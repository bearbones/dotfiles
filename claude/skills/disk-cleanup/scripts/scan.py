#!/usr/bin/env python3
"""
Disk cleanup scanner — finds the largest reclaimable disk consumers.
Outputs a JSON array of items with their sizes and cleanup metadata.
"""
import json
import os
import subprocess
import threading
from pathlib import Path

HOME = Path.home()


def du_bytes(path: str) -> int:
    """Return total size in bytes, or 0 if path doesn't exist."""
    p = Path(path)
    if not p.exists():
        return 0
    try:
        result = subprocess.run(
            ["du", "-sk", path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            kb = int(result.stdout.split()[0])
            return kb * 1024
    except Exception:
        pass
    return 0


def fmt(n: int) -> str:
    for unit, threshold in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
        if n >= threshold:
            return f"{n / threshold:.1f} {unit}"
    return f"{n} B"


def find_buck_outs() -> list[dict]:
    results = []
    git_root = HOME / "git"
    if not git_root.exists():
        return results
    for repo_dir in git_root.rglob("buck-out"):
        if repo_dir.is_dir() and ".claude/worktrees" not in str(repo_dir):
            size = du_bytes(str(repo_dir))
            if size > 0:
                results.append({
                    "category": "buck-out",
                    "path": str(repo_dir),
                    "size_bytes": size,
                    "size_human": fmt(size),
                    "safe": False,
                    "note": "Build cache — next build will be cold (remote cache helps)",
                    "command": f"rm -rf {repo_dir}",
                })
    return results


def find_worktrees() -> list[dict]:
    """Find locked/detached-HEAD worktrees across all repos under ~/git."""
    results = []
    git_root = HOME / "git"
    if not git_root.exists():
        return results

    # Find all main git repos (where .git is a directory, not a file)
    repos = []
    for dirpath, dirnames, _ in os.walk(git_root):
        git_dir = Path(dirpath) / ".git"
        if git_dir.is_dir():
            repos.append(dirpath)
            dirnames.clear()  # don't descend into submodules

    for repo in repos:
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True, text=True, cwd=repo, timeout=10
            )
            if result.returncode != 0:
                continue

            current_wt = None
            first = True
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    if current_wt and not first:
                        _check_worktree(repo, current_wt, results)
                    current_wt = {"path": line.split(" ", 1)[1], "branch": None,
                                  "locked": False, "detached": False, "commit": None}
                    first = False
                elif line.startswith("HEAD "):
                    if current_wt:
                        current_wt["commit"] = line.split()[1]
                elif line == "detached":
                    if current_wt:
                        current_wt["detached"] = True
                elif line.startswith("branch "):
                    if current_wt:
                        current_wt["branch"] = line.split(" ", 1)[1]
                elif line.startswith("locked"):
                    if current_wt:
                        current_wt["locked"] = True

            if current_wt and not first:
                _check_worktree(repo, current_wt, results)

        except Exception:
            pass

    return results


def _check_worktree(repo: str, wt: dict, results: list):
    path = wt["path"]
    if not Path(path).exists():
        # dangling — git knows about it but directory is gone
        results.append({
            "category": "worktree-dangling",
            "path": path,
            "size_bytes": 0,
            "size_human": "0 B",
            "safe": True,
            "note": f"Dangling worktree (directory gone) in {repo}",
            "command": f"git -C {repo!r} worktree prune",
        })
        return

    if wt["detached"] and wt["locked"]:
        size = du_bytes(path)
        results.append({
            "category": "worktree-stale-locked",
            "path": path,
            "size_bytes": size,
            "size_human": fmt(size),
            "safe": False,
            "note": f"Locked detached-HEAD worktree (abandoned session) in {repo}",
            "command": f"git -C {repo!r} worktree remove --force {path!r}",
        })


def find_caches() -> list[dict]:
    candidates = [
        {
            "category": "cache-uv",
            "path": str(HOME / ".cache/uv"),
            "note": "uv Python package cache — safe, rebuilt on demand",
            "safe": True,
            "command": "uv cache clean",
        },
        {
            "category": "cache-github-copilot",
            "path": str(HOME / ".cache/github-copilot"),
            "note": "GitHub Copilot context cache — safe to delete",
            "safe": True,
            "command": f"rm -rf {HOME}/.cache/github-copilot",
        },
        {
            "category": "cache-pip",
            "path": str(HOME / "Library/Caches/pip"),
            "note": "pip package cache — safe to delete",
            "safe": True,
            "command": f"rm -rf {HOME}/Library/Caches/pip",
        },
        {
            "category": "cache-homebrew-downloads",
            "path": str(HOME / "Library/Caches/Homebrew"),
            "note": "Homebrew download cache — safe (re-downloaded on demand)",
            "safe": True,
            "command": "brew cleanup --prune=all 2>/dev/null || rm -rf ~/Library/Caches/Homebrew",
        },
    ]
    results = []
    for c in candidates:
        size = du_bytes(c["path"])
        if size > 1 << 20:  # only report if >1 MB
            c["size_bytes"] = size
            c["size_human"] = fmt(size)
            results.append(c)
    return results


def find_tmp_orphans() -> list[dict]:
    """Orphaned worktree directories in /tmp that are no longer git-tracked."""
    results = []
    tmp = Path("/private/tmp")
    if not tmp.exists():
        tmp = Path("/tmp")

    # Collect all git-tracked worktree paths
    tracked = set()
    git_root = HOME / "git"
    if git_root.exists():
        for dirpath, dirnames, _ in os.walk(git_root):
            git_dir = Path(dirpath) / ".git"
            if git_dir.is_dir():
                try:
                    r = subprocess.run(
                        ["git", "worktree", "list", "--porcelain"],
                        capture_output=True, text=True, cwd=dirpath, timeout=10
                    )
                    for line in r.stdout.splitlines():
                        if line.startswith("worktree "):
                            tracked.add(line.split(" ", 1)[1].rstrip())
                except Exception:
                    pass
                dirnames.clear()

    patterns = ["doc-fix-*", "worktree-*", "openapi-fix-*"]
    for pattern in patterns:
        for d in tmp.glob(pattern):
            if d.is_dir() and str(d) not in tracked:
                size = du_bytes(str(d))
                results.append({
                    "category": "tmp-orphan",
                    "path": str(d),
                    "size_bytes": size,
                    "size_human": fmt(size),
                    "safe": True,
                    "note": "Orphaned /tmp worktree directory (not git-tracked)",
                    "command": f"rm -rf {d!r}",
                })

    return results


def find_simulator_runtimes() -> dict:
    path = str(HOME / "Library/Developer/CoreSimulator")
    size = du_bytes(path)
    if size == 0:
        return None
    return {
        "category": "ios-simulator",
        "path": path,
        "size_bytes": size,
        "size_human": fmt(size),
        "safe": True,
        "note": "iOS simulator runtimes — 'unavailable' ones can be deleted",
        "command": "xcrun simctl delete unavailable",
    }


def main():
    all_items = []
    lock = threading.Lock()

    def collect(fn):
        items = fn()
        with lock:
            if isinstance(items, list):
                all_items.extend(items)
            elif items:
                all_items.append(items)

    threads = [
        threading.Thread(target=collect, args=(find_buck_outs,)),
        threading.Thread(target=collect, args=(find_worktrees,)),
        threading.Thread(target=collect, args=(find_caches,)),
        threading.Thread(target=collect, args=(find_tmp_orphans,)),
        threading.Thread(target=collect, args=(find_simulator_runtimes,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_items.sort(key=lambda x: x["size_bytes"], reverse=True)
    print(json.dumps(all_items, indent=2))


if __name__ == "__main__":
    main()
