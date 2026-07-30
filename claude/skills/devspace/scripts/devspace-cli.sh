#!/bin/bash
set -euo pipefail

# Devspace Manager CLI wrapper
# Delegates to devspace_cli.py with system python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="${SCRIPT_DIR}/devspace_cli.py"

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found in PATH" >&2
    exit 1
fi

exec python3 "${CLI}" "$@"
