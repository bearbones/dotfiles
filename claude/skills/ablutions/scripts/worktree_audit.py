#!/usr/bin/env python3
"""
worktree_audit.py - Audit git worktrees across repos under ~/git.

Finds all main repos (where .git is a directory) and categorizes every
non-main worktree by staleness. Outputs JSON.

Categories (ordered by priority):
  prunable      - git already detected the directory is gone; safe to prune
  dangling      - directory doesn't exist but git didn't catch it; force-remove
  merged_pr     - PR is MERGED, working tree clean → auto-remove
  fully_merged  - branch has no unique commits vs default branch, no PR or closed → auto-remove
  closed_pr     - PR is CLOSED/abandoned, working tree clean → flag for user
  detached      - detached HEAD (no branch name); likely a temp review worktree
  stale_no_pr   - branch has no open PR, last commit > STALE_DAYS ago
  dirty         - uncommitted changes; never auto-remove
  active        - open PR or recent commit; keep

Usage:
  python3 worktree_audit.py [--search-root DIR]   (default: ~/git)
  python3 worktree_audit.py --repo /path/to/repo  (single repo)

Env:
  ABLUTIONS_GH_HOST   (default: github.rbx.com)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

STALE_DAYS = int(os.environ.get("ABLUTIONS_STALE_DAYS", "14"))
GH_HOST = os.environ.get("ABLUTIONS_GH_HOST", "github.rbx.com")

# Repos with an internal GHE instance → look up PRs
GH_REPOS: dict[str, str] = {
    "game-engine": "GameEngine/game-engine",
    "builderai":   "GameEngine/builderai",
    "util":        "GameEngine/util",
}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], cwd: Optional[str] = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def parse_worktree_porcelain(output: str) -> list[dict]:
    """Parse `git worktree list --porcelain` output into a list of dicts."""
    worktrees = []
    current: dict = {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):].strip(), "prunable": False}
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            ref = line[7:].strip()
            current["branch"] = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        elif line == "detached":
            current["detached"] = True
        elif "prunable" in line:
            current["prunable"] = True
    if current:
        worktrees.append(current)
    return worktrees


def check_dirty(path: str) -> list[str]:
    """Return list of changed files, or [] if clean."""
    r = run(["git", "status", "--porcelain"], cwd=path)
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def last_commit_days(path: str) -> float:
    """Days since the last commit in this worktree."""
    r = run(["git", "log", "-1", "--format=%ct"], cwd=path)
    if r.returncode != 0 or not r.stdout.strip():
        return 999.0
    ts = int(r.stdout.strip())
    return (time.time() - ts) / 86400


def last_modified_hours(path: str) -> float:
    """Hours since the most recently modified file under path (shallow walk)."""
    try:
        latest = max(
            (os.path.getmtime(os.path.join(root, f))
             for root, _, files in os.walk(path)
             for f in files
             if ".git" not in root),
            default=0.0,
        )
        return (time.time() - latest) / 3600
    except Exception:
        return 999.0


def branch_unique_commits(repo_root: str, branch: str, default_branch: str = "master") -> int:
    """Number of commits on branch not reachable from origin/default_branch."""
    r = run(
        ["git", "log", "--oneline", f"origin/{default_branch}..{branch}"],
        cwd=repo_root,
    )
    if r.returncode != 0:
        return -1  # unknown
    return len([l for l in r.stdout.splitlines() if l.strip()])


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def check_pr(branch: str, repo: str) -> Optional[dict]:
    """Return the most recent PR for this branch (any state), or None."""
    env = {**os.environ, "GH_HOST": GH_HOST}
    r = subprocess.run(
        [
            "gh", "pr", "list",
            "--head", branch,
            "--state", "all",
            "--repo", repo,
            "--json", "number,state,mergedAt,title",
            "--limit", "1",
        ],
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    items = json.loads(r.stdout)
    return items[0] if items else None


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

def categorize(wt: dict, repo_root: str, repo_slug: Optional[str], default_branch: str = "master") -> dict:
    path    = wt["path"]
    branch  = wt.get("branch")
    prunable = wt.get("prunable", False)
    detached = wt.get("detached", False) or not branch

    # 1. Git already knows the directory is gone
    if prunable:
        return {"category": "prunable", "action": "prune"}

    # 2. Directory doesn't exist (git missed it)
    if not os.path.exists(path):
        return {"category": "dangling", "action": "force_remove"}

    # 3. Dirty check first (overrides everything — never auto-remove dirty worktrees)
    dirty = check_dirty(path)

    # 4. PR state (only for repos with a known GH slug)
    pr_info = None
    if branch and repo_slug:
        pr_info = check_pr(branch, repo_slug)

    if pr_info:
        state = pr_info["state"]
        if state == "MERGED" and not dirty:
            return {"category": "merged_pr",  "action": "auto_remove",
                    "pr": pr_info["number"], "pr_title": pr_info.get("title", "")}
        if state == "CLOSED" and not dirty:
            return {"category": "closed_pr",  "action": "suggest_remove",
                    "pr": pr_info["number"], "pr_title": pr_info.get("title", "")}
        if state == "OPEN":
            return {"category": "active", "action": "keep",
                    "pr": pr_info["number"], "pr_title": pr_info.get("title", "")}

    # 5. Branch fully merged into default_branch (no open PR or closed)
    if branch and not dirty:
        unique = branch_unique_commits(repo_root, branch, default_branch)
        if unique == 0:
            return {"category": "fully_merged", "action": "auto_remove", "branch": branch}

    # 6. Detached HEAD (no branch name) — likely a temp review worktree
    if detached or not branch:
        hours_old = last_modified_hours(path)
        dirty_flag = bool(dirty)
        action = "flag_dirty" if dirty_flag else ("suggest_remove" if hours_old > 24 else "keep")
        return {
            "category": "detached",
            "action": action,
            "hours_old": round(hours_old, 1),
            "dirty": dirty_flag,
            "dirty_files": dirty if dirty_flag else [],
        }

    # 7. Dirty → flag, never auto-remove
    if dirty:
        return {
            "category": "dirty",
            "action": "flag_dirty",
            "dirty_files": dirty[:10],
            "pr": pr_info["number"] if pr_info else None,
        }

    # 8. No PR, stale
    days = last_commit_days(path)
    if days > STALE_DAYS:
        return {"category": "stale_no_pr", "action": "suggest_remove",
                "days_old": round(days, 1), "branch": branch}

    # 9. No PR but recent
    return {"category": "no_pr_recent", "action": "keep",
            "days_old": round(last_commit_days(path), 1), "branch": branch}


# ---------------------------------------------------------------------------
# Repo discovery
# ---------------------------------------------------------------------------

def find_main_repos(search_root: str) -> list[str]:
    """Find all git main repos (where .git is a directory) under search_root."""
    repos = []
    for root, dirs, _ in os.walk(search_root):
        depth = root.replace(search_root, "").count(os.sep)
        if depth > 3:
            dirs.clear()
            continue
        if ".git" in dirs:
            # It's a main repo
            repos.append(root)
            # Don't descend into it (worktrees inside are linked, not main repos)
            dirs.clear()
    return sorted(repos)


def audit_repo(repo_root: str) -> list[dict]:
    r = run(["git", "worktree", "list", "--porcelain"], cwd=repo_root)
    if r.returncode != 0:
        return []

    worktrees = parse_worktree_porcelain(r.stdout)
    if len(worktrees) <= 1:
        return []  # Only main worktree, nothing to audit

    # Detect default branch
    r2 = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_root)
    default_branch = "master"
    if r2.returncode == 0:
        default_branch = r2.stdout.strip().replace("refs/remotes/origin/", "")

    # Determine GH slug for this repo
    repo_name = os.path.basename(repo_root.rstrip("/"))
    repo_slug = GH_REPOS.get(repo_name)

    results = []
    main_path = worktrees[0]["path"]
    for wt in worktrees[1:]:  # skip main
        info = categorize(wt, repo_root, repo_slug, default_branch)
        results.append({
            "repo":          repo_root,
            "repo_name":     repo_name,
            "path":          wt["path"],
            "branch":        wt.get("branch"),
            "head":          wt.get("head", "")[:12],
            **info,
        })
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if "--repo" in args:
        idx = args.index("--repo")
        repos = [os.path.expanduser(args[idx + 1])]
    else:
        search_root = os.path.expanduser(
            args[args.index("--search-root") + 1] if "--search-root" in args else "~/git"
        )
        print(f"[worktree_audit] Scanning for repos under {search_root}...", file=sys.stderr)
        repos = find_main_repos(search_root)
        print(f"[worktree_audit] Found {len(repos)} repos", file=sys.stderr)

    all_worktrees: list[dict] = []
    for repo in repos:
        print(f"[worktree_audit]   {repo}", file=sys.stderr)
        all_worktrees.extend(audit_repo(repo))

    # Summary counts
    from collections import Counter
    counts = Counter(w["category"] for w in all_worktrees)

    output = {
        "stale_days_threshold": STALE_DAYS,
        "total": len(all_worktrees),
        "counts": dict(counts),
        "worktrees": all_worktrees,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
