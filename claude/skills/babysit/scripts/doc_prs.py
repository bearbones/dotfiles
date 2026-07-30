#!/usr/bin/env python3
"""Discover and report documentation PR states for the babysit skill."""
import json
import subprocess
import sys
import re

GH_HOST = "github.rbx.com"
REPO = "GameEngine/game-engine"
AUTHOR = "amason"

# Patterns that identify a "documentation PR"
DOC_BRANCH_RE = re.compile(
    r"(feature/doc-gen|docs/|nonprod/.*doc|.*_CLAUDE|.*claude\.md|"
    r".*documentation|.*preread|.*PREREAD)",
    re.IGNORECASE,
)
DOC_TITLE_RE = re.compile(
    r"\b(doc|docs|documentation|CLAUDE\.md|_CLAUDE|module doc|knowledge.harvest)\b",
    re.IGNORECASE,
)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def fetch_prs():
    out, err, rc = run([
        "gh", "pr", "list",
        "--author", AUTHOR,
        "--state", "open",
        "--repo", REPO,
        "--limit", "9999",
        "--json", "number,title,reviewDecision,headRefName,mergeStateStatus,url",
    ])
    if rc != 0:
        print(f"ERROR: gh pr list failed: {err}", file=sys.stderr)
        sys.exit(1)
    return json.loads(out)


def is_doc_pr(pr):
    branch = pr.get("headRefName", "")
    title = pr.get("title", "")
    return bool(DOC_BRANCH_RE.search(branch) or DOC_TITLE_RE.search(title))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    prs = fetch_prs()
    doc_prs = [p for p in prs if is_doc_pr(p)]

    # Sort: APPROVED first, then by number ascending
    order = {"APPROVED": 0, "REVIEW_REQUIRED": 1, "CHANGES_REQUESTED": 2}
    doc_prs.sort(key=lambda p: (order.get(p["reviewDecision"], 9), p["number"]))

    if mode == "approved-only":
        doc_prs = [p for p in doc_prs if p["reviewDecision"] == "APPROVED"]

    print(json.dumps(doc_prs, indent=2))


if __name__ == "__main__":
    main()
