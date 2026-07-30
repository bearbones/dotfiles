---
name: env-check
description: Ensure primary checkouts of key repos are on latest master/main, rescue dirty/stashed state to labeled sweepup worktrees, and verify game-engine's anti-blowup pre-push hook integrity.
argument-hint: [--status-only] [--hooks-only] [--repos-only]
---

# env-check: Environment Health Check

Runs three phases, each independently selectable via flags:
- `--status-only`: Phase 1 only (display, no changes)
- `--repos-only`: Phase 2 only (sync repos + rescue dirty state)
- `--hooks-only`: Phase 3 only (hook integrity check + repair)
- *(no flag)*: All three phases

## Constants

```
KEY_REPOS=(
    game-engine     ~/git/roblox/game-engine     master
    vycor-cpp       ~/git/roblox/vycor-cpp        main
    util            ~/git/roblox/util             main
    thought-bubble  ~/git/roblox/thought-bubble   main
)
GLOBAL_HOOK="$HOME/.git-hooks/pre-push"
GAME_ENGINE="$HOME/git/roblox/game-engine"
EXPECTED_HOOKSPATH="$HOME/.git-hooks"
```

---

## Phase 1: Status Snapshot

> **Mode gate**: always run unless `--repos-only` or `--hooks-only` was passed.

Run the status script:

```bash
bash ~/.claude/skills/env-check/scripts/status.sh
```

Parse the pipe-delimited output (REPO|PATH|BRANCH|DEFAULT|DIRTY_TRACKED|UNTRACKED|STASH_COUNT|HOOKSPATH)
and display a status table:

```
env-check status — <date>

Repo            Branch   Default   Tracked  Untracked  Stashes  hookspath
──────────────  ───────  ────────  ───────  ─────────  ───────  ─────────────────────
game-engine     master   master       0         1          31   (none=global default)
vycor-cpp       main     main         2         1           1   (none=global default)
util            main     main         4        14           0   /path/.git/hooks ⚠
thought-bubble  main     main         4         0           0   (none=global default)
```

Formatting notes:
- A repo with BRANCH == DEFAULT and DIRTY_TRACKED == 0 and UNTRACKED == 0: prefix with `✓`
- A repo with DIRTY_TRACKED > 0: prefix with `⚠` (needs rescue)
- A repo with BRANCH != DEFAULT: prefix with `↪` (on feature branch)
- A repo with STASH_COUNT > 10: add `(!)` after stash count to draw attention
- hookspath `(none)` means the global `~/.git-hooks` is in effect — safe. Display as `(global)`
- hookspath set to anything else: add `⚠` and note it deviates from global default

If STASH_COUNT > 0, list the stashes beneath the table row (up to 5, truncate rest):

```
  Stashes:
    [0] WIP on master: <message>
    [1] WIP on feature/foo: <message>
    ...
    (and 26 more — run: git -C <path> stash list)
```

After the table, print a one-line summary:
```
Summary: N repos clean, N need rescue, N on feature branches
```

---

## Phase 2: Repo Sync and Dirty State Rescue

> **Mode gate**: skip if `--status-only` or `--hooks-only`.

Process each repo in order. For each:

### 2a. Determine action needed

| Condition | Action |
|---|---|
| On default branch, clean, up-to-date | `git pull --ff-only` (fast-forward sync) |
| On default branch, has tracked dirty state | Rescue → commit to sweepup worktree → pull |
| On default branch, untracked-only | Pull; report untracked (don't move — may be intentional) |
| On feature branch, clean | Report branch; offer to checkout default and pull |
| On feature branch, dirty | Rescue dirty state to sweepup worktree; then offer to checkout default |
| Existing stashes | List them; if >5 stashes or any are >30 days old, offer to rescue each to a sweepup worktree |

### 2b. Sweepup rescue procedure

A **sweepup worktree** is a git worktree on a timestamped branch that commits the
rescued state so it's safe, labeled, and recoverable via `git branch --list 'sweepup/*'`.

**Path conventions**:
- game-engine: `$GAME_ENGINE/.claude/worktrees/sweepup-YYYYMMDD-HHMMSS`
- all others: `{repo_root}/.worktrees/sweepup-YYYYMMDD-HHMMSS`

**To rescue uncommitted tracked changes** from a repo at path `$REPO` currently on `$BRANCH`:

```bash
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SWEEPUP_BRANCH="sweepup/${TIMESTAMP}-${BRANCH//\//-}"
SWEEPUP_DIR="${REPO_ROOT}/.worktrees/sweepup-${TIMESTAMP}"  # or .claude/worktrees for game-engine

# 1. Stash ALL uncommitted tracked changes (including deletions), excluding untracked
git -C "$REPO_ROOT" stash push --include-untracked -m "sweepup: rescued from $BRANCH on $TIMESTAMP"

# 2. Create the sweepup branch at the current HEAD (same commit as the source branch)
git -C "$REPO_ROOT" worktree add "$SWEEPUP_DIR" -b "$SWEEPUP_BRANCH"

# 3. Pop the stash into the sweepup worktree (stash is shared across all worktrees)
git -C "$SWEEPUP_DIR" stash pop

# 4. Commit the rescued state in the sweepup worktree
git -C "$SWEEPUP_DIR" add -A
git -C "$SWEEPUP_DIR" commit -m "sweepup: rescued dirty state from $BRANCH on $TIMESTAMP"
```

After the rescue, report:
```
  ✓ rescued dirty state → sweepup/${TIMESTAMP}-<branch> at ${SWEEPUP_DIR}
    To return to this work: git -C <repo_root> worktree list
    Branch: sweepup/${TIMESTAMP}-<branch>
```

**To rescue existing stashes** (when user confirms):

For each stash `stash@{N}` in the stash list:

```bash
STASH_MSG=$(git -C "$REPO_ROOT" stash list | sed -n "$((N+1))p" | sed 's/.*: //')
SWEEPUP_BRANCH="sweepup/${TIMESTAMP}-stash${N}"
SWEEPUP_DIR="${REPO_ROOT}/.worktrees/sweepup-${TIMESTAMP}-stash${N}"

# Get the base commit for this stash
BASE_COMMIT=$(git -C "$REPO_ROOT" rev-parse "stash@{$N}^1")

git -C "$REPO_ROOT" worktree add "$SWEEPUP_DIR" -b "$SWEEPUP_BRANCH" "$BASE_COMMIT"
git -C "$SWEEPUP_DIR" stash apply "stash@{$N}"
git -C "$SWEEPUP_DIR" add -A
git -C "$SWEEPUP_DIR" commit -m "sweepup: stash[$N] — $STASH_MSG"

# Drop the original stash after confirmed rescue
git -C "$REPO_ROOT" stash drop "stash@{$N}"
```

Process stashes in REVERSE index order (highest N first) so dropping doesn't renumber remaining stashes.

### 2c. Sync to latest default branch

After rescuing any dirty state, sync the primary checkout:

```bash
git -C "$REPO_ROOT" fetch origin
git -C "$REPO_ROOT" checkout "$DEFAULT_BRANCH"
git -C "$REPO_ROOT" pull --ff-only origin "$DEFAULT_BRANCH"
```

If `pull --ff-only` fails (local commits exist on default branch), **stop and report** — do NOT
force-reset. This indicates the user has manually committed on master, which needs human review.

---

## Phase 3: Hook Integrity Check (game-engine)

> **Mode gate**: skip if `--repos-only` was passed (always runs in full and `--hooks-only` modes).

This phase verifies that the anti-blowup pre-push guard for game-engine is intact and cannot be
accidentally bypassed. The guard catches the "Claude Code bad rebase" failure mode: branching from
HEAD instead of `origin/master` causes PRs with inflated diffs (hundreds of unrelated files from
upstream master commits appearing in the diff).

Run all checks and collect pass/fail before taking any repair action.

### Check 1: Global guard exists and is executable

```bash
[ -x "$HOME/.git-hooks/pre-push" ] && echo "PASS" || echo "FAIL: $HOME/.git-hooks/pre-push missing or not executable"
```

If the file exists, verify it contains the large-diff guard logic:
```bash
grep -q "LARGE_DIFF_THRESHOLD\|THRESHOLD" "$HOME/.git-hooks/pre-push" && echo "PASS: contains guard" || echo "FAIL: pre-push hook missing large-diff guard logic"
```

### Check 2: No hostile local hookspath override in game-engine

The global `~/.gitconfig` sets `core.hookspath=~/.git-hooks`. A local override in game-engine's
`.git/config` that points away from `~/.git-hooks` would bypass the guard.

```bash
LOCAL_HOOKSPATH=$(git -C "$GAME_ENGINE" config --local core.hookspath 2>/dev/null || echo "")
```

Classify the result:

| Local hookspath value | Safety status |
|---|---|
| `""` (not set) | ✓ SAFE — global `~/.git-hooks` applies |
| `$HOME/.git-hooks` | ✓ SAFE — explicitly same as global |
| `.git/hooks` or `$GAME_ENGINE/.git/hooks` | ⚠ OVERRIDE — check the fallback (Check 3) |
| Any other path | ✗ DANGEROUS — guard likely bypassed |

If status is `DANGEROUS` (some other path that has no hooks or unknown hooks):
```bash
# Repair: remove the local override so global default applies
git -C "$GAME_ENGINE" config --local --unset core.hookspath
echo "✓ Repaired: removed local core.hookspath override, global ~/.git-hooks now applies"
```

If status is `OVERRIDE` (pointing to .git/hooks), proceed to Check 3.

### Check 3: Fallback chain in .git/hooks/pre-push (only relevant when local hookspath = .git/hooks)

The `.git/hooks/pre-push` in game-engine was written to chain to `~/.git-hooks/pre-push` even when
`git lfs install --local` overrides `core.hookspath` to `.git/hooks`. Verify the chain:

```bash
FALLBACK="$GAME_ENGINE/.git/hooks/pre-push"
```

Checks (in order):
1. File exists and is executable: `[ -x "$FALLBACK" ]`
2. It references the global hook: `grep -q 'git-hooks/pre-push\|GLOBAL_HOOK' "$FALLBACK"`
3. The referenced path is correct: `grep -q "$HOME/.git-hooks/pre-push" "$FALLBACK"`

If any check fails, **repair**: write a minimal chaining fallback:

```bash
cat > "$GAME_ENGINE/.git/hooks/pre-push" << 'HOOK'
#!/bin/sh
# Fallback: chain to global large-diff guard when core.hookspath is overridden to .git/hooks
# (e.g. by git lfs install --local). Written by env-check skill.
PUSH_REFS=$(cat)

# Run git-lfs if available
if command -v git-lfs >/dev/null 2>&1; then
    echo "$PUSH_REFS" | git lfs pre-push "$@" || exit $?
fi

# Chain to the global anti-blowup guard
GLOBAL_HOOK="${HOME}/.git-hooks/pre-push"
if [ -x "$GLOBAL_HOOK" ]; then
    echo "$PUSH_REFS" | "$GLOBAL_HOOK" "$@"
    exit $?
fi
HOOK
chmod +x "$GAME_ENGINE/.git/hooks/pre-push"
echo "✓ Repaired: wrote chaining fallback to $GAME_ENGINE/.git/hooks/pre-push"
```

### Check 4: Hook cannot be trivially skipped by accident

Verify that the guard respects the `LARGE_DIFF_OK=1` escape hatch (intentional override) but has
no accidental bypass paths:

```bash
grep -n "LARGE_DIFF_OK" "$HOME/.git-hooks/pre-push"
```

Expected: exactly one line like `if [ -n "$LARGE_DIFF_OK" ]; then exit 0; fi`. If found, report
as ✓. If missing (guard has no intentional escape), report as ⚠ (rigid guard, no override path).

### Check 5: util hookspath deviation (informational)

util has `core.hookspath` set locally to `.git/hooks`. This is non-standard but acceptable since
util is a tooling repo with no LFS. Just report it:

```
ℹ util: core.hookspath=/path/.git/hooks (local override, not using global ~/.git-hooks)
  This is fine for a non-C++ repo. The anti-blowup guard is only required for game-engine.
```

### Hook check report

```
Hook integrity — game-engine
  [✓/✗] Check 1: ~/.git-hooks/pre-push exists, executable, and contains large-diff guard
  [✓/✗] Check 2: No hostile local hookspath override  (local value: <value>)
  [✓/✗] Check 3: .git/hooks/pre-push fallback chains to global guard
  [✓/✗] Check 4: LARGE_DIFF_OK escape hatch present (intentional override path)
  [ℹ]   Check 5: util deviates from global hookspath (informational)

  <Repairs applied (if any)>
  <Final status: All checks pass / N issues repaired / N issues require manual attention>
```

---

## Final Report

```
env-check complete — <timestamp>

Repos synced:
  ✓ game-engine   master (already clean, pulled to <short-sha>)
  ✓ vycor-cpp     main — rescued dirty state to sweepup/YYYYMMDD-main
  ✓ util          main — rescued dirty state to sweepup/YYYYMMDD-main
  ✓ thought-bubble main — rescued dirty state to sweepup/YYYYMMDD-main

Stash rescue (if any):
  <list of rescued stashes or "none requested">

Hook integrity:
  ✓ All 4 checks passed (no repairs needed)
  — or —
  ✓ 1 issue repaired, 3 checks passed

To recover sweepup work:
  git -C <repo> worktree list       # list all worktrees including sweepup
  git -C <repo> branch -l 'sweepup/*'  # list sweepup branches
```
