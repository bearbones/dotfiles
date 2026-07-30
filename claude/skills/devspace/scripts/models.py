"""Data models for devspace manager.

Defines the core types used across daemon, CLI, and session management.
All models are stdlib-only dataclasses for zero-dependency operation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class DevspaceState(str, Enum):
    """Workspace lifecycle states from Coder API."""
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


class ConnectionState(str, Enum):
    """SSH ControlMaster connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class SessionState(str, Enum):
    """Remote persistent session states (Phase 2)."""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class Platform(str, Enum):
    """Remote devspace platform, detected via SSH."""
    LINUX = "linux"
    DARWIN = "darwin"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


@dataclass
class DevspaceInfo:
    """Represents a Coder workspace with connection metadata."""
    name: str
    template_name: str = ""
    state: DevspaceState = DevspaceState.UNKNOWN
    owner: str = ""
    last_used_at: Optional[str] = None
    instance_type: Optional[str] = None
    platform: Platform = Platform.UNKNOWN
    connection: ConnectionState = ConnectionState.DISCONNECTED
    autostop_hours: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["platform"] = self.platform.value
        d["connection"] = self.connection.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevspaceInfo:
        data = dict(data)
        data["state"] = DevspaceState(data.get("state", "unknown"))
        data["platform"] = Platform(data.get("platform", "unknown"))
        data["connection"] = ConnectionState(data.get("connection", "disconnected"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_coder_json(cls, data: dict[str, Any]) -> DevspaceInfo:
        """Create from `coder list --output json` entry."""
        status = data.get("latest_build", {}).get("status", "unknown")
        try:
            state = DevspaceState(status)
        except ValueError:
            state = DevspaceState.UNKNOWN
        return cls(
            name=data.get("name", ""),
            template_name=data.get("template_name", ""),
            state=state,
            owner=data.get("owner_name", ""),
            last_used_at=data.get("last_used_at"),
        )


@dataclass
class ConnectionInfo:
    """Tracks an active SSH ControlMaster connection."""
    devspace: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    ssh_host: str = ""
    control_path: str = ""
    connected_at: Optional[str] = None
    last_health_check: Optional[str] = None
    reconnect_attempts: int = 0
    platform: Platform = Platform.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["platform"] = self.platform.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionInfo:
        data = dict(data)
        data["state"] = ConnectionState(data.get("state", "disconnected"))
        data["platform"] = Platform(data.get("platform", "unknown"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionInfo:
    """Tracks a remote persistent session (Phase 2)."""
    name: str
    devspace: str
    state: SessionState = SessionState.CREATED
    command: str = ""
    cwd: str = ""
    platform: Platform = Platform.UNKNOWN
    backend: str = ""  # "tmux" or "powershell"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    exit_code: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["platform"] = self.platform.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionInfo:
        data = dict(data)
        data["state"] = SessionState(data.get("state", "created"))
        data["platform"] = Platform(data.get("platform", "unknown"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DaemonStatus:
    """Status snapshot of the running daemon."""
    pid: int
    started_at: str
    uptime_seconds: float
    connections: dict[str, ConnectionInfo] = field(default_factory=dict)
    version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "started_at": self.started_at,
            "uptime_seconds": self.uptime_seconds,
            "connections": {k: v.to_dict() for k, v in self.connections.items()},
            "version": self.version,
        }


@dataclass
class Inventory:
    """Persisted state across daemon restarts."""
    devspaces: dict[str, DevspaceInfo] = field(default_factory=dict)
    connections: dict[str, ConnectionInfo] = field(default_factory=dict)
    sessions: dict[str, SessionInfo] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "devspaces": {k: v.to_dict() for k, v in self.devspaces.items()},
            "connections": {k: v.to_dict() for k, v in self.connections.items()},
            "sessions": {k: v.to_dict() for k, v in self.sessions.items()},
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Inventory:
        inv = cls()
        for k, v in data.get("devspaces", {}).items():
            inv.devspaces[k] = DevspaceInfo.from_dict(v)
        for k, v in data.get("connections", {}).items():
            inv.connections[k] = ConnectionInfo.from_dict(v)
        for k, v in data.get("sessions", {}).items():
            inv.sessions[k] = SessionInfo.from_dict(v)
        inv.updated_at = data.get("updated_at", "")
        return inv

    def save(self, path: str) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        import os
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> Inventory:
        try:
            with open(path) as f:
                return cls.from_dict(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()


# --- Protocol Messages ---

@dataclass
class Request:
    """Client-to-daemon request over Unix socket."""
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"action": self.action, "params": self.params})

    @classmethod
    def from_json(cls, line: str) -> Request:
        data = json.loads(line)
        return cls(action=data["action"], params=data.get("params", {}))


@dataclass
class Response:
    """Daemon-to-client response over Unix socket."""
    ok: bool
    data: Any = None
    error: Optional[str] = None

    def to_json(self) -> str:
        d: dict[str, Any] = {"ok": self.ok}
        if self.data is not None:
            d["data"] = self.data
        if self.error is not None:
            d["error"] = self.error
        return json.dumps(d)

    @classmethod
    def from_json(cls, line: str) -> Response:
        data = json.loads(line)
        return cls(ok=data["ok"], data=data.get("data"), error=data.get("error"))
