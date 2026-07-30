#!/usr/bin/env bash
# Apply BOOST_→RBX_ replacements for one batch and stage changes.
# Intended to be called by subagents or manually.
#
# Usage: apply_batch.sh <batch_id> <file1> [<file2> ...]
#
# The caller is responsible for:
#   - already being on the correct branch
#   - committing and opening the PR after this script succeeds
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT="$HOME/.claude/scripts/boost_to_rbx.py"

if [[ $# -lt 2 ]]; then
    echo "Usage: apply_batch.sh <batch_id> <file1> [<file2> ...]" >&2
    exit 1
fi

BATCH_ID="$1"
shift
FILES=("$@")

echo "Batch: $BATCH_ID"
echo "Files: ${#FILES[@]}"

# Verify script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo "ERROR: $SCRIPT not found" >&2
    exit 1
fi

# Apply replacements
cd "$REPO_ROOT"
./Tools/Util/gobot uv run "$SCRIPT" "${FILES[@]}"

# Sanity: verify no BOOST_ macros remain in affected files
REMAINING=$(./Tools/Util/gobot uv run "$SCRIPT" --check "${FILES[@]}" 2>&1 | grep -c "WOULD CHANGE" || true)
if [[ "$REMAINING" -gt 0 ]]; then
    echo "ERROR: $REMAINING files still have BOOST_ macros after replacement" >&2
    exit 1
fi

echo "All replacements applied for batch $BATCH_ID"
