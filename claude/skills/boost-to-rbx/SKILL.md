---
name: boost-to-rbx
description: Manage the BOOST_→RBX_ macro refactor campaign. Use when: fanning out refactor PRs from the batch manifest, monitoring open refactor PRs for merge conflicts or needed master merges, re-running the replacement script after conflict resolution, or checking overall campaign progress.
---

# BOOST_ → RBX_ Macro Refactor

Cosmetic refactor that replaces `BOOST_*` test macros with their `RBX_*` equivalents.
Compiled output is **identical** — `RBXTest.hpp` defines each `BOOST_` macro as a direct alias.

## Key Files

| File | Purpose |
|------|---------|
| `~/.claude/scripts/boost_to_rbx.py` | Applies substitutions to a set of files |
| `~/.claude/scripts/boost_to_rbx_batch.py` | Parses CODEOWNERS, groups affected files into PR batches |
| `~/.claude/skills/boost-to-rbx/scripts/status.sh` | List all open boost-to-rbx PRs and their CI state |
| `~/.claude/skills/boost-to-rbx/scripts/apply_batch.sh` | Create a branch + apply replacements for one batch |
| `~/.claude/skills/boost-to-rbx/manifest.json` | The generated batch manifest (2046 files, 144 batches) |

## Workflow

### 1. Generate the Batch Manifest (already done — 144 batches in manifest.json)

To re-run if master changes significantly:
```bash
cd /path/to/game-engine
gobot uv run ~/.claude/scripts/boost_to_rbx_batch.py \
  --max-files 40 \
  --out ~/.claude/skills/boost-to-rbx/manifest.json
```

The manifest is a JSON array of batch objects:
```json
[
  {
    "owners": ["@GameEngine/game-engine-systems-core"],
    "batch_id": "game-engine-systems-core-001",
    "files": ["Client/Foo/tests/Bar.cpp", ...]
  }
]
```

### 2. Fan Out PRs (subagents)

For each batch entry, spawn a subagent with this prompt template:

```
Apply the BOOST_→RBX_ macro replacement to these files and open a PR.

Batch: <batch_id>
Owners: <owners>
Files: <files>
Repo root: /Users/amason/git/roblox/game-engine

Steps:
1. cd /Users/amason/git/roblox/game-engine
2. git fetch origin master
3. git worktree add .claude/worktrees/boost-<batch_id> origin/master
4. cd .claude/worktrees/boost-<batch_id>
5. git checkout -b refactor/boost-to-rbx-<batch_id>
6. /Users/amason/git/roblox/game-engine/Tools/Util/gobot uv run \
     ~/.claude/scripts/boost_to_rbx.py <files...>
7. verify: gobot uv run ~/.claude/scripts/boost_to_rbx.py --check <files...>  # must exit 0
8. git add <files...>
9. git commit -m "refactor: replace BOOST_ macros with RBX_ equivalents (<batch_id>)

Purely cosmetic — compiled output unchanged.
RBXTest.hpp defines BOOST_* as direct aliases to RBX_*, so this removes
the indirection at the source level."
10. git push origin refactor/boost-to-rbx-<batch_id>
11. gh pr create --title "refactor: BOOST_→RBX_ macro replacement (<batch_id>) #nonprod" \
      --body "..." --base master
```

### 3. Monitor Open PRs

```bash
.claude/skills/boost-to-rbx/scripts/status.sh
```

For each PR that is behind master or has conflicts:
1. Run `/merge-master` on that branch
2. If the replacement script needs re-running (rare: if a new BOOST_ macro appeared), run it again
3. Push the updated branch

### 4. Track Campaign Progress

```bash
.claude/skills/boost-to-rbx/scripts/status.sh --summary
```

Shows: total PRs opened, merged, closed, still open, failing CI.

## Guardrails

- **Never** modify `Client/Base.UnitTest.Lib/` — these are the compat shim files that define the BOOST_ aliases.
- **Never** touch files under `Client/dependencies/` (managed by gobot).
- **Always** check the diff before pushing: `git diff HEAD~1 --stat` should show only `.cpp`/`.h` changes.
- The replacement script is idempotent — running it twice on the same file is safe.

## Conflict Resolution

If a PR has merge conflicts after merging master:
1. Checkout the branch
2. `git merge master`
3. For conflicted files: accept the incoming (master) version for any non-test lines; for test assertion lines that conflict, apply the replacement script to the resolved file
4. `gobot uv run Tools/Scripts/boost_to_rbx.py --check <conflicted files>` — must exit 0 after resolution

## PR Status Codes

| Status | Meaning | Action |
|--------|---------|--------|
| `OPEN` | Normal | None |
| `BEHIND` | Needs master merge | Run `/merge-master` |
| `CONFLICT` | Has merge conflicts | Resolve + re-run script |
| `CI_FAIL` | Tests failing | Investigate — should be rare since this is purely cosmetic |
| `MERGED` | Done ✓ | None |
