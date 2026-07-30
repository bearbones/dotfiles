#!/usr/bin/env bash
# run-handoff.sh — execute a pending Claude session handoff to a devspace
#
# Usage:
#   run-handoff.sh              # auto-selects if exactly one pending handoff
#   run-handoff.sh <slug>       # run the named pending handoff
#   run-handoff.sh --list       # list pending handoffs and exit
#
# The skill writes params + handoff.md into ~/claude-handoffs/pending/.
# This script reads those files, executes all SSH/SCP/tmux work, and
# archives the files on success.

set -euo pipefail

PENDING_DIR="$HOME/claude-handoffs/pending"
ARCHIVE_DIR="$HOME/claude-handoffs/archive"

# ── Argument parsing ──────────────────────────────────────────────────────────

if [[ "${1:-}" == "--list" ]]; then
    echo "Pending handoffs in $PENDING_DIR:"
    find "$PENDING_DIR" -maxdepth 1 -name "*.params" 2>/dev/null \
        | sort | while read -r f; do
            slug="$(basename "$f" .params)"
            ts="$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null \
                  || stat -c '%y' "$f" 2>/dev/null | cut -c1-16)"
            echo "  $slug  ($ts)"
        done
    exit 0
fi

# ── Select params file ────────────────────────────────────────────────────────

PARAMS_FILES=()
while IFS= read -r f; do
    PARAMS_FILES+=("$f")
done < <(find "$PENDING_DIR" -maxdepth 1 -name "*.params" 2>/dev/null | sort)

if [[ ${#PARAMS_FILES[@]} -eq 0 ]]; then
    echo "ERROR: No pending handoffs in $PENDING_DIR" >&2
    exit 1
fi

if [[ $# -ge 1 ]]; then
    PARAMS_FILE="$PENDING_DIR/$1.params"
    [[ -f "$PARAMS_FILE" ]] || {
        echo "ERROR: No params file for slug '$1' in $PENDING_DIR" >&2
        exit 1
    }
elif [[ ${#PARAMS_FILES[@]} -eq 1 ]]; then
    PARAMS_FILE="${PARAMS_FILES[0]}"
else
    echo "Multiple pending handoffs — specify one:" >&2
    for f in "${PARAMS_FILES[@]}"; do
        echo "  $(basename "$f" .params)" >&2
    done
    echo "" >&2
    echo "Usage: $0 <slug>" >&2
    exit 1
fi

# ── Load params ───────────────────────────────────────────────────────────────
# shellcheck source=/dev/null
source "$PARAMS_FILE"

# Validate required vars
: "${DEVSPACE_NAME:?DEVSPACE_NAME not set in $PARAMS_FILE}"
: "${BRANCH:?BRANCH not set in $PARAMS_FILE}"
: "${SESSION_SLUG:?SESSION_SLUG not set in $PARAMS_FILE}"
: "${HANDOFF_LOCAL:?HANDOFF_LOCAL not set in $PARAMS_FILE}"
: "${WORKTREE_RELPATH:?WORKTREE_RELPATH not set in $PARAMS_FILE}"
: "${TMUX_SESSION:?TMUX_SESSION not set in $PARAMS_FILE}"

[[ -f "$HANDOFF_LOCAL" ]] || {
    echo "ERROR: Handoff file not found: $HANDOFF_LOCAL" >&2
    exit 1
}

SSH_HOST="coder.${DEVSPACE_NAME}"
CONTROL_PATH="$HOME/.claude/devspace/ssh/${DEVSPACE_NAME}.sock"

# Helper: use ControlMaster socket if the devspace skill daemon has one open,
# otherwise fall back to plain SSH (which requires coder config-ssh).
_ssh() {
    if [[ -S "$CONTROL_PATH" ]]; then
        ssh -o ControlPath="$CONTROL_PATH" -o ControlMaster=no "$@"
    else
        ssh "$@"
    fi
}
_scp() {
    if [[ -S "$CONTROL_PATH" ]]; then
        scp -o ControlPath="$CONTROL_PATH" -o ControlMaster=no "$@"
    else
        scp "$@"
    fi
}
HANDOFF_BASENAME="$(basename "$HANDOFF_LOCAL")"

echo "=== Session Handoff: $SESSION_SLUG ==="
echo "Devspace:  $DEVSPACE_NAME"
echo "Branch:    $BRANCH"
echo "Worktree:  ~/$WORKTREE_RELPATH"
echo "tmux:      $TMUX_SESSION"
echo ""

# ── Verify coder CLI is authenticated and version-compatible ─────────────────
CODER_CHECK_OUTPUT="$(coder list 2>&1)"
CODER_CHECK_EXIT=$?
if echo "$CODER_CHECK_OUTPUT" | grep -q "version mismatch"; then
    echo "WARNING: coder CLI version mismatch (commands will likely still work)" >&2
fi
if [[ $CODER_CHECK_EXIT -ne 0 ]]; then
    echo ""
    echo "ERROR: coder CLI is not authenticated or pointed at the wrong server." >&2
    echo "" >&2
    echo "Fix: run one of the following, then re-run this script:" >&2
    echo "" >&2
    echo "  coder login https://dev.rbx.com        # primary — use this first" >&2
    echo "  coder login https://devspaces.rbx.com  # alternate" >&2
    echo "" >&2
    echo "If the browser flow doesn't open automatically, copy the URL it prints." >&2
    exit 1
fi

# ── Ensure devspace is running ────────────────────────────────────────────────
echo ">> Starting devspace (if stopped)..."
coder start "$DEVSPACE_NAME" --yes 2>/dev/null || true

# ── Refresh SSH config ────────────────────────────────────────────────────────
echo ">> Refreshing coder SSH config..."
coder config-ssh --yes 2>/dev/null || true

# ── Wait for SSH to be ready ──────────────────────────────────────────────────
echo ">> Waiting for SSH..."
for i in $(seq 1 12); do
    _ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_HOST" "echo ready" 2>/dev/null \
        && break || true
    [[ $i -eq 12 ]] && { echo "ERROR: SSH not ready after 60s" >&2; exit 1; }
    sleep 5
done

# ── Detect remote OS ─────────────────────────────────────────────────────────
REMOTE_OS=$(_ssh "$SSH_HOST" 'uname -s' 2>/dev/null || echo Windows)
echo "  Remote OS: $REMOTE_OS"

# ── Push handoff file ─────────────────────────────────────────────────────────
echo ">> Pushing handoff file..."
if [[ "$REMOTE_OS" == Windows* ]]; then
    # PowerShell: New-Item -Force silently succeeds if directory already exists
    _ssh "$SSH_HOST" "New-Item -ItemType Directory -Force -Path \"\$HOME\\claude-handoffs\" | Out-Null"
else
    _ssh "$SSH_HOST" "mkdir -p ~/claude-handoffs"
fi
_scp "$HANDOFF_LOCAL" "$SSH_HOST:~/claude-handoffs/$HANDOFF_BASENAME"

if [[ "$REMOTE_OS" == Windows* ]]; then
    # Windows devspace: tmux and awk don't exist — skip automation and print
    # manual instructions instead.
    HANDOFF_PROMPT="Please read ~/claude-handoffs/${HANDOFF_BASENAME} — it has full context about the session you are continuing. Acknowledge the current status and state the immediate next action."
    echo ""
    echo "  Windows devspace detected: skipping tmux/worktree automation."
    echo "  Handoff file pushed to: ~/claude-handoffs/${HANDOFF_BASENAME}"
    echo ""
    echo "  On the devspace, open a terminal and run:"
    echo ""
    echo "    cd ~/${WORKTREE_RELPATH}"
    echo "    claude --dangerously-skip-permissions"
    echo ""
    echo "  Then paste this prompt:"
    echo ""
    echo "    ${HANDOFF_PROMPT}"
    echo ""
else
    # ── Fetch branch on devspace ──────────────────────────────────────────────
    echo ">> Fetching branch '$BRANCH' on devspace..."
    _ssh "$SSH_HOST" "cd ~/game-engine && git fetch origin '$BRANCH' 2>/dev/null || true"

    # ── Create or reuse worktree ──────────────────────────────────────────────
    # If a worktree already exists for this branch at *any* path (e.g. left over
    # from a previous handoff), reuse it rather than failing. Otherwise fall back
    # to the requested path, creating it if needed.
    echo ">> Resolving worktree for branch '$BRANCH'..."
    EFFECTIVE_WORKTREE_REL=$(_ssh "$SSH_HOST" "
        cd ~/game-engine
        existing=\$(git worktree list --porcelain | awk -v branch='refs/heads/$BRANCH' '
            /^worktree / {wt=\$2}
            /^branch / && \$2==branch {print wt; exit}
        ')
        if [ -n \"\$existing\" ]; then
            echo \"  (re-using existing worktree at \$existing for branch '$BRANCH')\" >&2
            printf '%s' \"\${existing#\$HOME/}\"
        elif git worktree list --porcelain | awk '/^worktree / {print \$2}' | grep -qxF \"\$HOME/$WORKTREE_RELPATH\"; then
            echo '  (worktree already exists at requested path)' >&2
            printf '%s' '$WORKTREE_RELPATH'
        else
            echo '  (creating new worktree at ~/$WORKTREE_RELPATH)' >&2
            git worktree add ~/'$WORKTREE_RELPATH' '$BRANCH' >&2
            printf '%s' '$WORKTREE_RELPATH'
        fi
    ")
    WORKTREE_RELPATH="$EFFECTIVE_WORKTREE_REL"
    echo "  Effective worktree: ~/$WORKTREE_RELPATH"

    # ── Start tmux session ────────────────────────────────────────────────────
    echo ">> Starting tmux session '$TMUX_SESSION'..."
    _ssh "$SSH_HOST" "
        if tmux has-session -t '$TMUX_SESSION' 2>/dev/null; then
            echo '  (tmux session already exists, skipping)'
        else
            tmux new-session -d -s '$TMUX_SESSION' -c ~/'$WORKTREE_RELPATH'
        fi
    "

    # ── Launch Claude and inject handoff prompt ───────────────────────────────
    echo ">> Launching Claude..."
    _ssh "$SSH_HOST" "tmux send-keys -t '$TMUX_SESSION' 'claude --dangerously-skip-permissions' Enter"

    echo ">> Waiting for Claude to load (6s)..."
    sleep 6

    HANDOFF_PROMPT="Please read ~/claude-handoffs/${HANDOFF_BASENAME} — it has full context about the session you are continuing. Acknowledge the current status and state the immediate next action."
    _ssh "$SSH_HOST" "tmux send-keys -t '$TMUX_SESSION' $(printf '%q' "$HANDOFF_PROMPT") Enter"
fi

# ── Archive ───────────────────────────────────────────────────────────────────
echo ">> Archiving handoff files..."
ARCHIVE_SLOT="$ARCHIVE_DIR/$(date +%Y%m%d-%H%M%S)-$SESSION_SLUG"
mkdir -p "$ARCHIVE_SLOT"
mv "$PARAMS_FILE" "$ARCHIVE_SLOT/"
cp "$HANDOFF_LOCAL" "$ARCHIVE_SLOT/"

echo ""
echo "=== Handoff complete ==="
echo ""
echo "To attach:"
echo "  coder ssh $DEVSPACE_NAME -- tmux attach -t $TMUX_SESSION"
echo ""
echo "Or via SSH:"
echo "  ssh $SSH_HOST -t 'tmux attach -t $TMUX_SESSION'"
