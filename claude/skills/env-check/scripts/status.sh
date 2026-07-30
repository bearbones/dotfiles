#!/usr/bin/env bash
# Quick status snapshot for all key repos. Outputs structured lines for the skill to parse.
# Format: REPO|PATH|BRANCH|DEFAULT|DIRTY_TRACKED|UNTRACKED|STASH_COUNT|HOOKSPATH
#
# DIRTY_TRACKED: number of modified/deleted/staged tracked files
# UNTRACKED: number of untracked files
# STASH_COUNT: number of stash entries

set -uo pipefail

check_repo() {
    local name="$1" path="$2" default="$3"

    if [ ! -d "$path/.git" ]; then
        echo "$name|$path|MISSING|$default|0|0|0|(no .git)"
        return
    fi

    local branch dirty_tracked untracked stash_count hookspath porcelain
    branch=$(git -C "$path" branch --show-current 2>/dev/null || echo "DETACHED")

    porcelain=$(git -C "$path" status --porcelain 2>/dev/null || true)
    dirty_tracked=$(printf '%s\n' "$porcelain" | grep -v '^??' | grep -v '^$' | wc -l | tr -d ' ')
    untracked=$(printf '%s\n' "$porcelain" | grep '^??' | wc -l | tr -d ' ')

    stash_count=$(git -C "$path" stash list 2>/dev/null | wc -l | tr -d ' ')
    hookspath=$(git -C "$path" config --local core.hookspath 2>/dev/null || echo "(none)")

    echo "$name|$path|$branch|$default|$dirty_tracked|$untracked|$stash_count|$hookspath"
}

check_repo "game-engine"    "$HOME/git/roblox/game-engine"    "master"
check_repo "vycor-cpp"      "$HOME/git/roblox/vycor-cpp"      "main"
check_repo "util"           "$HOME/git/roblox/util"            "main"
check_repo "thought-bubble" "$HOME/git/roblox/thought-bubble"  "main"
