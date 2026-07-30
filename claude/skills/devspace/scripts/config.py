"""Configuration and path constants for devspace manager.

All paths are anchored under ~/.claude/devspace/ for state and
~/.claude/skills/devspace/ for code. Config is loaded from YAML
if present, falling back to sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# --- Path Constants ---

HOME = Path.home()
STATE_DIR = HOME / ".claude" / "devspace"
SKILL_DIR = HOME / ".claude" / "skills" / "devspace"
SCRIPTS_DIR = SKILL_DIR / "scripts"

# Daemon files
PID_FILE = STATE_DIR / "daemon.pid"
SOCKET_PATH = STATE_DIR / "daemon.sock"
LOG_FILE = STATE_DIR / "daemon.log"
INVENTORY_FILE = STATE_DIR / "inventory.json"
CONFIG_FILE = STATE_DIR / "config.yaml"

# SSH
SSH_DIR = STATE_DIR / "ssh"

# Sessions (Phase 2)
SESSIONS_DIR = STATE_DIR / "sessions"


def control_path(devspace_name: str) -> Path:
    """SSH ControlMaster socket path for a devspace."""
    return SSH_DIR / f"{devspace_name}.sock"


def ssh_host(devspace_name: str) -> str:
    """SSH host alias as configured by `coder config-ssh`."""
    return f"coder.{devspace_name}"


# --- SSH Settings ---

SSH_CONTROL_PERSIST = 300       # seconds to keep ControlMaster alive after last channel
SSH_SERVER_ALIVE_INTERVAL = 15  # seconds between keepalive probes
SSH_SERVER_ALIVE_COUNT_MAX = 3  # missed probes before declaring dead
SSH_CONNECT_TIMEOUT = 10        # seconds for initial connection

# --- Daemon Settings ---

HEALTH_CHECK_INTERVAL = 30      # seconds between connection health checks
RECONNECT_BASE_DELAY = 10      # seconds initial reconnect backoff
RECONNECT_MAX_DELAY = 60       # seconds max reconnect backoff
NETWORK_PROBE_HOST = "devspaces.rbx.com"
NETWORK_PROBE_PORT = 443

# Coder
CODER_WAIT_READY_ATTEMPTS = 15
CODER_WAIT_READY_INTERVAL = 20  # seconds between ready checks

# Daemon
DAEMON_VERSION = "0.1.0"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB before rotation


@dataclass
class DevspaceConfig:
    """User-configurable settings, loaded from config.yaml."""
    default_template: str = "linux-vm"
    default_instance_type: str = "r8i.4xlarge"
    default_disk_size: int = 200
    default_stop_after: str = "8h"
    dotfiles_uri: str = ""
    git_repo: str = ""
    auto_connect: bool = True
    auto_reconnect: bool = True
    coder_path: str = "coder"
    extra_ssh_options: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[str] = None) -> DevspaceConfig:
        """Load config from YAML file, falling back to defaults.

        Uses a simple key: value parser to avoid PyYAML dependency.
        Supports only flat top-level keys (no nesting).
        """
        config_path = Path(path) if path else CONFIG_FILE
        cfg = cls()

        if not config_path.exists():
            return cfg

        try:
            with open(config_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if ":" not in line:
                        continue
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")

                    if hasattr(cfg, key):
                        current = getattr(cfg, key)
                        if isinstance(current, bool):
                            setattr(cfg, key, value.lower() in ("true", "yes", "1"))
                        elif isinstance(current, int):
                            setattr(cfg, key, int(value))
                        elif isinstance(current, str):
                            setattr(cfg, key, value)
        except (OSError, ValueError):
            pass  # Corrupt config → use defaults

        return cfg

    def save(self, path: Optional[str] = None) -> None:
        """Save config as simple YAML."""
        config_path = Path(path) if path else CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Devspace Manager Configuration",
            f"default_template: {self.default_template}",
            f"default_instance_type: {self.default_instance_type}",
            f"default_disk_size: {self.default_disk_size}",
            f"default_stop_after: {self.default_stop_after}",
            f"dotfiles_uri: {self.dotfiles_uri}",
            f"git_repo: {self.git_repo}",
            f"auto_connect: {str(self.auto_connect).lower()}",
            f"auto_reconnect: {str(self.auto_reconnect).lower()}",
        ]

        tmp = str(config_path) + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, str(config_path))


def ensure_dirs() -> None:
    """Create all required state directories."""
    for d in [STATE_DIR, SSH_DIR, SESSIONS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
