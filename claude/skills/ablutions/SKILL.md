---
name: ablutions
description: Refresh the general PR queue — surface reviews to do, handle re-reviews, address comments on authored PRs, and merge master on approved PRs. Can run interactively on laptop or as a cron task on a devspace.
argument-hint: [--autonomous] [--review|--comments|--merge]
---

# Ablutions: PR Queue Refresh

Runs a full PR queue sweep across four buckets:

1. **Review requests** — first reviews and re-reviews for PRs where you're a requested reviewer
2. **Authored PRs with comments** — address reviewer feedback programmatically, or flag for local testing
3. **Approved PRs** — show them all, merge master on stale ones

If the `--autonomous` flag is present (e.g., running on a cron), reviews are submitted via `finalize-review`
rather than left PENDING. In interactive mode, all reviews are left PENDING for manual submission.

## Mode Selection

Three optional mode flags narrow the scope. Only one mode flag may be specified at a time.
If no mode flag is given, all phases run (full mode).

| Flag         | Phases run            | What it does                                                  |
|--------------|-----------------------|---------------------------------------------------------------|
| `--review`   | 1, 2 only             | Run the review-pr workflow for assigned first-reviews and re-reviews |
| `--comments` | 3 only (+ 3a CI)      | Triage and address reviewer comments on your authored PRs     |
| `--merge`    | 4 only (+ CI gate)    | Merge master / enable auto-merge on your approved PRs         |
| *(none)*     | 0, 1, 2, 3, 4, 5      | Full sweep — all phases                                       |

Parse mode before Phase 0. Set boolean flags `MODE_REVIEW`, `MODE_COMMENTS`, `MODE_MERGE`.
If none of the three flags is present, set all three to `true` and also set `MODE_FULL=true`.

## Constants

```
GAME_ENGINE_ROOT="$HOME/git/roblox/game-engine"
GH_HOST="github.rbx.com"
REPO="GameEngine/game-engine"
ME="amason"
```

`aladavac` is the review bot — its review comments count as amason's for the purpose of determining
whether a PR has been previously reviewed (used when reviewing on behalf of agent-config).

### Critical: Never re-request an approver

**NEVER call `requested_reviewers` POST for a reviewer whose last review state is `APPROVED`.**
Re-requesting negates their approval on GitHub and wastes their time. New commits — including
content commits — do NOT invalidate approvals. A PR showing `REVIEW_REQUIRED` status may simply
need approval from a *different* CODEOWNERS group, not a re-review from someone who already approved.

Only re-request when ALL of:
1. The reviewer's last state is `CHANGES_REQUESTED` or `COMMENTED` (never `APPROVED`)
2. Real content commits (parents == 1) exist since their review SHA
3. They are not already in `requested_reviewers`

---

## Pre-Phase: Sync game-engine to latest master

Before any other work, ensure the game-engine checkout is on the latest master:

```bash
cd "$HOME/git/roblox/game-engine"
git fetch origin
git checkout master
git pull --ff-only origin master
```

If `git pull --ff-only` fails (e.g., local commits on master), report the conflict to the user and
abort — do NOT force-reset. If the working tree is clean and up to date, proceed silently.

---

## Phase 0: Discovery

Run the discovery script and parse the JSON output:

```bash
python3 ~/.claude/skills/ablutions/scripts/pr_state.py
```

This queries GitHub for:
- PRs where `@me` is a requested reviewer → categorized as first_review / rereview / waiting_for_author
- PRs authored by `@me` → categorized as authored_needs_work / authored_approved

**Scope by mode** — only fetch what the active mode needs:

| Mode         | Fetches review-requested PRs? | Fetches authored PRs?                       |
|--------------|-------------------------------|---------------------------------------------|
| `--review`   | yes                           | no                                          |
| `--comments` | no                            | yes (authored_needs_work only)              |
| `--merge`    | no                            | yes (authored_approved only)                |
| full         | yes                           | yes (both authored_needs_work + approved)   |

Pass the appropriate `--mode` argument to the script so it only performs the needed API calls:

```bash
# review mode
python3 ~/.claude/skills/ablutions/scripts/pr_state.py --mode review

# comments mode
python3 ~/.claude/skills/ablutions/scripts/pr_state.py --mode comments

# merge mode
python3 ~/.claude/skills/ablutions/scripts/pr_state.py --mode merge

# full (no flag or --mode all)
python3 ~/.claude/skills/ablutions/scripts/pr_state.py
```

Display a summary table before taking any action, showing only the rows relevant to the active mode:

```
PR Queue — <date>  [mode: review|comments|merge|full]
┌─────────────────────────────┬───────┐
│ Category                    │ Count │
├─────────────────────────────┼───────┤
│ First reviews needed        │   N   │   ← shown in review / full mode
│ Re-reviews needed           │   N   │   ← shown in review / full mode
│ Waiting for author          │   N   │   ← shown in review / full mode
│ Your PRs with comments      │   N   │   ← shown in comments / full mode
│ Your approved PRs           │   N   │   ← shown in merge / full mode
│ Errors (skipped)            │   N   │
└─────────────────────────────┴───────┘
```

If there are errors (PR data could not be fetched), list them with the error message and skip them.

---

## Phase 1: First Reviews

> **Mode gate**: skip this phase unless `MODE_REVIEW` is true.

For each PR in `first_review`, run the full review-pr workflow **directly** using `pr_review.sh`.
The review-pr skill has `disable-model-invocation: true` and cannot be invoked via `Skill(...)` —
you **must** execute the workflow steps below.

**Script path:** `$GAME_ENGINE_ROOT/.claude/skills/review-pr/scripts/pr_review.sh`

### Review workflow (one PR at a time — shared state under `.claude/tmp/pr_review/`)

**Step 1: Get PR info and prepare worktree**
```bash
SHA=$(pr_review.sh get-commit {number})
REVIEW_ROOT=$(pr_review.sh prepare-worktree "$SHA")
pr_review.sh get-files {number}            # writes files.txt to state dir
pr_review.sh get-diff {number}             # full diff for context
```

Check the PR body for a self-review marker `<!-- self-review:v1 sha:<SHA> -->`. If found,
follow Self-Review Aware Mode (see review-pr SKILL.md). If not found, continue.

**Step 2: Collect review rules (FATAL on failure)**
```bash
cat "$STATE_DIR/files.txt" | pr_review.sh collect-rules "$REVIEW_ROOT"
```
If `collect-rules` exits non-zero → **STOP this PR's review**, report the error, release the
worktree (`pr_review.sh release-worktree`), and move on to the next PR.

**Step 3: Spawn subagents (parallel)**
For each section in the `collect-rules` JSON output, spawn a subagent using the Subagent Prompt
Template from the review-pr SKILL.md. Pass `review_root`, the section's `rules_content`,
`confluence_content`, and each file's diff (`pr_review.sh get-diff {number} "file"`).

**Step 4: Collate and post**
```bash
pr_review.sh create {number} "$SHA"
# For each inline finding (line > 0):
pr_review.sh get-line {number} "path/to/file" "pattern"
pr_review.sh add-comment {number} "path/to/file" {line} "bug: ..."
```
File-level findings go in the review body.

**Step 5a: Interactive mode (default)**
```bash
printf '%s' "$review_body" | pr_review.sh submit-pending {number} -
```
Report pending review ID and comment count to the user before moving to the next PR.

**Step 5b: Autonomous mode (--autonomous flag)**
```bash
printf '%s' "$SUMMARY" | pr_review.sh finalize-review {number} "$SHA" amason -
```

After all first reviews: print a summary listing which PRs now have pending reviews.

---

## Phase 2: Re-Reviews

> **Mode gate**: skip this phase unless `MODE_REVIEW` is true.

For each PR in `rereview`, run the same workflow as Phase 1 with one addition: before Step 3,
fetch existing review comments and include them in each subagent prompt:

```bash
pr_review.sh get-review-comments {number}   # fetch previous comments
```

Add this section to each subagent prompt (after "Files Under Review"):
```
## Previous Review Comments

This PR was previously reviewed at commit {previous_sha}. New commits have been pushed since.
For each comment below:
- If the issue was addressed in the new changes, do NOT re-flag it
- If the issue was NOT addressed, include it in your findings
- Focus extra attention on code that changed since {previous_sha}

{previous_comments}
```

When posting (Step 4), use `reply-to-comment` for findings that match an existing thread:
```bash
pr_review.sh reply-to-comment {number} {comment_id} "..."
```

Process re-reviews **one at a time** (same shared-state reason as Phase 1).

### Autonomous mode (--autonomous flag)

Same as Phase 1: use `finalize-review` instead of `submit-pending` in Step 5.

---

## Phase 3: Authored PRs with Reviewer Comments

> **Mode gate**: skip this phase unless `MODE_COMMENTS` is true.

### Phase 3a: CI Failure Triage

> **Mode gate**: run 3a when `MODE_COMMENTS` **or** `MODE_MERGE` is true. In `--merge` mode only,
> limit 3a to PRs in `authored_approved` (skip `authored_needs_work`).

Before analyzing reviewer comments, check CI status for every PR in `authored_needs_work` **and** `authored_approved`.

For each such PR, fetch the check status:

```bash
GH_HOST=github.rbx.com gh pr checks {number} --repo GameEngine/game-engine \
  --json name,status,conclusion,detailsUrl
```

**Freshness failures** (skip — already handled by merge-master in Phase 4):
Any check whose name matches: `freshness`, `needs-rebase`, `update-branch`, `stale`, `up-to-date`, or `branch-up-to-date`.

**`PR Tag + Jira Check` failures**: Two sub-cases:

1. **"has no Testing Instructions"**: Set the ticket's Testing Instructions to `"No manual testing required"`.
   Testing Instructions are for QA testers, not developers — amason's PRs never require manual testing.
   ```bash
   jira_cli.py update {TICKET} --testing "No manual testing required"
   ```

2. **"is set to Closed"**: The Jira ticket is already resolved. **NEVER reopen or retransition a closed ticket.**
   Instead, **close the PR** with a comment explaining the issue was already resolved:
```bash
GH_HOST=github.rbx.com gh pr close {number} --repo GameEngine/game-engine \
  --comment "Closing: {TICKET} is already Closed, indicating the underlying issue was resolved. This PR is superseded."
```

**Non-freshness failures**: For each failing check that is NOT freshness-related:

1. Fetch the failure log (up to ~100 lines):
   ```bash
   GH_HOST=github.rbx.com gh run view {run_id} --log-failed --repo GameEngine/game-engine 2>/dev/null | head -100
   ```
   (The `run_id` can be extracted from `detailsUrl` — it's the numeric segment after `/runs/`.)

2. **Staleness log check** — before spawning a triage subagent, scan the log for staleness
   indicators. If the log contains any of the following (case-insensitive):
   `PR is stale`, `merge master`, `branch is out of date`, `behind.*master`, `please.*merge`,
   `stale.*branch`, `needs.*rebase`, `not up.to.date`
   — treat this as a freshness failure (regardless of check name) and run:
   ```bash
   GH_HOST=github.rbx.com gh pr update-branch {number} --repo GameEngine/game-engine
   ```
   If the command succeeds, record as `✓ master merged (clean)` and **skip the triage subagent**.
   If it fails, record as `⚠ update-branch failed` and continue to the triage subagent.

3. Spawn a **parallel subagent** for each failing check, providing:
   - The PR diff (`gh pr diff {number}`)
   - The failed log output
   - The PR title and description

   Subagent instruction:
   ```
   You are triaging a CI failure on a PR authored by amason in GameEngine/game-engine.
   
   PR diff: {diff}
   Failed check: {check_name}
   Failure log (truncated): {log}
   
   Classify this failure as one of:
   - **fluke**: The failure is unrelated to the PR changes (known flaky test, infrastructure blip,
     unrelated test file, random ordering issue). Evidence: the failure involves tests/files not
     touched by this PR, or the failure message is clearly non-deterministic.
   - **pr_caused**: The failure is plausibly caused by changes in this PR. Evidence: the failing
     tests or files overlap with what this PR modifies, or the failure message references symbols
     changed by this PR.
   - **unknown**: Not enough information to classify.
   
   Output JSON only:
   {"check": "{check_name}", "verdict": "fluke|pr_caused|unknown", "reason": "one sentence"}
   ```

3. After all triage subagents return:
   - **fluke** verdicts: note them in the Phase 3 summary but take no action
   - **pr_caused** verdicts: add them to the "on deck" list alongside `needs_local_testing` comments
   - **unknown**: flag to user with a one-liner summary

For PRs in `authored_approved` with `pr_caused` failures: **do not enable auto-merge** (or warn if auto-merge was already enabled) — flag these for user attention.

---

For each PR in `authored_needs_work`, spawn a **parallel** subagent to analyze the reviewer comments.

### Subagent prompt (replace `{number}` and `{title}`)

```
You are analyzing reviewer comments on a GitHub PR to determine what work is needed.

PR: #{number} — {title}
Repo: GameEngine/game-engine (GH_HOST: github.rbx.com)

## Step 1: Fetch the diff and review comments

```bash
GH_HOST=github.rbx.com gh pr diff {number} --repo GameEngine/game-engine
GH_HOST=github.rbx.com gh api repos/GameEngine/game-engine/pulls/{number}/comments
GH_HOST=github.rbx.com gh api repos/GameEngine/game-engine/pulls/{number}/reviews \
  --jq '.[] | select(.state != "APPROVED" and .state != "PENDING") | {user: .user.login, state, body: .body[0:200], submitted_at}'
```

## Step 2: Classify each reviewer comment

For each non-empty inline comment (skip empty body, skip comments from amason/gedevops-build/github-actions[bot]), classify as:

- **addressable**: A code fix, documentation correction, or rename that can be made by reading the diff alone.
  No building, no running tests, no platform-specific behavior required.
- **needs_local_testing**: Involves building the engine, platform-specific behavior (Windows/Android/PS5/iOS),
  performance or memory characteristics, or the comment says "does this still work on X".
- **already_addressed**: Subsequent commits clearly made the change the comment asked for (verify
  via the current diff — **an explicit author reply is not required**), the comment is informational
  (no action requested), the comment's `position` field in the API response is `null` (GitHub marks
  this as "outdated" — the diff line it was on no longer exists in the current PR diff), or the
  author has replied to the thread explaining why no change is needed.

## Step 3: Output JSON only

{
  "pr": {number},
  "addressable": [
    {"comment_id": N, "file": "path/to/file", "line": N_or_null, "description": "one-line summary of the fix needed"}
  ],
  "needs_local_testing": [
    {"comment_id": N, "summary": "brief description of why local testing is needed"}
  ],
  "already_addressed": [
    {"comment_id": N}
  ]
}

Output ONLY the JSON. No explanation.
```

### After all subagents return

**Addressable comments** — group by PR. If any PR has addressable comments, spawn a **coding subagent**
per PR to make the fixes. Use `isolation: "worktree"` so each PR's changes are isolated:

Coding subagent prompt:
```
You are fixing code in response to reviewer comments on PR #{number} in GameEngine/game-engine.

Working directory: $HOME/git/roblox/game-engine (you are in a fresh worktree on branch {branch})

Addressable comments to resolve:
{list each: file, line, description}

Steps:
1. Read each referenced file
2. Make the minimal code change that resolves each comment
3. Commit with message: "Address review comments on #{number}\n\nCo-authored-by: Claude <noreply@anthropic.com>"
4. Push: git push origin {branch}
5. Report: list each change made as a brief bullet

Do NOT change anything not related to the listed comments. Do NOT merge master.
```

**Needs local testing** — add to the "on deck" list. Report to user:
```
On deck (need local testing):
  PR #N — {title}
    • {summary of each comment needing local testing}
```

**Already addressed** — note in the summary but take no action.

**Re-review requests** — after processing all comments for a PR, if the PR is **not yet approved**
and all comments resolved to `already_addressed` (none remain `addressable` or `needs_local_testing`),
re-request review from every reviewer whose last review state is `COMMENTED` or `CHANGES_REQUESTED`.

```bash
# Fetch last review state per reviewer
GH_HOST=github.rbx.com gh api repos/GameEngine/game-engine/pulls/{number}/reviews \
  --jq '[.[] | {user: .user.login, state}] | group_by(.user) | map(last)'

# Re-request only non-approved reviewers (NEVER re-request state == "APPROVED")
GH_HOST=github.rbx.com gh api -X POST \
  repos/GameEngine/game-engine/pulls/{number}/requested_reviewers \
  -f 'reviewers[]={login}' ...
```

**Critical**: Never include a reviewer whose last state is `APPROVED` in the re-request list.
Re-requesting an approver negates their approval on GitHub.

---

## Phase 4: Approved PRs

> **Mode gate**: skip this phase unless `MODE_MERGE` is true.

List all PRs in `authored_approved` in a table:

```
Your approved PRs:
  #N  title                              last commit: YYYY-MM-DD HH:MM  (X hours ago)
  ...
```

### Staleness Check and Master Merge

For each PR in `authored_approved`, fetch its merge state:

```bash
GH_HOST=github.rbx.com gh pr view {number} --repo GameEngine/game-engine \
  --json mergeable,mergeStateStatus,headRefName
```

Classify by `mergeStateStatus`:

| Status       | Meaning                                     | Action                         |
|--------------|---------------------------------------------|--------------------------------|
| `CLEAN`      | Already up to date with base                | Skip — no merge needed         |
| `BEHIND`     | Behind base, no conflicts                   | `gh pr update-branch`          |
| `DIRTY`      | Has merge conflicts                         | Invoke `merge-master` skill    |
| `BLOCKED`    | Passing but blocked by branch protection    | Skip — treat as CLEAN          |
| `UNSTABLE`   | CI running/failing                          | Skip — handled by CI gate      |
| `UNKNOWN`    | GitHub hasn't computed state yet            | Skip with a warning            |

**BEHIND — clean update:**

```bash
GH_HOST=github.rbx.com gh pr update-branch {number} --repo GameEngine/game-engine
```

If the command succeeds, record as `✓ master merged (clean)` in the final report.
If it fails (e.g., race with a concurrent push), record as `⚠ update-branch failed` and skip auto-merge.

**DIRTY — conflict resolution:**

Invoke the `merge-master` skill for the PR's branch:

```
/merge-master   (on branch {headRefName})
```

The `merge-master` skill will check out the branch, merge master, resolve conflicts, and push.
If it reports success, record as `✓ master merged (conflicts resolved)` in the final report.
If it reports unresolvable conflicts, record as `⚠ conflicts flagged` and **skip auto-merge** — add to the "On deck" list for the user.

---

### CI gate before auto-merge

Before enabling auto-merge on any PR, check the Phase 3a CI triage results for that PR.

- **pr_caused** verdict: **do NOT enable auto-merge** — report to user instead:
  ```
  ⚠ PR #{number} — skipped auto-merge (CI failure likely caused by PR changes)
    Check: {check_name}
    Reason: {triage reason}
  ```
- **fluke** or no failures: proceed to the comment gate below.
- **unknown**: proceed to the comment gate but add a warning line next to the PR in the summary.

### Unaddressed Comment Gate

Reviewers sometimes approve with outstanding nit/fix comments, expecting the author to handle them
without requiring a re-review cycle. Check for these before enabling auto-merge.

For each PR in `authored_approved`, fetch unanswered inline comments:

```bash
GH_HOST=github.rbx.com gh api repos/GameEngine/game-engine/pulls/{number}/comments \
  --jq '[.[] | select(.user.login | IN("amason","gedevops-build","github-actions[bot]") | not)]'
```

An **unanswered top-level comment** is one with no `in_reply_to_id` where amason has not replied to
that thread. If none exist, skip to Auto-merge.

Note: `aladavac` is intentionally **included** in this query — its comments on approved PRs must be
handled (see classification rules below). Only `amason`, `gedevops-build`, and `github-actions[bot]`
are excluded.

If unanswered comments exist, spawn a **parallel classification subagent** per PR using the same
Phase 3 subagent prompt. The subagent should note this PR is already approved — classify each comment as:

- **addressable**: fix can be made from the diff alone (no build/test required)
- **needs_local_testing**: requires building, platform-specific behavior, or runtime verification
- **already_addressed**: covered by a later commit, informational only, or `position: null` (outdated diff line)

After subagents return, act on the results:

**`bug:`-prefixed or correctness-blocking comments** (regardless of source):
- Spawn a coding subagent to apply the fix (worktree isolated), commit, push
- **Do NOT enable auto-merge** until the fix is pushed and aladavac re-requested
- Report: `⚠ PR #{number} — fix pushed for bug-level comment, re-review requested`

**`nit:` / `design:` / style-level addressable comments**:
- Spawn a coding subagent to apply the fix, commit, push
- Enable auto-merge after pushing (reviewer approved knowing these were minor)
- Report: `✓ PR #{number} — nit fixes pushed, auto-merge enabled`

**`needs_local_testing`**:
- Warn in summary but do NOT block auto-merge (reviewer approved with this outstanding)
- Report: `⚠ PR #{number} — unverified local-testing comment (auto-merge enabled anyway)`

**`already_addressed`**: proceed to auto-merge normally.

For aladavac comments specifically: aladavac comments on approved PRs are always nit/design level
(never block the approval). Treat them as nit-level addressable unless prefixed `bug:`.

### Auto-merge

Ask the user which of the listed PRs to enable GitHub auto-merge on. For each PR the user selects
(and that passed the CI gate above):

```bash
GH_HOST=github.rbx.com gh pr merge --auto --squash {number} --repo GameEngine/game-engine
```

Report: `✓ auto-merge enabled for PR #{number} — {title}`

---

## Phase 5: Stale Worktree Cleanup

> **Mode gate**: skip this phase unless `MODE_FULL` is true (i.e., no mode flag was given).

Scan all git repos under `~/git` for non-main worktrees that can be cleaned up. This runs last
so it doesn't interfere with any worktrees created in Phase 4.

### Step 1: Audit

```bash
python3 ~/.claude/skills/ablutions/scripts/worktree_audit.py
```

This scans every main repo (where `.git` is a directory) under `~/git`, runs
`git worktree list --porcelain` for each, and categorizes non-main worktrees:

| Category      | Meaning                                                              | Default action  |
|---------------|----------------------------------------------------------------------|-----------------|
| `prunable`    | git already knows the directory is gone                              | auto-prune      |
| `dangling`    | directory doesn't exist (git missed it)                              | auto-remove     |
| `merged_pr`   | PR is MERGED, working tree clean                                     | auto-remove     |
| `fully_merged`| branch has zero unique commits vs. default branch                   | auto-remove     |
| `closed_pr`   | PR is CLOSED/abandoned, working tree clean                           | suggest to user |
| `detached`    | detached HEAD (no branch), typically temp review worktrees            | suggest if >24h |
| `stale_no_pr` | no open PR, last commit >{STALE_DAYS} days ago, clean               | suggest to user |
| `dirty`       | uncommitted changes                                                  | flag only       |
| `active`      | open PR or recent commits                                            | keep            |
| `no_pr_recent`| no PR but recent activity                                            | keep            |

### Step 2: Display summary

Show a table of what was found before taking action:

```
Worktree audit across ~/git:
  prunable / dangling / merged_pr / fully_merged:  N  (will auto-clean)
  closed_pr / detached / stale_no_pr:              N  (awaiting confirmation)
  dirty:                                           N  (flagged — not touched)
  active / no_pr_recent:                           N  (kept)
```

List the auto-clean and suggest-remove items with their repo, path, branch, and category.

### Step 3: Auto-clean (no confirmation needed)

For each `prunable` worktree:
```bash
git -C {repo_root} worktree prune
```
(One `prune` per repo covers all prunable worktrees in that repo.)

For each `dangling` worktree (directory truly gone):
```bash
git -C {repo_root} worktree remove --force {path}
```

For each `merged_pr` or `fully_merged` worktree (PR merged, clean working tree):
```bash
git -C {repo_root} worktree remove {path}
# Then optionally delete the local branch if it still exists:
git -C {repo_root} branch -d {branch} 2>/dev/null || true
```

Report each removal: `✓ removed {path} ({branch})`

### Step 4: Confirm-to-remove

After auto-cleaning, list any `closed_pr`, `detached` (>24h old), and `stale_no_pr`
worktrees and ask:

```
The following worktrees look stale. Remove them?

  [closed_pr]    game-engine/.claude/worktrees/fix-6179  (PR #155452 closed)
  [stale_no_pr]  game-engine/.claude/worktrees/old-thing  (last commit 21 days ago, no PR)
  [detached]     /private/tmp/worktree-pr-12345  (detached HEAD, 3.5 days old)

Enter numbers to remove (e.g. "1 3"), "all", or "none":
```

Remove only those the user selects. For each removal, run `git worktree remove {path}` and
optionally delete the branch.

### Step 5: Dirty worktrees

For each `dirty` worktree, report and **do not touch**:

```
⚠ dirty worktree — NOT removed:
  {path}  ({branch})
  Uncommitted files: {list up to 5 files}
```

---

## Final Report

After all phases, show a consolidated summary. Omit sections for phases that were skipped.

```
Ablutions complete — <timestamp>  [mode: review|comments|merge|full]

Reviews (Phase 1–2)                     ← only if MODE_REVIEW
  Pending reviews created:  N  (submit manually in GitHub)
  [list: PR #N — title]

Author PRs (Phase 3)                    ← only if MODE_COMMENTS
  Fixes pushed:  N
  [list: PR #N — what was fixed]
  On deck (need local testing):  N
  [list: PR #N — what's needed]

Approved PRs (Phase 4)                  ← only if MODE_MERGE
  Master merged (clean):      N  [list: PR #N — ✓]
  Master merged (conflicts):  N  [list: PR #N — ✓ resolved]
  Conflicts flagged:          N  [list: PR #N — ⚠ needs manual resolution]
  Auto-merge enabled:         N  [list: PR #N]
  Skipped (CI failure / no-merge):  N  [list: PR #N — reason]

Worktrees (Phase 5)                     ← only if MODE_FULL
  Auto-removed:   N  (prunable/dangling/merged)
  User-confirmed: N
  Flagged dirty:  N  (not touched)
  Kept active:    N

Skipped (errors):  N
```
