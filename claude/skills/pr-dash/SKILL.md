---
name: pr-dash
description: Fast, complete replacement for the org PR Dashboard. Categorizes all open PRs (to-review, waiting, commented, approved), shows failing checks + outstanding CODEOWNERS groups + reviewer states, and drills into the gated-commits integrator down to the specific TeamCity build or GHA step. Read-only — for taking action on the queue (reviews, comments, merges) use the `ablutions` skill.
argument-hint: [show|refresh|<PR#>|failing] 
---

# PR Dashboard

A read-only view of the whole PR queue. The org dashboard is slow, greyboxes on
refocus, and silently drops PRs when you have many open (200+); this fetches the
entire set in two paginated GraphQL calls, caches it, and renders instantly.

**This skill is read-only.** To actually work the queue — submit reviews, address
comments, merge master, enable auto-merge — use the `ablutions` skill instead.

## Constants

```
SCRIPT="$HOME/.claude/skills/pr-dash/scripts/pr_dash.py"   # symlinked from dotfiles
CACHE="$HOME/.cache/ge/pr_dash.json"
GH_HOST=github.rbx.com   REPO=GameEngine/game-engine   ME=amason
```

Config is overridable via env: `PRD_REPO`, `PRD_ME`, `PRD_TTL` (cache-freshness
seconds for `show`, default 300), `GH_HOST`.

## Commands

```bash
python3 "$SCRIPT" refresh          # force fetch + rewrite cache (~60s at 200 PRs)
python3 "$SCRIPT" show             # tables from cache; auto-refresh if >TTL stale
python3 "$SCRIPT" show --cached    # never auto-refresh (use the cache as-is)
python3 "$SCRIPT" show --review    # only the "assigned to me to review" bucket
python3 "$SCRIPT" show --mine      # only my authored buckets
python3 "$SCRIPT" show --failing   # only my CI-red authored PRs
python3 "$SCRIPT" show --json      # raw cached dataset (for further processing)
python3 "$SCRIPT" drill <PR#>          # one PR: non-green checks + integrator build
python3 "$SCRIPT" drill <PR#> --logs   # also pull failing GHA job logs
```

Interactively, the `prd` shell function wraps all of these (`prd`, `prd refresh`,
`prd <PR#>`, `prd failing`, `prd watch`). Agents should call the script directly
(the shell function isn't defined in non-interactive shells).

## Buckets

| Bucket    | Meaning                                                            |
|-----------|-------------------------------------------------------------------|
| review    | PRs where I'm a requested reviewer                                |
| waiting   | my open PRs waiting on reviewers / CODEOWNERS groups (no comments) |
| comments  | my PRs with human comments or CHANGES_REQUESTED (maybe unaddressed)|
| approved  | my fully-approved PRs                                              |

Row annotations: `⦿` outstanding CODEOWNERS **teams** (still-required approval
groups), `@user` requested individuals, `⟲ changes:` who requested changes,
`💬` who commented, `✔` who approved, `[integrator ✗ tc:<id>]` failing gated-commits
integrator with its TeamCity build id. `✗N` = N failing checks; `~` = branch is
stale (merge master); `●` = checks pending.

## Deep-dive: the gated-commits integrator (TeamCity)

The merge gate is the **`Integrator (Gated Commits (PR))` StatusContext**, not the
identically-named GHA `gated-commits` CheckRun. Its `targetUrl` ends in the
TeamCity build id (e.g. `.../buildConfiguration/gc_integrator/70923663`). `drill`
surfaces that id. To find the *specific* failing test or step, use the TeamCity
MCP tools on that build id:

1. Get the build id: `python3 "$SCRIPT" drill <PR#>` (or read `_checks.integrator.build_id`
   from `show --json`). Configs: `gc_integrator` (full), `gc_lite_integrator` (lite).
2. Deep-dive with TeamCity MCP:
   - `get_build(id)` — expands problems, failed tests, changes inline (best entry point).
   - `list_build_problems(build_id)` — compiler/exit-code/non-test failures.
   - `list_tests(build_id, status="FAILURE")` — the failing test cases.
   - `get_build_log(id, tail=200)` — end of the log (where failures print); always
     use `tail` on large logs.

Integrator failures on test-infra PRs are frequently **python static checks** or a
single flaky test — the log tail or `list_tests` usually pinpoints it in one call.

## Deep-dive: a failing GHA step

For a failing `CheckRun` (its `detailsUrl` contains `/runs/<run_id>`):

```bash
python3 "$SCRIPT" drill <PR#> --logs        # auto-extracts run_id, tails --log-failed
# or manually:
GH_HOST=github.rbx.com gh run view <run_id> --log-failed --repo GameEngine/game-engine | tail -100
```

`PR Tag + Jira Check` and `Branch Freshness` failures are handled by the `ablutions`
skill (Jira testing-instructions fix / merge-master), not here.
