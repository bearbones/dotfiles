"""Devspace daemon — asyncio Unix socket server managing SSH connections.

Runs as a background daemon (double-fork), accepts newline-delimited JSON
commands over a Unix domain socket, and manages SSH ControlMaster connections
to Coder devspaces with automatic health checking and reconnection.

Usage:
    python3 devspace_daemon.py start   # Daemonize and run
    python3 devspace_daemon.py stop    # Send shutdown signal
    python3 devspace_daemon.py status  # Print daemon status
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Add scripts dir to path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    CODER_WAIT_READY_ATTEMPTS,
    CODER_WAIT_READY_INTERVAL,
    DAEMON_VERSION,
    HEALTH_CHECK_INTERVAL,
    INVENTORY_FILE,
    LOG_FILE,
    MAX_LOG_SIZE,
    NETWORK_PROBE_HOST,
    NETWORK_PROBE_PORT,
    PID_FILE,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    SOCKET_PATH,
    SSH_CONNECT_TIMEOUT,
    SSH_CONTROL_PERSIST,
    SSH_DIR,
    SSH_SERVER_ALIVE_COUNT_MAX,
    SSH_SERVER_ALIVE_INTERVAL,
    DevspaceConfig,
    control_path,
    ensure_dirs,
    ssh_host,
)
from models import (
    ConnectionInfo,
    ConnectionState,
    DaemonStatus,
    DevspaceInfo,
    DevspaceState,
    Inventory,
    Platform,
    Request,
    Response,
)

logger = logging.getLogger("devspace-daemon")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def run_cmd(
    *args: str, timeout: Optional[float] = None
) -> tuple[int, str, str]:
    """Run a subprocess asynchronously, returning (exit_code, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return -1, "", f"Command not found: {args[0]}"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", "timeout"
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CoderClient — Coder CLI wrapper
# ---------------------------------------------------------------------------

class CoderClient:
    """Wraps the `coder` CLI for workspace lifecycle management."""

    def __init__(self, config: DevspaceConfig):
        self.config = config
        self._ssh_lock = asyncio.Lock()

    async def list_workspaces(self) -> list[dict[str, Any]]:
        """List all workspaces via `coder list --output json`."""
        rc, stdout, stderr = await run_cmd(self.config.coder_path, "list", "--output", "json", timeout=30)
        if rc != 0:
            logger.error("coder list failed: %s", stderr)
            return []
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            logger.error("coder list returned invalid JSON: %s", stdout[:200])
            return []

    async def create_workspace(
        self,
        name: str,
        template: Optional[str] = None,
        instance_type: Optional[str] = None,
        disk_size: Optional[int] = None,
        stop_after: Optional[str] = None,
        git_repo: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Create a new Coder workspace. Returns (success, message)."""
        tmpl = template or self.config.default_template
        cmd = [self.config.coder_path, "create", name, "-t", tmpl, "-y"]

        params: dict[str, str] = {}
        if git_repo or self.config.git_repo:
            params["git_repo"] = git_repo or self.config.git_repo
        if disk_size or self.config.default_disk_size:
            params["disk_size"] = str(disk_size or self.config.default_disk_size)
        if instance_type or self.config.default_instance_type:
            params["instance_type"] = instance_type or self.config.default_instance_type
        if self.config.dotfiles_uri:
            params["dotfiles_uri"] = self.config.dotfiles_uri
        if stop_after or self.config.default_stop_after:
            cmd.extend(["--stop-after", stop_after or self.config.default_stop_after])

        for k, v in params.items():
            cmd.extend(["--parameter", f"{k}={v}"])

        logger.info("Creating workspace: %s", " ".join(cmd))
        rc, stdout, stderr = await run_cmd(*cmd, timeout=300)
        if rc != 0:
            return False, f"coder create failed: {stderr.strip()}"
        return True, f"Workspace {name} created"

    async def start_workspace(self, name: str) -> tuple[bool, str]:
        rc, stdout, stderr = await run_cmd(self.config.coder_path, "start", name, "-y", timeout=120)
        if rc != 0:
            return False, f"coder start failed: {stderr.strip()}"
        return True, f"Workspace {name} started"

    async def stop_workspace(self, name: str) -> tuple[bool, str]:
        rc, stdout, stderr = await run_cmd(self.config.coder_path, "stop", name, "-y", timeout=60)
        if rc != 0:
            return False, f"coder stop failed: {stderr.strip()}"
        return True, f"Workspace {name} stopped"

    async def config_ssh(self) -> bool:
        """Run `coder config-ssh -y` with file locking to prevent concurrent writes."""
        async with self._ssh_lock:
            lock_path = SSH_DIR / "config-ssh.lock"
            lock_fd = None
            try:
                lock_fd = open(lock_path, "w")
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                rc, stdout, stderr = await run_cmd(self.config.coder_path, "config-ssh", "-y", timeout=30)
                if rc != 0:
                    logger.error("coder config-ssh failed: %s", stderr)
                    return False
                return True
            finally:
                if lock_fd:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()

    async def wait_for_ready(self, name: str, max_attempts: Optional[int] = None) -> bool:
        """Poll SSH connectivity until the workspace is ready."""
        attempts = max_attempts or CODER_WAIT_READY_ATTEMPTS
        host = ssh_host(name)
        for i in range(attempts):
            rc, stdout, stderr = await run_cmd(
                "ssh", "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
                host, "--", "echo", "ready",
                timeout=float(SSH_CONNECT_TIMEOUT + 5),
            )
            if rc == 0 and "ready" in stdout:
                if "workspace may be incomplete" not in stderr:
                    return True
            logger.info("Waiting for %s to be ready (attempt %d/%d)", name, i + 1, attempts)
            await asyncio.sleep(CODER_WAIT_READY_INTERVAL)
        return False

    async def detect_platform(self, name: str, cp: Path) -> Platform:
        """Detect remote OS via SSH. Returns Platform enum."""
        rc, stdout, stderr = await run_cmd(
            "ssh", "-o", f"ControlPath={cp}",
            ssh_host(name), "--",
            "uname -s 2>/dev/null || echo Windows",
            timeout=15,
        )
        if rc != 0:
            return Platform.UNKNOWN
        out = stdout.strip().lower()
        if "linux" in out:
            return Platform.LINUX
        elif "darwin" in out:
            return Platform.DARWIN
        elif "windows" in out or "mingw" in out or "msys" in out:
            return Platform.WINDOWS
        return Platform.UNKNOWN


# ---------------------------------------------------------------------------
# ConnectionManager — SSH ControlMaster lifecycle
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages SSH ControlMaster connections to devspaces."""

    def __init__(self, inventory: Inventory, config: DevspaceConfig, coder: CoderClient):
        self.inventory = inventory
        self.config = config
        self.coder = coder
        self._health_task: Optional[asyncio.Task] = None
        self._reconnect_delays: dict[str, float] = {}

    def _ssh_opts(self, name: str) -> list[str]:
        """Common SSH options for ControlMaster."""
        cp = str(control_path(name))
        return [
            "-o", f"ControlPath={cp}",
            "-o", f"ServerAliveInterval={SSH_SERVER_ALIVE_INTERVAL}",
            "-o", f"ServerAliveCountMax={SSH_SERVER_ALIVE_COUNT_MAX}",
            "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        ]

    async def connect(self, name: str) -> tuple[bool, str]:
        """Establish SSH ControlMaster connection to a devspace."""
        cp = control_path(name)
        host = ssh_host(name)

        # Already connected?
        if cp.exists():
            rc, _, _ = await run_cmd(
                "ssh", "-o", f"ControlPath={cp}", "-O", "check", host,
                timeout=10,
            )
            if rc == 0:
                return True, f"Already connected to {name}"

        # Ensure coder SSH config is up to date
        await self.coder.config_ssh()

        # Create connection info
        conn = self.inventory.connections.get(name, ConnectionInfo(devspace=name))
        conn.state = ConnectionState.CONNECTING
        conn.ssh_host = host
        conn.control_path = str(cp)
        self.inventory.connections[name] = conn

        # Start ControlMaster
        rc, stdout, stderr = await run_cmd(
            "ssh",
            "-o", f"ControlMaster=yes",
            "-o", f"ControlPath={cp}",
            "-o", f"ControlPersist={SSH_CONTROL_PERSIST}",
            "-o", f"ServerAliveInterval={SSH_SERVER_ALIVE_INTERVAL}",
            "-o", f"ServerAliveCountMax={SSH_SERVER_ALIVE_COUNT_MAX}",
            "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
            "-N", "-f",
            host,
            timeout=float(SSH_CONNECT_TIMEOUT + 10),
        )

        if rc != 0:
            conn.state = ConnectionState.FAILED
            self._save()
            return False, f"SSH ControlMaster failed: {stderr.strip()}"

        conn.state = ConnectionState.CONNECTED
        conn.connected_at = now_iso()
        conn.reconnect_attempts = 0
        self._reconnect_delays.pop(name, None)

        # Detect platform
        platform = await self.coder.detect_platform(name, cp)
        conn.platform = platform
        if name in self.inventory.devspaces:
            self.inventory.devspaces[name].platform = platform

        self._save()
        logger.info("Connected to %s (platform: %s)", name, platform.value)
        return True, f"Connected to {name} (platform: {platform.value})"

    async def disconnect(self, name: str) -> tuple[bool, str]:
        """Tear down SSH ControlMaster connection."""
        cp = control_path(name)
        host = ssh_host(name)

        if cp.exists():
            await run_cmd(
                "ssh", "-o", f"ControlPath={cp}", "-O", "exit", host,
                timeout=10,
            )

        conn = self.inventory.connections.get(name)
        if conn:
            conn.state = ConnectionState.DISCONNECTED
        self._save()
        return True, f"Disconnected from {name}"

    async def health_check(self, name: str) -> bool:
        """Check if a connection is alive."""
        cp = control_path(name)
        host = ssh_host(name)

        if not cp.exists():
            return False

        rc, _, _ = await run_cmd(
            "ssh", "-o", f"ControlPath={cp}", "-O", "check", host,
            timeout=10,
        )
        conn = self.inventory.connections.get(name)
        if conn:
            conn.last_health_check = now_iso()
            if rc == 0:
                conn.state = ConnectionState.CONNECTED
            else:
                conn.state = ConnectionState.DISCONNECTED
            self._save()
        return rc == 0

    async def ssh_exec(
        self, name: str, command: str, timeout: float = 60
    ) -> tuple[int, str, str]:
        """Execute a command on a devspace via multiplexed SSH."""
        cp = control_path(name)
        host = ssh_host(name)

        if not cp.exists():
            return -1, "", "Not connected (no ControlMaster socket)"

        return await run_cmd(
            "ssh", "-o", f"ControlPath={cp}", host, "--", command,
            timeout=timeout,
        )

    async def health_check_loop(self) -> None:
        """Periodic health check for all connections. Reconnects dead ones."""
        while True:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                for name, conn in list(self.inventory.connections.items()):
                    if conn.state in (ConnectionState.DISCONNECTED, ConnectionState.FAILED):
                        continue
                    alive = await self.health_check(name)
                    if not alive and self.config.auto_reconnect:
                        await self._reconnect(name)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Error in health check loop")

    async def _reconnect(self, name: str) -> None:
        """Attempt to reconnect with exponential backoff."""
        conn = self.inventory.connections.get(name)
        if not conn:
            return

        conn.state = ConnectionState.RECONNECTING
        conn.reconnect_attempts += 1
        self._save()

        # Check network first
        if not await self._network_available():
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** min(conn.reconnect_attempts - 1, 4)),
                RECONNECT_MAX_DELAY,
            )
            self._reconnect_delays[name] = delay
            logger.info("Network unavailable, will retry %s in %ds", name, delay)
            await asyncio.sleep(delay)
            return

        logger.info("Reconnecting to %s (attempt %d)", name, conn.reconnect_attempts)
        ok, msg = await self.connect(name)
        if not ok:
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** min(conn.reconnect_attempts - 1, 4)),
                RECONNECT_MAX_DELAY,
            )
            logger.warning("Reconnect to %s failed: %s (retry in %ds)", name, msg, delay)
            await asyncio.sleep(delay)

    async def _network_available(self) -> bool:
        """Quick TCP probe to check network connectivity."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(NETWORK_PROBE_HOST, NETWORK_PROBE_PORT),
                timeout=5,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    async def disconnect_all(self) -> None:
        """Tear down all active connections."""
        for name in list(self.inventory.connections):
            await self.disconnect(name)

    def start_health_checks(self) -> None:
        self._health_task = asyncio.create_task(self.health_check_loop())

    def stop_health_checks(self) -> None:
        if self._health_task:
            self._health_task.cancel()

    def _save(self) -> None:
        self.inventory.save(str(INVENTORY_FILE))


# ---------------------------------------------------------------------------
# DaemonServer — asyncio Unix socket server
# ---------------------------------------------------------------------------

class DaemonServer:
    """Main daemon: listens on Unix socket, dispatches JSON commands."""

    def __init__(self):
        self.config = DevspaceConfig.load()
        self.inventory = Inventory.load(str(INVENTORY_FILE))
        self.coder = CoderClient(self.config)
        self.connections = ConnectionManager(self.inventory, self.config, self.coder)
        self._server: Optional[asyncio.AbstractServer] = None
        self._started_at = now_iso()
        self._shutdown_event = asyncio.Event()

    # --- Command Dispatch ---

    async def dispatch(self, request: Request) -> Response:
        """Route a request to the appropriate handler."""
        handlers: dict[str, Callable] = {
            "daemon.status": self._handle_daemon_status,
            "daemon.shutdown": self._handle_daemon_shutdown,
            "list": self._handle_list,
            "create": self._handle_create,
            "start": self._handle_start,
            "stop": self._handle_stop,
            "connect": self._handle_connect,
            "disconnect": self._handle_disconnect,
            "exec": self._handle_exec,
            "status": self._handle_status,
            "health_check": self._handle_health_check,
        }
        handler = handlers.get(request.action)
        if not handler:
            return Response(ok=False, error=f"Unknown action: {request.action}")
        try:
            return await handler(request.params)
        except Exception as e:
            logger.exception("Error handling %s", request.action)
            return Response(ok=False, error=str(e))

    async def _handle_daemon_status(self, params: dict) -> Response:
        status = DaemonStatus(
            pid=os.getpid(),
            started_at=self._started_at,
            uptime_seconds=time.time() - datetime.fromisoformat(self._started_at).timestamp(),
            connections=dict(self.inventory.connections),
            version=DAEMON_VERSION,
        )
        return Response(ok=True, data=status.to_dict())

    async def _handle_daemon_shutdown(self, params: dict) -> Response:
        logger.info("Shutdown requested")
        self._shutdown_event.set()
        return Response(ok=True, data="Shutting down")

    async def _handle_list(self, params: dict) -> Response:
        workspaces = await self.coder.list_workspaces()
        infos = []
        for ws in workspaces:
            info = DevspaceInfo.from_coder_json(ws)
            # Merge connection state if we're tracking this devspace
            if info.name in self.inventory.connections:
                info.connection = self.inventory.connections[info.name].state
                info.platform = self.inventory.connections[info.name].platform
            self.inventory.devspaces[info.name] = info
            infos.append(info.to_dict())
        self.inventory.save(str(INVENTORY_FILE))
        return Response(ok=True, data=infos)

    async def _handle_create(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        ok, msg = await self.coder.create_workspace(
            name,
            template=params.get("template"),
            instance_type=params.get("instance_type"),
            disk_size=params.get("disk_size"),
            stop_after=params.get("stop_after"),
            git_repo=params.get("git_repo"),
        )
        if ok and self.config.auto_connect:
            # Wait for ready then connect
            await self.coder.config_ssh()
            ready = await self.coder.wait_for_ready(name)
            if ready:
                await self.connections.connect(name)
                msg += " (connected)"
            else:
                msg += " (created but not yet ready for SSH)"
        return Response(ok=ok, data=msg if ok else None, error=msg if not ok else None)

    async def _handle_start(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        ok, msg = await self.coder.start_workspace(name)
        if ok and self.config.auto_connect:
            await self.coder.config_ssh()
            ready = await self.coder.wait_for_ready(name)
            if ready:
                await self.connections.connect(name)
                msg += " (connected)"
        return Response(ok=ok, data=msg if ok else None, error=msg if not ok else None)

    async def _handle_stop(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        # Disconnect first
        if name in self.inventory.connections:
            await self.connections.disconnect(name)
        ok, msg = await self.coder.stop_workspace(name)
        return Response(ok=ok, data=msg if ok else None, error=msg if not ok else None)

    async def _handle_connect(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        ok, msg = await self.connections.connect(name)
        return Response(ok=ok, data=msg if ok else None, error=msg if not ok else None)

    async def _handle_disconnect(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        ok, msg = await self.connections.disconnect(name)
        return Response(ok=ok, data=msg if ok else None, error=msg if not ok else None)

    async def _handle_exec(self, params: dict) -> Response:
        name = params.get("name")
        command = params.get("command")
        if not name or not command:
            return Response(ok=False, error="Missing 'name' or 'command' parameter")
        timeout = float(params.get("timeout", 60))
        rc, stdout, stderr = await self.connections.ssh_exec(name, command, timeout=timeout)
        return Response(
            ok=(rc == 0),
            data={"exit_code": rc, "stdout": stdout, "stderr": stderr},
            error=stderr if rc != 0 else None,
        )

    async def _handle_status(self, params: dict) -> Response:
        name = params.get("name")
        if name:
            conn = self.inventory.connections.get(name)
            if not conn:
                return Response(ok=True, data={"name": name, "connection": "none"})
            return Response(ok=True, data=conn.to_dict())
        # All connections
        result = {k: v.to_dict() for k, v in self.inventory.connections.items()}
        return Response(ok=True, data=result)

    async def _handle_health_check(self, params: dict) -> Response:
        name = params.get("name")
        if not name:
            return Response(ok=False, error="Missing 'name' parameter")
        alive = await self.connections.health_check(name)
        return Response(ok=True, data={"name": name, "alive": alive})

    # --- Server Lifecycle ---

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection (one request-response per line)."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = Request.from_json(line.decode().strip())
                except (json.JSONDecodeError, KeyError) as e:
                    resp = Response(ok=False, error=f"Invalid request: {e}")
                    writer.write((resp.to_json() + "\n").encode())
                    await writer.drain()
                    continue

                response = await self.dispatch(request)
                writer.write((response.to_json() + "\n").encode())
                await writer.drain()
        except ConnectionResetError:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        """Start the daemon server."""
        ensure_dirs()

        # Clean stale socket
        sock_path = str(SOCKET_PATH)
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except OSError:
                pass

        self._server = await asyncio.start_unix_server(
            self.handle_client, path=sock_path
        )
        os.chmod(sock_path, 0o600)

        # Write PID file
        with open(PID_FILE, "w") as f:
            f.write(f"{os.getpid()}\n{self._started_at}\n")

        # Start health check loop
        self.connections.start_health_checks()

        logger.info("Daemon started (pid=%d, socket=%s)", os.getpid(), sock_path)

        # Wait for shutdown signal
        await self._shutdown_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown: disconnect all, clean up files."""
        logger.info("Shutting down daemon...")

        # Stop accepting new connections first
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Brief grace period for in-flight client handlers to finish
        await asyncio.sleep(0.1)

        self.connections.stop_health_checks()
        await self.connections.disconnect_all()

        # Clean up files
        for f in [PID_FILE, SOCKET_PATH]:
            try:
                f.unlink()
            except OSError:
                pass

        self.inventory.save(str(INVENTORY_FILE))
        logger.info("Daemon stopped")


# ---------------------------------------------------------------------------
# Daemonization
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure logging to daemon.log with rotation."""
    ensure_dirs()

    # Rotate if too large
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        rotated = LOG_FILE.with_suffix(".log.1")
        try:
            LOG_FILE.rename(rotated)
        except OSError:
            pass

    handler = logging.FileHandler(str(LOG_FILE))
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def check_stale_pid() -> Optional[int]:
    """Check if a daemon is already running. Returns PID if alive, None if stale/absent.

    Uses socket connectivity as the liveness check because os.kill(pid, 0)
    fails with EPERM on macOS for processes in different sessions (post-setsid).
    """
    if not PID_FILE.exists():
        return None
    try:
        pid_str = PID_FILE.read_text().strip().split("\n")[0]
        pid = int(pid_str)
    except (ValueError, OSError):
        _clean_stale_artifacts()
        return None

    # Try connecting to the socket — this proves the daemon is alive and responsive
    if SOCKET_PATH.exists():
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(SOCKET_PATH))
            sock.close()
            return pid
        except OSError:
            pass

    # Socket gone or unresponsive — check if PID is still alive as fallback
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        pass

    _clean_stale_artifacts()
    return None


def _clean_stale_artifacts() -> None:
    """Remove stale PID file and socket."""
    for f in [PID_FILE, SOCKET_PATH]:
        try:
            f.unlink()
        except OSError:
            pass


def daemonize() -> None:
    """Double-fork to fully detach from terminal."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent — wait briefly for child to set up, then exit
        sys.exit(0)

    # Create new session
    os.setsid()

    # Second fork — prevent reacquiring terminal
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect stdio to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)


def cmd_start(foreground: bool = False) -> None:
    """Start the daemon."""
    existing = check_stale_pid()
    if existing:
        print(f"Daemon already running (pid={existing})")
        sys.exit(1)

    if not foreground:
        daemonize()

    setup_logging()
    logger.info("Starting daemon (pid=%d)", os.getpid())

    # Handle SIGTERM for graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    server = DaemonServer()

    def handle_sigterm(*_):
        server._shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        loop.run_until_complete(server.shutdown())
    finally:
        loop.close()


def cmd_stop() -> None:
    """Stop the daemon."""
    pid = check_stale_pid()
    if not pid:
        print("Daemon is not running")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (pid={pid})")
        # Wait briefly for clean shutdown
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.25)
            except OSError:
                print("Daemon stopped")
                return
        print("Daemon did not stop within 5 seconds")
    except OSError as e:
        print(f"Failed to stop daemon: {e}")


def cmd_status() -> None:
    """Print daemon status."""
    pid = check_stale_pid()
    if not pid:
        print("Daemon is not running")
        sys.exit(1)
    # Read PID file for start time
    try:
        lines = PID_FILE.read_text().strip().split("\n")
        started = lines[1] if len(lines) > 1 else "unknown"
    except OSError:
        started = "unknown"
    print(f"Daemon running (pid={pid}, started={started})")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: devspace_daemon.py {start|stop|status} [--foreground]")
        sys.exit(1)

    cmd = sys.argv[1]
    foreground = "--foreground" in sys.argv

    if cmd == "start":
        cmd_start(foreground=foreground)
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
