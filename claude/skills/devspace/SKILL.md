---
name: devspace
description: Manage remote Coder devspaces — SSH connections, remote execution, persistent sessions. Use when the user wants to create, connect to, or run commands on devspaces.
tools: Bash, Read, Glob, Grep
---

# Devspace Manager

Manages remote Coder devspaces with persistent SSH connections, automatic reconnection, and remote command execution.

## Architecture

Three layers:
1. **CLI** (`devspace-cli.sh`) — bash wrapper invoking `devspace_cli.py`
2. **Daemon** (`devspace_daemon.py`) — asyncio background server managing SSH ControlMaster connections
3. **Skill** (this file) — Claude Code integration patterns

The daemon runs as a background process, accepting JSON commands over a Unix socket at `~/.claude/devspace/daemon.sock`.

## CLI Reference

```bash
CLI="~/.claude/skills/devspace/scripts/devspace-cli.sh"

# Daemon lifecycle
$CLI daemon start              # Start background daemon
$CLI daemon stop               # Graceful shutdown
$CLI daemon status             # PID, uptime, connections

# Workspace management (via Coder)
$CLI list                      # List all devspaces
$CLI create <name>             # Create new devspace
$CLI start <name>              # Start stopped devspace
$CLI stop <name>               # Stop devspace

# SSH connections
$CLI connect <name>            # Establish SSH ControlMaster
$CLI disconnect <name>         # Tear down connection
$CLI exec <name> "<command>"   # Run command via SSH
$CLI status [name]             # Show connection states

# Add --json for raw JSON output (machine-readable)
$CLI list --json
$CLI exec <name> "echo hello" --json
```

## Quick Start

```bash
# 1. Start the daemon
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh daemon start

# 2. Connect to a devspace
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh connect my-devspace

# 3. Run a command
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh exec my-devspace "cd ~/repo && buck2 build //path:target"
```

## State Files

All state lives under `~/.claude/devspace/`:
- `daemon.pid` — PID + start timestamp
- `daemon.sock` — Unix domain socket
- `daemon.log` — Daemon log (rotated at 10MB)
- `config.yaml` — User preferences
- `inventory.json` — Persisted devspace + connection state
- `ssh/` — SSH ControlMaster sockets

## Workflow Patterns

### Ensure daemon is running

Before any devspace operation, verify the daemon:
```bash
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh daemon status || \
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh daemon start
```

### Remote build with output capture

```bash
# Start a build and capture output
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh exec my-devspace \
  "cd ~/game-engine && buck2 build //Client/App:RobloxStudioApp 2>&1"
```

### Check workspace status before connecting

```bash
# List to see current states, then connect
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh list
bash ~/.claude/skills/devspace/scripts/devspace-cli.sh connect my-devspace
```

## Platform Support

The daemon auto-detects the remote platform on first SSH connection:

| Platform | Detection | Session Backend (Phase 2) |
|----------|-----------|--------------------------|
| Linux | `uname -s` → "Linux" | tmux |
| macOS | `uname -s` → "Darwin" | tmux |
| Windows | `uname -s` fails | PowerShell detached process |

Platform is cached in `inventory.json` and used to select the appropriate session backend in Phase 2.

## Configuration

Edit `~/.claude/devspace/config.yaml`:
```yaml
default_template: linux-vm
default_instance_type: r8i.4xlarge
default_disk_size: 200
default_stop_after: 8h
auto_connect: true
auto_reconnect: true
```

## Troubleshooting

- **Daemon won't start**: Check `~/.claude/devspace/daemon.log`
- **Connection failed**: Verify `coder list` works, then `coder config-ssh -y`
- **Stale PID file**: Daemon startup auto-cleans stale PIDs
- **Socket permission denied**: Socket is created with 0600 permissions in user-owned directory
