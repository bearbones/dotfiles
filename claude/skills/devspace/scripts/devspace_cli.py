"""CLI client for devspace daemon.

Communicates with the daemon over a Unix domain socket using
newline-delimited JSON. Falls back to direct Coder CLI calls
when the daemon is not running for read-only operations (list).

Usage:
    devspace_cli.py daemon {start|stop|status}
    devspace_cli.py list
    devspace_cli.py create <name> [--template T] [--instance-type T]
    devspace_cli.py start <name>
    devspace_cli.py stop <name>
    devspace_cli.py connect <name>
    devspace_cli.py disconnect <name>
    devspace_cli.py exec <name> <command...>
    devspace_cli.py status [name]
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Add scripts dir for sibling imports
sys.path.insert(0, str(Path(__file__).parent))

from config import PID_FILE, SOCKET_PATH, ensure_dirs
from models import Request, Response


# ---------------------------------------------------------------------------
# Socket Communication
# ---------------------------------------------------------------------------

def send_request(action: str, params: Optional[dict[str, Any]] = None) -> Response:
    """Send a request to the daemon and return the response."""
    req = Request(action=action, params=params or {})
    sock_path = str(SOCKET_PATH)

    if not SOCKET_PATH.exists():
        return Response(ok=False, error="Daemon is not running (no socket). Run: devspace daemon start")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(300)  # 5 min for long operations like create
        sock.connect(sock_path)
        sock.sendall((req.to_json() + "\n").encode())

        # Read response (buffered readline)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                return Response(ok=False, error="Daemon closed connection")
            buf += chunk

        line = buf.split(b"\n")[0].decode()
        return Response.from_json(line)
    except socket.timeout:
        return Response(ok=False, error="Request timed out")
    except ConnectionRefusedError:
        return Response(ok=False, error="Daemon refused connection. Try: devspace daemon start")
    except OSError as e:
        return Response(ok=False, error=f"Socket error: {e}")
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Output Formatting
# ---------------------------------------------------------------------------

def print_response(resp: Response, raw: bool = False) -> int:
    """Print a response and return exit code."""
    if raw:
        print(json.dumps({"ok": resp.ok, "data": resp.data, "error": resp.error}, indent=2))
        return 0 if resp.ok else 1

    if not resp.ok:
        print(f"Error: {resp.error}", file=sys.stderr)
        return 1

    if isinstance(resp.data, str):
        print(resp.data)
    elif isinstance(resp.data, list):
        _print_workspace_table(resp.data)
    elif isinstance(resp.data, dict):
        if "stdout" in resp.data:
            # exec response
            if resp.data.get("stdout"):
                sys.stdout.write(resp.data["stdout"])
            if resp.data.get("stderr"):
                sys.stderr.write(resp.data["stderr"])
            return resp.data.get("exit_code", 0)
        elif "pid" in resp.data:
            _print_daemon_status(resp.data)
        elif "devspace" in resp.data:
            _print_connection(resp.data)
        else:
            # Connection status map or generic dict
            if all(isinstance(v, dict) for v in resp.data.values()):
                _print_connections(resp.data)
            else:
                print(json.dumps(resp.data, indent=2))
    else:
        print(resp.data)
    return 0


def _print_workspace_table(workspaces: list[dict]) -> None:
    """Pretty-print workspace list as a table."""
    if not workspaces:
        print("No workspaces found")
        return

    # Header
    fmt = "{:<25} {:<15} {:<10} {:<12} {:<10}"
    print(fmt.format("NAME", "TEMPLATE", "STATE", "CONNECTION", "PLATFORM"))
    print("-" * 75)

    for ws in workspaces:
        print(fmt.format(
            ws.get("name", "")[:25],
            ws.get("template_name", "")[:15],
            ws.get("state", "unknown")[:10],
            ws.get("connection", "none")[:12],
            ws.get("platform", "unknown")[:10],
        ))


def _print_daemon_status(data: dict) -> None:
    """Pretty-print daemon status."""
    uptime = int(data.get("uptime_seconds", 0))
    h, m = divmod(uptime // 60, 60)
    s = uptime % 60
    conns = data.get("connections", {})
    active = sum(1 for c in conns.values() if c.get("state") == "connected")

    print(f"Daemon: running (pid={data['pid']}, v{data.get('version', '?')})")
    print(f"Uptime: {h}h {m}m {s}s")
    print(f"Started: {data.get('started_at', '?')}")
    print(f"Connections: {active} active / {len(conns)} total")

    if conns:
        print()
        _print_connections(conns)


def _print_connection(data: dict) -> None:
    """Pretty-print a single connection."""
    print(f"  {data.get('devspace', '?')}: {data.get('state', '?')} "
          f"(platform={data.get('platform', '?')})")


def _print_connections(conns: dict) -> None:
    """Pretty-print multiple connections."""
    fmt = "  {:<25} {:<15} {:<10}"
    print(fmt.format("DEVSPACE", "STATE", "PLATFORM"))
    print("  " + "-" * 50)
    for name, info in sorted(conns.items()):
        if isinstance(info, dict):
            print(fmt.format(name[:25], info.get("state", "?")[:15], info.get("platform", "?")[:10]))


# ---------------------------------------------------------------------------
# Daemon Subcommands (handled locally, not via socket)
# ---------------------------------------------------------------------------

def daemon_start(foreground: bool = False) -> int:
    """Start the daemon process."""
    ensure_dirs()

    # Check if already running before spawning (use socket probe — os.kill fails
    # with EPERM on macOS for processes in different sessions after setsid)
    if PID_FILE.exists() and SOCKET_PATH.exists():
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(SOCKET_PATH))
            sock.close()
            pid = PID_FILE.read_text().strip().split("\n")[0]
            print(f"Daemon already running (pid={pid})")
            return 1
        except OSError:
            # Socket unresponsive — stale artifacts, clean up
            for f in [PID_FILE, SOCKET_PATH]:
                try:
                    f.unlink()
                except OSError:
                    pass

    daemon_script = Path(__file__).parent / "devspace_daemon.py"
    args = [sys.executable, str(daemon_script), "start"]
    if foreground:
        args.append("--foreground")
        os.execv(sys.executable, args)
        return 0  # unreachable

    # Launch daemon in background
    proc = subprocess.Popen(
        args,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # The daemon double-forks, so this parent exits quickly
    rc = proc.wait()
    if rc != 0:
        # Daemon script rejected start (e.g., already running)
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip().split("\n")[0]
            print(f"Daemon already running (pid={pid})")
        else:
            print("Daemon failed to start. Check ~/.claude/devspace/daemon.log", file=sys.stderr)
        return 1

    # Verify it started
    import time
    for _ in range(10):
        time.sleep(0.3)
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip().split("\n")[0]
            print(f"Daemon started (pid={pid})")
            return 0

    print("Daemon may have failed to start. Check ~/.claude/devspace/daemon.log", file=sys.stderr)
    return 1


def daemon_stop() -> int:
    """Stop the daemon."""
    if SOCKET_PATH.exists():
        resp = send_request("daemon.shutdown")
        if resp.ok:
            import time
            for _ in range(20):
                time.sleep(0.25)
                if not PID_FILE.exists():
                    print("Daemon stopped")
                    return 0
            print("Daemon shutdown in progress...")
            return 0
        # Fall back to direct signal
    # Try direct PID kill
    daemon_script = Path(__file__).parent / "devspace_daemon.py"
    result = subprocess.run([sys.executable, str(daemon_script), "stop"], capture_output=True, text=True)
    print(result.stdout.strip())
    return result.returncode


def daemon_status() -> int:
    """Show daemon status."""
    if SOCKET_PATH.exists():
        resp = send_request("daemon.status")
        return print_response(resp)
    # Fallback to PID check
    daemon_script = Path(__file__).parent / "devspace_daemon.py"
    result = subprocess.run([sys.executable, str(daemon_script), "status"], capture_output=True, text=True)
    print(result.stdout.strip())
    return result.returncode


# ---------------------------------------------------------------------------
# Argument Parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> int:
    """Parse CLI arguments and execute. Returns exit code."""
    if not argv:
        print_usage()
        return 1

    raw = "--json" in argv
    argv = [a for a in argv if a != "--json"]

    cmd = argv[0]

    # Daemon subcommands
    if cmd == "daemon":
        if len(argv) < 2:
            print("Usage: devspace daemon {start|stop|status} [--foreground]")
            return 1
        sub = argv[1]
        if sub == "start":
            return daemon_start(foreground="--foreground" in argv)
        elif sub == "stop":
            return daemon_stop()
        elif sub == "status":
            return daemon_status()
        else:
            print(f"Unknown daemon command: {sub}")
            return 1

    # Commands that go through the daemon socket
    if cmd == "list":
        resp = send_request("list")
        return print_response(resp, raw=raw)

    elif cmd == "create":
        if len(argv) < 2:
            print("Usage: devspace create <name> [--template T] [--instance-type T] [--disk-size N]")
            return 1
        params: dict[str, Any] = {"name": argv[1]}
        i = 2
        while i < len(argv):
            if argv[i] == "--template" and i + 1 < len(argv):
                params["template"] = argv[i + 1]; i += 2
            elif argv[i] == "--instance-type" and i + 1 < len(argv):
                params["instance_type"] = argv[i + 1]; i += 2
            elif argv[i] == "--disk-size" and i + 1 < len(argv):
                params["disk_size"] = int(argv[i + 1]); i += 2
            elif argv[i] == "--stop-after" and i + 1 < len(argv):
                params["stop_after"] = argv[i + 1]; i += 2
            elif argv[i] == "--git-repo" and i + 1 < len(argv):
                params["git_repo"] = argv[i + 1]; i += 2
            else:
                i += 1
        resp = send_request("create", params)
        return print_response(resp, raw=raw)

    elif cmd == "start":
        if len(argv) < 2:
            print("Usage: devspace start <name>"); return 1
        resp = send_request("start", {"name": argv[1]})
        return print_response(resp, raw=raw)

    elif cmd == "stop":
        if len(argv) < 2:
            print("Usage: devspace stop <name>"); return 1
        resp = send_request("stop", {"name": argv[1]})
        return print_response(resp, raw=raw)

    elif cmd == "connect":
        if len(argv) < 2:
            print("Usage: devspace connect <name>"); return 1
        resp = send_request("connect", {"name": argv[1]})
        return print_response(resp, raw=raw)

    elif cmd == "disconnect":
        if len(argv) < 2:
            print("Usage: devspace disconnect <name>"); return 1
        resp = send_request("disconnect", {"name": argv[1]})
        return print_response(resp, raw=raw)

    elif cmd == "exec":
        if len(argv) < 3:
            print("Usage: devspace exec <name> <command...>"); return 1
        name = argv[1]
        command = " ".join(argv[2:])
        resp = send_request("exec", {"name": name, "command": command})
        return print_response(resp, raw=raw)

    elif cmd == "status":
        params = {}
        if len(argv) >= 2:
            params["name"] = argv[1]
        resp = send_request("status", params)
        return print_response(resp, raw=raw)

    else:
        print(f"Unknown command: {cmd}")
        print_usage()
        return 1


def print_usage() -> None:
    print("""Usage: devspace <command> [args...] [--json]

Daemon:
  daemon start [--foreground]   Start the devspace daemon
  daemon stop                   Stop the daemon
  daemon status                 Show daemon status

Workspaces:
  list                          List all devspaces
  create <name> [options]       Create a new devspace
  start <name>                  Start a stopped devspace
  stop <name>                   Stop a devspace

Connections:
  connect <name>                Establish SSH connection
  disconnect <name>             Tear down connection
  exec <name> <command...>      Run command on devspace
  status [name]                 Show connection status

Options:
  --json                        Output raw JSON responses""")


def main() -> None:
    sys.exit(parse_args(sys.argv[1:]))


if __name__ == "__main__":
    main()
