---
name: disk-cleanup
description: Scan for reclaimable disk space (buck-out, worktrees, caches, simulator runtimes) and clean up selected items.
argument-hint: [--auto]
---

# Disk Cleanup

Scans the system for the largest reclaimable disk consumers, presents a prioritized table, and cleans what's approved.

## Flags

- `--auto` — skip confirmation prompts and clean everything that is marked `safe: true`. Destructive items (`safe: false`) are still listed but never touched without explicit confirmation.

---

## Phase 1: Scan

Run the scan script and parse the JSON output:

```bash
~/.claude/skills/disk-cleanup/scripts/scan.py
```

The script discovers (in parallel):
- **buck-out** directories under `~/git/` — build caches
- **Stale worktrees** — locked detached-HEAD worktrees and dangling entries
- **Caches** — uv, GitHub Copilot, pip, Homebrew
- **Orphaned /tmp directories** — ex-worktrees no longer tracked by git
- **iOS simulator runtimes** — `~/Library/Developer/CoreSimulator`

Each item has:
- `category` — what type of item it is
- `path` — filesystem path
- `size_human` — human-readable size (e.g., "113.0 GB")
- `size_bytes` — for sorting
- `safe` — true means no rebuild/cold-start penalty; false means destructive or has side effects
- `note` — one-line explanation
- `command` — the exact command to run to clean it

---

## Phase 2: Report

Display a table sorted by size descending:

```
Disk Cleanup Scan — <date>
┌────────────────────────────────────────────────────┬──────────┬───────┐
│ Item                                               │ Size     │ Safe? │
├────────────────────────────────────────────────────┼──────────┼───────┤
│ [buck-out]       ~/git/roblox/game-engine/buck-out │ 113.0 GB │  ⚠   │
│ [worktree-stale] .claude/worktrees/fix-12345       │   2.1 GB │  ⚠   │
│ [cache-uv]       ~/.cache/uv                       │   4.7 GB │  ✓   │
│ [cache-copilot]  ~/.cache/github-copilot           │   4.5 GB │  ✓   │
│ [tmp-orphan]     /tmp/doc-fix-155628               │   2.2 GB │  ✓   │
│ [ios-simulator]  ~/Library/Developer/CoreSimulator │   1.0 GB │  ✓   │
└────────────────────────────────────────────────────┴──────────┴───────┘

Total reclaimable:  127.5 GB
  Safe to clean:    12.4 GB  (no side effects)
  Needs confirm:   115.1 GB  (cold rebuild or manual verification)
```

If no items are found, report "Disk looks clean — nothing significant found."

---

## Phase 3: Clean

### Safe items (✓)

For safe items, either:
- **`--auto` flag**: clean all safe items immediately, reporting each one.
- **Interactive mode (default)**: list the safe items and ask "Clean all safe items? (Y/n)". If yes, run them all. If no, skip.

Run each item's `command` in sequence. After each command succeeds, report:
```
✓ Freed ~{size_human}: {category} — {path}
```

If a command fails, report the error and continue with the next item.

### Destructive items (⚠)

Destructive items are **never** cleaned automatically, even with `--auto`.

For each destructive item, ask individually:

```
⚠ {size_human}  [{category}]  {path}
   {note}
   Command: {command}
   Clean this? (y/N):
```

Default is N. Only run the command if the user explicitly answers "y" or "yes".

---

## Phase 4: Summary

After all cleanups, show a final summary:

```
Disk Cleanup Complete

  Freed:    {total freed}
  Skipped:  {total skipped}

Remaining items (not cleaned):
  {list any items that were skipped or declined}
```

If any buck-out was cleaned, add a note:
```
Note: Next build will be a cold Buck2 build. The remote cache should cover most targets.
```

If any stale worktrees were removed, run `git worktree prune` on the affected repos to clean up git's internal references:
```bash
git -C {repo_root} worktree prune
```
