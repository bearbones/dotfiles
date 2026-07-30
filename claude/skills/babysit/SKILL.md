---
name: babysit
description: Sequentially merge all fully-approved documentation PRs in GameEngine/game-engine. Each merge causes CLAUDE.md conflicts in the remaining PRs, so the skill resolves conflicts one at a time and waits for each PR to merge before moving to the next. Designed to run repeatedly via /loop.
argument-hint: [--dry-run] [--status]
---

# babysit: Documentation PR Merge Queue

Documentation PRs all touch CLAUDE.md and therefore conflict with each other after each merge.
This skill resolves them strictly one at a time: pick the lowest-numbered approved PR, fix its
conflicts, enable auto-merge, and stop. On the next invocation the cycle repeats.

**Run as a loop** to babysit the full queue hands-free:

```
/loop 10m /babysit
```

`--status`: Show the PR table and exit — no changes made.
`--dry-run`: Show what would be done but do not push or enable auto-merge.

---

## Constants

```
GH_HOST="github.rbx.com"
REPO="GameEngine/game-engine"
GAME_ENGINE_ROOT="$HOME/git/roblox/game-engine"
SKILL_DIR="$HOME/.claude/skills/babysit"
```

---

## Step 1: Discover documentation PRs

```bash
GH_HOST=github.rbx.com python3 "$SKILL_DIR/scripts/doc_prs.py"
```

This returns a JSON array of all open PRs whose branch or title matches documentation keywords
(doc-gen, docs/, *_CLAUDE, documentation, knowledge-harvest, PREREAD, etc.).

Parse the JSON. Display a summary table grouped by review decision:

```
Documentation PR Queue — <date>
─────────────────────────────────────────────────────────────────────────
  State                Count
  APPROVED                 N
  REVIEW_REQUIRED          N
  CHANGES_REQUESTED        N
─────────────────────────────────────────────────────────────────────────

 Approved (ready to merge):
   #N  branch-name                        title (truncated to 60 chars)
   ...

 Awaiting review:
   #N  branch-name                        title
   ...

 Changes requested:
   #N  branch-name                        title
   ...
```

If `--status` was passed, stop here and report the table. Do not proceed.

---

## Step 2: Find the target PR

From the approved PRs, pick the **lowest-numbered** one. This is the one to process this cycle.

If no approved PRs exist:
- Report: "No approved documentation PRs. Nothing to do."
- If running in a /loop, this is a normal idle result — the loop should continue.
- Exit.

---

## Step 3: Check merge state

```bash
GH_HOST=github.rbx.com gh pr view {number} \
  --repo GameEngine/game-engine \
  --json mergeable,mergeStateStatus,headRefName,autoMergeRequest
```

Extract `mergeStateStatus`, `headRefName`, and `autoMergeRequest`.

**If `autoMergeRequest` is non-null** — auto-merge is already enabled on this PR.
- Check if the PR is still open (it may have merged already but GitHub's webhook lagged):
  ```bash
  GH_HOST=github.rbx.com gh pr view {number} --repo GameEngine/game-engine --json state
  ```
  - If `state == "MERGED"`: report merged, then continue to Step 2 to find the next PR.
  - If `state == "OPEN"`: auto-merge is pending — report "waiting for CI/merge on #{number}"
    and exit for this cycle. The /loop will check again next interval.

| mergeStateStatus | Meaning                              | Action                          |
|------------------|--------------------------------------|---------------------------------|
| `CLEAN`          | Up to date, no conflicts             | Go to Step 4 (enable auto-merge)|
| `BLOCKED`        | Protected branch, CI must pass first | Go to Step 4 (enable auto-merge)|
| `BEHIND`         | Behind base, no conflicts            | Go to Step 3a                   |
| `DIRTY`          | Merge conflicts exist                | Go to Step 3b                   |
| `UNSTABLE`       | CI running or failing                | Report and exit — wait for CI   |
| `UNKNOWN`        | GitHub hasn't computed state yet     | Retry once after 30s; if still  |
|                  |                                      | UNKNOWN, report and exit        |

---

### Step 3a: No-conflict update (BEHIND)

```bash
GH_HOST=github.rbx.com gh pr update-branch {number} --repo GameEngine/game-engine
```

If successful, continue to Step 4.
If it fails, report the error and exit — do not enable auto-merge.

---

### Step 3b: Conflict resolution (DIRTY)

These PRs primarily conflict on `CLAUDE.md` at the repo root (the main documentation index).
Less commonly they also conflict on module `*_CLAUDE.md` files they added.

Check out the branch locally and run the merge-master skill:

```bash
# Ensure we're in the game-engine repo
cd "$GAME_ENGINE_ROOT"
git fetch origin
```

Invoke the `merge-master` skill for branch `{headRefName}`:

```
/merge-master   (working on branch {headRefName})
```

The merge-master skill will:
1. Find or create a worktree for the branch
2. Merge origin/master
3. Resolve conflicts

**CLAUDE.md conflict guidance** — pass this hint to merge-master when invoking it:
> The main conflict will be in CLAUDE.md. The file is a documentation index table. This PR
> adds one or more rows to the table. The correct resolution is to keep ALL rows from both
> sides — master's new rows AND this PR's new rows — sorted by area name or appended at the end
> of the relevant section. Never drop rows. Never prefer one side entirely.

After merge-master completes:
- If successful (push confirmed): continue to Step 4.
- If merge-master reports unresolvable conflicts: report to user, skip this PR for this cycle,
  and try the next approved PR (go back to Step 2 with this PR excluded).

---

## Step 4: Enable auto-merge

If `--dry-run` was passed, report what would happen and exit without making changes.

Enable GitHub auto-merge with squash:

```bash
GH_HOST=github.rbx.com gh pr merge --auto --squash {number} \
  --repo GameEngine/game-engine
```

Report: `✓ Auto-merge enabled for PR #{number} — {title}`

The PR will now merge automatically once CI passes. Exit for this cycle.

On the next /loop invocation, Step 3 will detect `autoMergeRequest` is set, poll for merge
completion, and then move to the next approved PR.

---

## Final Report (each invocation)

```
babysit — <timestamp>

  Doc PRs total:    N  (APPROVED: N, REVIEW_REQUIRED: N, CHANGES_REQUESTED: N)

  This cycle:
    Target PR:  #{number} — {title}
    Action:     [none | update-branch | conflict-resolved | auto-merge-enabled | waiting-for-merge | already-merged]
    Status:     [✓ done | ⏳ waiting | ⚠ blocked — <reason>]

  Next:         #{number} — {title}  (will process after #{target} merges)
                (none — queue empty)
```

---

## Loop behavior

When invoked via `/loop 10m /babysit`, each iteration:

1. Discovers all approved doc PRs
2. If the lowest-numbered PR has auto-merge enabled and is still open → reports "waiting" → exits
3. If it merged → moves to the next PR in the queue → resolves conflicts → enables auto-merge
4. If no approved PRs → reports idle

The loop continues until all approved PRs have merged or the user stops it with Ctrl-C / `/loop stop`.
