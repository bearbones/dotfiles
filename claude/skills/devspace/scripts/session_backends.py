"""Session backend abstraction for remote persistent sessions.

Phase 1: ABC + stubs only. Full implementation in Phase 2.

The daemon auto-detects the remote platform on first SSH connection
and selects the appropriate backend:
  - Linux/macOS: TmuxBackend (full interactivity via pipe-pane, send-keys)
  - Windows native: PowerShellBackend (fire-and-forget with output capture)
  - Windows + WSL: TmuxBackend via WSL prefix
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from models import Platform


class SessionBackend(ABC):
    """Abstract interface for remote session management.

    Each backend wraps a platform-specific mechanism for running
    persistent processes that survive SSH disconnects.
    """

    platform: Platform

    @abstractmethod
    async def create(self, ssh_exec, name: str, cwd: str, command: Optional[str] = None) -> bool:
        """Create a new persistent session on the remote host.

        Args:
            ssh_exec: Callable(cmd, timeout) -> (exit_code, stdout, stderr)
            name: Session name (unique per devspace)
            cwd: Working directory on the remote host
            command: Optional initial command to run

        Returns:
            True if session was created successfully.
        """
        ...

    @abstractmethod
    async def send(self, ssh_exec, name: str, command: str) -> bool:
        """Send a command to an existing session.

        Args:
            ssh_exec: Callable(cmd, timeout) -> (exit_code, stdout, stderr)
            name: Session name
            command: Command text to execute

        Returns:
            True if command was sent successfully.
        """
        ...

    @abstractmethod
    async def read_output(self, ssh_exec, name: str, lines: int = 50) -> str:
        """Read recent output from a session.

        Args:
            ssh_exec: Callable(cmd, timeout) -> (exit_code, stdout, stderr)
            name: Session name
            lines: Number of trailing lines to read

        Returns:
            Output text (may be empty if no output yet).
        """
        ...

    @abstractmethod
    async def is_alive(self, ssh_exec, name: str) -> bool:
        """Check if a session is still running.

        Args:
            ssh_exec: Callable(cmd, timeout) -> (exit_code, stdout, stderr)
            name: Session name

        Returns:
            True if the session process is alive.
        """
        ...

    @abstractmethod
    async def kill(self, ssh_exec, name: str) -> bool:
        """Kill a running session.

        Args:
            ssh_exec: Callable(cmd, timeout) -> (exit_code, stdout, stderr)
            name: Session name

        Returns:
            True if the session was killed (or was already dead).
        """
        ...


class TmuxBackend(SessionBackend):
    """Session backend using tmux (Linux, macOS, Windows+WSL).

    Phase 2 implementation will use:
      - create: tmux new-session -d -s <name> -c <cwd> + pipe-pane for output capture
      - send:   tmux send-keys -t <name> '<cmd>' Enter
      - read:   tail -n <lines> ~/devspace-sessions/<name>/output.log
      - alive:  tmux has-session -t <name>
      - kill:   tmux kill-session -t <name>
    """

    platform = Platform.LINUX  # Also works for DARWIN

    def __init__(self, wsl_prefix: bool = False):
        """Args:
            wsl_prefix: If True, prefix tmux commands with 'wsl' (Windows+WSL mode).
        """
        self.wsl_prefix = wsl_prefix

    async def create(self, ssh_exec, name: str, cwd: str, command: Optional[str] = None) -> bool:
        raise NotImplementedError("TmuxBackend.create() is Phase 2")

    async def send(self, ssh_exec, name: str, command: str) -> bool:
        raise NotImplementedError("TmuxBackend.send() is Phase 2")

    async def read_output(self, ssh_exec, name: str, lines: int = 50) -> str:
        raise NotImplementedError("TmuxBackend.read_output() is Phase 2")

    async def is_alive(self, ssh_exec, name: str) -> bool:
        raise NotImplementedError("TmuxBackend.is_alive() is Phase 2")

    async def kill(self, ssh_exec, name: str) -> bool:
        raise NotImplementedError("TmuxBackend.kill() is Phase 2")


class PowerShellBackend(SessionBackend):
    """Session backend using detached PowerShell processes (Windows native).

    Phase 2 implementation will use:
      - create: Start-Process powershell -WindowStyle Hidden -RedirectStandardOutput <out> ...
      - send:   Not supported (each command is a new detached process)
      - read:   Get-Content -Tail <n> <output_file>
      - alive:  Get-Process -Id <pid> -ErrorAction SilentlyContinue
      - kill:   Stop-Process -Id <pid> -Force

    Limitation: No send-keys equivalent. For interactive work, use WSL+tmux.
    """

    platform = Platform.WINDOWS

    async def create(self, ssh_exec, name: str, cwd: str, command: Optional[str] = None) -> bool:
        raise NotImplementedError("PowerShellBackend.create() is Phase 2")

    async def send(self, ssh_exec, name: str, command: str) -> bool:
        raise NotImplementedError("PowerShellBackend: send() not supported for Windows native. Use WSL+tmux for interactive sessions.")

    async def read_output(self, ssh_exec, name: str, lines: int = 50) -> str:
        raise NotImplementedError("PowerShellBackend.read_output() is Phase 2")

    async def is_alive(self, ssh_exec, name: str) -> bool:
        raise NotImplementedError("PowerShellBackend.is_alive() is Phase 2")

    async def kill(self, ssh_exec, name: str) -> bool:
        raise NotImplementedError("PowerShellBackend.kill() is Phase 2")


def backend_for_platform(platform: Platform) -> SessionBackend:
    """Select the appropriate session backend for a platform."""
    if platform == Platform.WINDOWS:
        return PowerShellBackend()
    # Linux, Darwin, and Unknown all get tmux
    return TmuxBackend()
