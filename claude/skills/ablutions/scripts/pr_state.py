#!/usr/bin/env python3
"""
pr_state.py - Discover and categorize open PRs for the ablutions skill.

Outputs JSON with four buckets:
  first_review        - review-requested PRs with no prior review from amason/aladavac
  rereview            - review-requested PRs with new non-merge commits since last review
  waiting_for_author  - review-requested PRs where author hasn't responded yet
  authored_needs_work - amason's PRs that have reviewer comments
  authored_approved   - amason's PRs that are fully approved

Usage:
  python3 pr_state.py [--repo OWNER/REPO] [--host GH_HOST] [--mode review|comments|merge|all]

Modes:
  review   - fetch only review-requested PRs (first_review, rereview, waiting_for_author)
  comments - fetch only authored PRs with comments (authored_needs_work)
  merge    - fetch only authored approved PRs (authored_approved)
  all      - fetch everything (default)
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

GH_HOST = os.environ.get("ABLUTIONS_GH_HOST", "github.rbx.com")
REPO    = os.environ.get("ABLUTIONS_REPO", "GameEngine/game-engine")
ME      = os.environ.get("ABLUTIONS_ME", "amason")
# aladavac is the review bot; its reviews count as amason's for agent-config PRs
PROXY_REVIEWERS = {ME, "aladavac"}


def gh_json(*args: str) -> object:
    env = {**os.environ, "GH_HOST": GH_HOST}
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else []


def gh_api(path: str) -> object:
    return gh_json("api", f"repos/{REPO}/{path}", "--paginate")


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def is_merge_from_master(commit: dict) -> bool:
    if len(commit.get("parents", [])) < 2:
        return False
    msg = commit.get("commit", {}).get("message", "").lower()
    return any(kw in msg for kw in ("merge branch 'master'", "merge branch 'main'", "merge master", "merge main"))


def categorize_review_request(pr_num: int, title: str) -> dict:
    try:
        reviews = gh_api(f"pulls/{pr_num}/reviews")
    except RuntimeError as e:
        return {"category": "error", "error": str(e)}

    my_reviews = [
        r for r in reviews
        if r["user"]["login"] in PROXY_REVIEWERS and r.get("state") not in ("PENDING", "DISMISSED")
    ]

    if not my_reviews:
        return {"category": "first_review"}

    latest = max(my_reviews, key=lambda r: r.get("submitted_at") or "")
    reviewed_at = parse_dt(latest["submitted_at"])
    reviewed_sha = latest.get("commit_id", "")

    try:
        commits = gh_api(f"pulls/{pr_num}/commits")
    except RuntimeError as e:
        return {"category": "error", "error": str(e)}

    new_commits = [
        c for c in commits
        if not is_merge_from_master(c)
        and parse_dt(c["commit"]["author"]["date"]) > reviewed_at
    ]

    head_sha = commits[-1]["sha"] if commits else ""

    if new_commits:
        return {
            "category": "rereview",
            "previous_sha": reviewed_sha,
            "head_sha": head_sha,
            "new_commit_count": len(new_commits),
            "reviewed_by": latest["user"]["login"],
        }
    return {
        "category": "waiting_for_author",
        "last_review_sha": reviewed_sha,
        "reviewed_by": latest["user"]["login"],
    }


def process_authored_pr(pr: dict) -> dict:
    pr_num = pr["number"]
    try:
        comments = gh_api(f"pulls/{pr_num}/comments")
        reviews  = gh_api(f"pulls/{pr_num}/reviews")
        commits  = gh_api(f"pulls/{pr_num}/commits")
    except RuntimeError as e:
        return {"error": str(e)}

    last_commit_at = commits[-1]["commit"]["author"]["date"] if commits else ""
    head_sha       = commits[-1]["sha"] if commits else ""

    reviewer_comments = [
        c for c in comments
        if c["user"]["login"] not in (ME, "github-actions[bot]", "gedevops-build", "aladavac")
    ]

    non_me_reviews = [r for r in reviews if r["user"]["login"] != ME and r.get("state") not in ("PENDING",)]
    reviewers      = list({r["user"]["login"] for r in non_me_reviews})

    return {
        "approved": pr.get("reviewDecision") == "APPROVED",
        "comment_count": len(reviewer_comments),
        "head_sha": head_sha,
        "last_commit_at": last_commit_at,
        "reviewers": reviewers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and categorize open PRs for ablutions.")
    parser.add_argument("--repo",  default=None, help="Override ABLUTIONS_REPO")
    parser.add_argument("--host",  default=None, help="Override ABLUTIONS_GH_HOST")
    parser.add_argument("--mode",  default="all",
                        choices=["all", "review", "comments", "merge"],
                        help="Scope which PRs to fetch (default: all)")
    args = parser.parse_args()

    if args.repo:
        global REPO
        REPO = args.repo
    if args.host:
        global GH_HOST
        GH_HOST = args.host

    mode = args.mode
    fetch_reviews  = mode in ("all", "review")
    fetch_authored = mode in ("all", "comments", "merge")
    # In merge mode we only care about approved PRs; in comments mode only needs-work.
    authored_filter = mode  # "all" | "comments" | "merge"

    first_review, rereview, waiting_for_author = [], [], []
    authored_approved, authored_needs_work = [], []
    errors = []

    if fetch_reviews:
        print("[ablutions] Fetching review requests...", file=sys.stderr)
        try:
            review_requests = gh_json(
                "pr", "list",
                "--search", "review-requested:@me",
                "--state", "open",
                "--repo", REPO,
                "--json", "number,title,author,headRefName,reviewDecision",
                "--limit", "300",
            )
        except RuntimeError as e:
            print(f"ERROR fetching review requests: {e}", file=sys.stderr)
            review_requests = []

        for pr in review_requests:
            print(f"[ablutions]   Checking PR #{pr['number']}: {pr['title'][:50]}", file=sys.stderr)
            result = categorize_review_request(pr["number"], pr["title"])
            entry = {
                "number":  pr["number"],
                "title":   pr["title"],
                "author":  pr["author"]["login"],
                "branch":  pr["headRefName"],
                **result,
            }
            cat = result["category"]
            if cat == "first_review":
                first_review.append(entry)
            elif cat == "rereview":
                rereview.append(entry)
            elif cat == "waiting_for_author":
                waiting_for_author.append(entry)
            else:
                errors.append(entry)

    if fetch_authored:
        print("[ablutions] Fetching authored PRs...", file=sys.stderr)
        try:
            authored = gh_json(
                "pr", "list",
                "--author", "@me",
                "--state", "open",
                "--repo", REPO,
                "--json", "number,title,headRefName,reviewDecision,updatedAt",
                "--limit", "300",
            )
        except RuntimeError as e:
            print(f"ERROR fetching authored PRs: {e}", file=sys.stderr)
            authored = []

        for pr in authored:
            print(f"[ablutions]   Checking authored PR #{pr['number']}: {pr['title'][:50]}", file=sys.stderr)
            result = process_authored_pr(pr)
            if "error" in result:
                errors.append({"number": pr["number"], "title": pr["title"], **result})
                continue
            entry = {
                "number": pr["number"],
                "title":  pr["title"],
                "branch": pr["headRefName"],
                **result,
            }
            if result["approved"]:
                if authored_filter in ("all", "merge"):
                    authored_approved.append(entry)
            if result["comment_count"] > 0:
                if authored_filter in ("all", "comments"):
                    authored_needs_work.append(entry)
            # PRs that are neither approved nor have comments are waiting for reviewer — skip

    output = {
        "me":                  ME,
        "repo":                REPO,
        "gh_host":             GH_HOST,
        "mode":                mode,
        "first_review":        first_review,
        "rereview":            rereview,
        "waiting_for_author":  waiting_for_author,
        "authored_needs_work": authored_needs_work,
        "authored_approved":   authored_approved,
        "errors":              errors,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
