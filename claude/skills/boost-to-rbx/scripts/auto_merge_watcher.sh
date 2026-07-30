#!/usr/bin/env bash
# Monitor open boost-to-rbx refactor PRs:
#   - Enable auto-merge on any PR that is approved and CI-passing
#   - Merge master into PRs that are behind
#   - Report conflicts
#
# Intended to run as a cron job from a devspace.
# Requires: gh (GitHub CLI), git, jq (optional but used by gh)
#
# Usage: auto_merge_watcher.sh [--dry-run]
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REPO="GameEngine/game-engine"
SEARCH="refactor/boost-to-rbx in:title is:open"
LOG_PREFIX="[boost-auto-merge $(date '+%Y-%m-%d %H:%M')]"

echo "$LOG_PREFIX Starting PR scan"

# Fetch all open boost-to-rbx PRs with their status
PRS=$(gh pr list \
    --repo "$REPO" \
    --search "$SEARCH" \
    --json number,title,headRefName,mergeable,statusCheckRollup,reviewDecision,autoMergeRequest \
    --limit 300 2>/dev/null)

TOTAL=$(echo "$PRS" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
echo "$LOG_PREFIX Open PRs: $TOTAL"

if [[ "$TOTAL" == "0" ]]; then
    echo "$LOG_PREFIX Nothing to do."
    exit 0
fi

echo "$PRS" | python3 - <<PYEOF
import json, subprocess, sys, os

prs = json.load(sys.stdin)
dry_run = os.environ.get('DRY_RUN', 'false') == 'true'
repo = "GameEngine/game-engine"
log = lambda msg: print(f"[boost-auto-merge] {msg}", flush=True)

enabled_automerge = 0
behind_count = 0
conflict_count = 0
already_automerge = 0

for pr in prs:
    num = pr["number"]
    title = pr["title"]
    branch = pr["headRefName"]
    mergeable = pr.get("mergeable", "UNKNOWN")
    review = pr.get("reviewDecision", "")
    auto_merge = pr.get("autoMergeRequest")

    # Determine CI status
    checks = pr.get("statusCheckRollup") or []
    completed = [c for c in checks if c.get("conclusion")]
    if not completed:
        ci = "PENDING"
    elif all(c.get("conclusion") in ("SUCCESS", "SKIPPED", "NEUTRAL") for c in completed):
        ci = "PASS"
    elif any(c.get("conclusion") == "FAILURE" for c in completed):
        ci = "FAIL"
    else:
        ci = "PENDING"

    # Action logic
    if mergeable == "CONFLICTING":
        conflict_count += 1
        log(f"PR #{num}: CONFLICT — manual resolution needed: {branch}")
        continue

    if auto_merge:
        already_automerge += 1
        log(f"PR #{num}: auto-merge already enabled — skip")
        continue

    if review == "APPROVED" and ci in ("PASS", "PENDING"):
        log(f"PR #{num}: APPROVED + CI={ci} — enabling auto-merge")
        if not dry_run:
            result = subprocess.run(
                ["gh", "pr", "merge", str(num), "--auto", "--merge",
                 "--repo", repo],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                enabled_automerge += 1
                log(f"  ✓ Auto-merge enabled on #{num}")
            else:
                log(f"  ✗ Failed: {result.stderr.strip()}")
        else:
            log(f"  [DRY RUN] Would enable auto-merge on #{num}")
            enabled_automerge += 1
        continue

    if mergeable == "BEHIND":
        behind_count += 1
        log(f"PR #{num}: behind master — merging master")
        if not dry_run:
            # Merge master into the PR branch via GitHub API (no local checkout needed)
            result = subprocess.run(
                ["gh", "api",
                 f"repos/{repo}/merges",
                 "-f", f"base={branch}",
                 "-f", "head=master",
                 "-f", "commit_message=Merge master into {branch}",
                 "--method", "POST"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                log(f"  ✓ Master merged into {branch}")
            elif "already up-to-date" in result.stderr.lower() or result.returncode == 204:
                log(f"  ✓ Already up to date")
            else:
                log(f"  ✗ Merge failed: {result.stderr.strip()[:120]}")
        else:
            log(f"  [DRY RUN] Would merge master into #{num}")
        continue

    log(f"PR #{num}: review={review} ci={ci} mergeable={mergeable} — waiting")

print(f"\nSummary: auto-merge enabled={enabled_automerge}, already-set={already_automerge}, behind={behind_count}, conflicts={conflict_count}")
PYEOF
