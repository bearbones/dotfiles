#!/usr/bin/env bash
# List all open boost-to-rbx refactor PRs and their status.
# Usage: status.sh [--summary]
set -euo pipefail

SUMMARY_ONLY=false
for arg in "$@"; do
    [[ "$arg" == "--summary" ]] && SUMMARY_ONLY=true
done

# Query all open PRs whose branch starts with refactor/boost-to-rbx-
PRS=$(gh pr list \
    --search "refactor/boost-to-rbx in:title is:open" \
    --json number,title,headRefName,statusCheckRollup,mergeable,baseRefName \
    --limit 200 2>/dev/null || echo "[]")

TOTAL=$(echo "$PRS" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
echo "Open boost-to-rbx PRs: $TOTAL"

if [[ "$SUMMARY_ONLY" == "true" ]]; then
    MERGED=$(gh pr list \
        --search "refactor/boost-to-rbx in:title is:merged" \
        --json number --limit 200 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
    echo "Merged: $MERGED"
    CLOSED=$(gh pr list \
        --search "refactor/boost-to-rbx in:title is:closed" \
        --json number --limit 200 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
    echo "Closed (non-merged): $CLOSED"
    exit 0
fi

# Detailed per-PR status
echo "$PRS" | python3 - <<'PYEOF'
import json, sys

prs = json.load(sys.stdin)
if not prs:
    print("  (none)")
    sys.exit(0)

for pr in prs:
    num = pr["number"]
    title = pr["title"]
    branch = pr["headRefName"]
    mergeable = pr.get("mergeable", "UNKNOWN")

    # Determine CI status
    checks = pr.get("statusCheckRollup") or []
    if not checks:
        ci = "NO_CI"
    elif all(c.get("conclusion") == "SUCCESS" for c in checks if c.get("conclusion")):
        ci = "CI_PASS"
    elif any(c.get("conclusion") == "FAILURE" for c in checks):
        ci = "CI_FAIL"
    else:
        ci = "CI_PENDING"

    # Determine overall status
    if mergeable == "CONFLICTING":
        status = "CONFLICT"
    elif mergeable == "BEHIND":
        status = "BEHIND"
    elif ci == "CI_FAIL":
        status = "CI_FAIL"
    elif ci == "CI_PASS":
        status = "READY"
    else:
        status = "OPEN"

    print(f"  PR #{num:5d}  [{status:10s}]  {branch}")
PYEOF
