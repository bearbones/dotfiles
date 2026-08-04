#!/usr/bin/env python3
"""
pr_dash.py — a fast, complete replacement for the org PR Dashboard.

The org dashboard is slow (per-PR round-trips), greyboxes on refocus, and
silently drops PRs when you have many open. This fetches the *entire* set in
two `gh pr list --limit 9999` calls (each auto-paginates and returns
reviewDecision, review requests incl. CODEOWNERS teams, latest reviews,
comments, and the full status-check rollup), caches the result, and renders
categorized tables instantly from cache.

Subcommands:
  show     (default) render tables from cache; auto-refreshes if stale (>TTL)
  refresh            force a fetch and rewrite the cache
  drill N            detail one PR: every non-green check + the gated-commits
                     integrator's TeamCity build id/url (the real merge gate)
  watch              refresh on a loop (the "daemon" — run in a tmux window)

Buckets (from the memory spec):
  review    — assigned to me to review
  waiting   — my open PRs waiting on reviewers / CODEOWNERS groups
  comments  — my PRs with reviewer comments / changes-requested (maybe unaddressed)
  approved  — my fully-approved PRs

Config (env):
  GH_HOST   default github.rbx.com
  PRD_REPO  default GameEngine/game-engine
  PRD_ME    default amason
  PRD_TTL   cache freshness seconds for `show` (default 300)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

GH_HOST = os.environ.get("GH_HOST", "github.rbx.com")
REPO    = os.environ.get("PRD_REPO", "GameEngine/game-engine")
ME      = os.environ.get("PRD_ME", "amason")
TTL     = int(os.environ.get("PRD_TTL", "300"))
CACHE   = os.path.expanduser("~/.cache/ge/pr_dash.json")

# Bot accounts whose reviews/comments never mean "the human wants changes".
BOTS = {"aladavac", "gedevops-build", "github-actions[bot]"}

# Fields for the per-PR drill path (`gh pr view --json`), which is cheap at N=1.
FIELDS = ("number,title,url,isDraft,headRefName,reviewDecision,updatedAt,"
          "reviewRequests,latestReviews,comments,statusCheckRollup")

# Bulk fetch uses paginated GraphQL instead of `gh pr list --json
# statusCheckRollup`: requesting the full rollup for all ~200 PRs in one shot
# 502s the enterprise gateway. first:40 with contexts(first:40) is well under
# the limit and pages the whole set in a handful of requests.
PAGE = 40
NODE = """
      ... on PullRequest {
        number title url isDraft headRefName reviewDecision updatedAt
        reviewRequests(first: 25) { nodes { requestedReviewer {
          __typename ... on Team { name slug } ... on User { login } } } }
        latestReviews(first: 25) { nodes { author { login } state } }
        comments(first: 30) { totalCount nodes { author { login } } }
        commits(last: 1) { nodes { commit { statusCheckRollup { state
          contexts(first: 40) { nodes {
            __typename
            ... on CheckRun { name conclusion status detailsUrl }
            ... on StatusContext { context state targetUrl } } } } } } }
      }"""

# A failing "Branch Freshness"/"needs-rebase" check means "merge master", not a
# broken build — surfaced as a stale flag, not a hard CI failure.
FRESHNESS_RE = re.compile(r"freshness|needs.?rebase|update.?branch|up.?to.?date|out.?of.?date", re.I)
# The gated-commits integrator: the TeamCity status context that actually gates
# merge. Its targetUrl ends in the TeamCity build id.
INTEGRATOR_RE = re.compile(r"integrator|gated.?commit", re.I)


# ------------------------------------------------------------------ fetching
def gh(*args):
    """Run gh against the enterprise host; return parsed JSON (or [])."""
    env = {**os.environ, "GH_HOST": GH_HOST}
    r = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else []


def gh_graphql(query, variables):
    """Run a GraphQL query via gh, retrying transient 5xx gateway errors."""
    env = {**os.environ, "GH_HOST": GH_HOST}
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is not None:
            cmd += ["-f", f"{k}={v}"]  # -f = raw string (don't type-coerce the query)
    last = None
    for attempt in range(4):
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode == 0:
            return json.loads(r.stdout)
        last = r.stderr.strip()
        if not re.search(r"HTTP 5\d\d|Bad Gateway|timeout", last):
            raise RuntimeError(f"graphql: {last}")
        time.sleep(2 ** attempt)  # 1,2,4s backoff on transient gateway errors
    raise RuntimeError(f"graphql (after retries): {last}")


def _flatten(node):
    """Normalize a GraphQL PR node into the flat shape the analysis code wants."""
    rr = []
    for n in (node.get("reviewRequests") or {}).get("nodes") or []:
        r = n.get("requestedReviewer") or {}
        rr.append(r)
    commits = (node.get("commits") or {}).get("nodes") or []
    rollup = (commits[0]["commit"].get("statusCheckRollup") if commits else None) or {}
    contexts = (rollup.get("contexts") or {}).get("nodes") or []
    comments = node.get("comments") or {}
    return {
        "number": node.get("number"), "title": node.get("title", ""),
        "url": node.get("url", ""), "isDraft": node.get("isDraft", False),
        "headRefName": node.get("headRefName", ""),
        "reviewDecision": node.get("reviewDecision"),
        "updatedAt": node.get("updatedAt"),
        "reviewRequests": rr,
        "latestReviews": (node.get("latestReviews") or {}).get("nodes") or [],
        "comments": comments.get("nodes") or [],
        "statusCheckRollup": contexts,
    }


def fetch_search(search):
    """Page a search query (first:PAGE, after cursor) into a flat PR list."""
    query = ("query($q: String!, $after: String) { search(query: $q, type: ISSUE,"
             f" first: {PAGE}, after: $after) {{ pageInfo {{ hasNextPage endCursor }}"
             f" nodes {{ {NODE} }} }} }}")
    out, cursor = [], None
    while True:
        data = gh_graphql(query, {"q": search, "after": cursor})
        s = data["data"]["search"]
        out += [_flatten(n) for n in s["nodes"] if n]
        if not s["pageInfo"]["hasNextPage"]:
            return out
        cursor = s["pageInfo"]["endCursor"]


def fetch():
    """Fetch authored + review-requested PRs via paginated GraphQL search."""
    base = f"repo:{REPO} is:pr is:open"
    authored = fetch_search(f"{base} author:{ME}")
    review = fetch_search(f"{base} review-requested:{ME}")
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "gh_host": GH_HOST, "repo": REPO, "me": ME,
        "authored": authored, "review": review,
    }


def save(data):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(data, f)


def load():
    with open(CACHE) as f:
        return json.load(f)


def cache_age():
    """Seconds since the cache was fetched, or None if there is no cache."""
    try:
        fetched = datetime.fromisoformat(load()["fetched_at"])
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return (datetime.now(timezone.utc) - fetched).total_seconds()


# ------------------------------------------------------------------ analysis
def tc_build_id(url):
    """Extract the trailing TeamCity build id from an integrator targetUrl."""
    m = re.search(r"/(\d+)/?$", url or "")
    return m.group(1) if m else None


def analyze_checks(pr):
    """Reduce statusCheckRollup into failing/pending lists + special flags.

    Returns a dict: {failing, pending, stale, integrator} where failing/pending
    are lists of {name, url}, stale is bool (freshness check red), and
    integrator is {name, url, build_id, state} for the gated-commits gate if
    it is not green (else None)."""
    failing, pending = [], []
    stale = False
    integrator = None  # the TeamCity StatusContext that actually gates merge
    for c in pr.get("statusCheckRollup") or []:
        typ = c.get("__typename")
        if typ == "CheckRun":
            name = c.get("name", "?")
            url = c.get("detailsUrl", "")
            concl, status = c.get("conclusion"), c.get("status")
            if concl in ("FAILURE", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"):
                result = "fail"
            elif concl == "SUCCESS":
                result = "pass"
            elif concl in ("SKIPPED", "NEUTRAL"):
                result = "skip"
            elif status and status != "COMPLETED":
                result = "pending"
            else:
                result = "other"
        elif typ == "StatusContext":
            name = c.get("context", "?")
            url = c.get("targetUrl", "")
            state = c.get("state")
            result = {"SUCCESS": "pass", "FAILURE": "fail", "ERROR": "fail",
                      "PENDING": "pending", "EXPECTED": "pending"}.get(state, "other")
        else:
            continue

        if result == "fail" and FRESHNESS_RE.search(name):
            stale = True
            continue  # not a hard failure — merge-master fixes it
        if result == "fail":
            failing.append({"name": name, "url": url})
        elif result == "pending":
            pending.append({"name": name, "url": url})

        # The merge gate is the TeamCity StatusContext (its targetUrl carries the
        # build id); the identically-named GHA CheckRun is NOT it. Prefer a
        # failing integrator over a pending one, and never let a CheckRun win.
        if typ == "StatusContext" and INTEGRATOR_RE.search(name) and result in ("fail", "pending"):
            if integrator is None or (integrator["state"] != "fail" and result == "fail"):
                integrator = {"name": name, "url": url, "state": result,
                              "build_id": tc_build_id(url)}
    return {"failing": failing, "pending": pending, "stale": stale, "integrator": integrator}


def reviewers_of(pr):
    """Latest review state per human reviewer + outstanding requested groups.

    Returns {approvers, commenters, changes, req_teams, req_users}."""
    approvers, commenters, changes = [], [], []
    for r in pr.get("latestReviews") or []:
        login = (r.get("author") or {}).get("login", "?")
        state = r.get("state")
        if login in BOTS:
            continue  # bot review states are captured by the CI/integrator signals
        if state == "APPROVED":
            approvers.append(login)
        elif state == "CHANGES_REQUESTED":
            changes.append(login)
        elif state == "COMMENTED":
            commenters.append(login)
    req_teams, req_users = [], []
    for rr in pr.get("reviewRequests") or []:
        if rr.get("__typename") == "Team":
            # slug is "GameEngine/test-tools"; the bare name is what people say.
            req_teams.append(rr.get("name") or rr.get("slug", "?").split("/")[-1])
        else:
            req_users.append(rr.get("login", "?"))
    return {"approvers": approvers, "commenters": commenters, "changes": changes,
            "req_teams": req_teams, "req_users": req_users}


def human_comment_count(pr):
    """Top-level PR conversation comments, excluding bots."""
    n = 0
    for c in pr.get("comments") or []:
        if (c.get("author") or {}).get("login") not in BOTS:
            n += 1
    return n


def enrich(pr):
    """Attach derived checks/reviewers/flags used by rendering + bucketing."""
    checks = analyze_checks(pr)
    rev = reviewers_of(pr)
    pr["_checks"] = checks
    pr["_rev"] = rev
    pr["_ci_red"] = len(checks["failing"]) > 0
    pr["_comment_n"] = human_comment_count(pr)
    return pr


def bucket_authored(pr):
    """Assign one of: approved | comments | waiting."""
    decision = pr.get("reviewDecision")
    rev = pr["_rev"]
    if decision == "APPROVED":
        return "approved"
    if decision == "CHANGES_REQUESTED" or rev["changes"]:
        return "comments"
    if rev["commenters"] or pr["_comment_n"] > 0:
        return "comments"
    return "waiting"


# ------------------------------------------------------------------ rendering
class C:
    """ANSI palette (gruvbox-ish); neutered when color is disabled."""
    enabled = True
    def __getattr__(self, name):
        codes = {"red": "31", "grn": "32", "yel": "33", "blu": "34",
                 "mag": "35", "cyn": "36", "gry": "90", "bold": "1", "dim": "2"}
        if not self.enabled or name not in codes:
            return lambda s: s
        return lambda s: f"\033[{codes[name]}m{s}\033[0m"
c = C()


def term_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def ci_cell(pr):
    """Compact CI status glyph: ✓ green / ✗N red / ● pending / ~ stale."""
    ck = pr["_checks"]
    if ck["failing"]:
        return c.red(f"✗{len(ck['failing'])}")
    if ck["pending"]:
        return c.yel("●")
    if ck["stale"]:
        return c.yel("~")
    return c.grn("✓")


def trunc(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


_ANSI = re.compile(r"\033\[[0-9;]*m")
def vis(s):
    """Visible width of a string, ignoring ANSI color codes."""
    return len(_ANSI.sub("", s))


def pad(s, n):
    """Left-justify to n visible columns (color-code aware)."""
    return s + " " * max(0, n - vis(s))


# Title gets a stable column so identity is always readable; the annotation
# tail (groups/reviewers/integrator) follows and may wrap on very busy PRs —
# preferable to truncating either the title or the actionable reviewer info.
def title_width():
    return max(28, min(52, term_width() - 55))


def render_row(pr, tail):
    """`  #NNNNN  <ci>  Title…             <tail>` — title in a fixed column."""
    num = pad(c.cyn(f"#{pr['number']}"), 7)
    ci = pad(ci_cell(pr), 4)
    draft = c.gry("(draft) ") if pr.get("isDraft") else ""
    tw = title_width()
    title = pad(trunc(pr.get("title", ""), tw), tw)
    return f"  {num} {ci} {title}  {draft}{tail}"


def _cap(items, n):
    """Join up to n names, appending '+K' when the list is longer."""
    if len(items) <= n:
        return ", ".join(items)
    return ", ".join(items[:n]) + f" +{len(items) - n}"


def group_tail(rev, checks, decision):
    """The right-hand annotation: outstanding groups, reviewer states, integrator."""
    bits = []
    if rev["req_teams"]:
        bits.append(c.yel("⦿ " + _cap(rev["req_teams"], 6)))  # ⦿ = CODEOWNERS groups
    if rev["req_users"]:
        bits.append(c.dim("@" + _cap(rev["req_users"], 6).replace(", ", ", @")))
    if rev["changes"]:
        bits.append(c.red("⟲ changes: " + _cap(rev["changes"], 4)))
    if rev["commenters"]:
        bits.append(c.mag("\U0001f4ac " + _cap(rev["commenters"], 4)))
    if rev["approvers"]:
        bits.append(c.grn("✔ " + _cap(rev["approvers"], 6)))
    integ = checks["integrator"]
    if integ and integ["state"] == "fail":
        bid = integ["build_id"]
        bits.append(c.red(f"[integrator ✗ tc:{bid}]" if bid else "[integrator ✗]"))
    return "  ".join(bits)


def section(title, prs, color):
    print(color(f"▌ {title} ({len(prs)})"))
    if not prs:
        print(c.dim("    — none —"))
        return
    for pr in prs:
        tail = group_tail(pr["_rev"], pr["_checks"], pr.get("reviewDecision"))
        print(render_row(pr, tail))
    print()


def render(data, which, only_failing):
    authored = [enrich(p) for p in data.get("authored", [])]
    review = [enrich(p) for p in data.get("review", [])]
    if only_failing:
        authored = [p for p in authored if p["_ci_red"]]

    buckets = {"waiting": [], "comments": [], "approved": []}
    for pr in authored:
        buckets[bucket_authored(pr)].append(pr)
    for v in buckets.values():
        v.sort(key=lambda p: p["number"], reverse=True)
    review.sort(key=lambda p: p["number"], reverse=True)

    age = cache_age()
    stamp = f"cached {int(age)}s ago" if age is not None else "live"
    hdr = f"PR Dashboard — {ME}@{REPO}  ({stamp})"
    print(c.bold(hdr))
    print(c.dim("─" * min(len(hdr), term_width())))

    show_review = which in ("all", "review")
    show_mine = which in ("all", "mine")
    if show_review:
        section("Assigned to me to review", review, c.blu)
    if show_mine or only_failing:
        section("Waiting for reviewers", buckets["waiting"], c.yel)
        section("Comments / changes (maybe unaddressed)", buckets["comments"], c.mag)
        section("Approved", buckets["approved"], c.grn)

    tot = len(review) + sum(len(v) for v in buckets.values())
    red = sum(1 for p in authored if p["_ci_red"])
    print(c.dim(f"{tot} PRs · {len(review)} to review · "
                f"{len(buckets['waiting'])} waiting · "
                f"{len(buckets['comments'])} commented · "
                f"{len(buckets['approved'])} approved · {red} CI-red"))


# ------------------------------------------------------------------ drill
def find_pr(data, num):
    for key in ("authored", "review"):
        for pr in data.get(key, []):
            if pr.get("number") == num:
                return pr
    return None


def drill(num, want_logs):
    """Detail one PR's failing/pending checks + the integrator TeamCity build."""
    data = load()
    pr = find_pr(data, num)
    if pr is None:  # not in cache (e.g. someone else's PR) — fetch just this one
        pr = gh("pr", "view", str(num), "--repo", REPO, "--json", FIELDS)
    enrich(pr)
    ck = pr["_checks"]
    print(c.bold(f"#{pr['number']}  {pr.get('title','')}"))
    print(c.dim(pr.get("url", "")))
    print(f"  decision: {pr.get('reviewDecision')}   CI: "
          f"{len(ck['failing'])} failing, {len(ck['pending'])} pending"
          + (c.yel("  ~stale") if ck["stale"] else ""))
    print()

    integ = ck["integrator"]
    if integ:
        tag = c.red("FAIL") if integ["state"] == "fail" else c.yel("PENDING")
        print(c.bold("Gated-commits integrator: ") + tag)
        print(f"  {integ['name']}")
        print(f"  {c.cyn(integ['url'])}")
        if integ["build_id"]:
            print(c.dim(f"  TeamCity build {integ['build_id']} — deep-dive with the "
                        f"`teamcity` skill / MCP get_build({integ['build_id']})"))
        print()

    if ck["failing"]:
        print(c.red(f"Failing checks ({len(ck['failing'])}):"))
        for f in ck["failing"]:
            print(f"  ✗ {f['name']}")
            print(c.dim(f"      {f['url']}"))
    if ck["pending"]:
        print(c.yel(f"Pending checks ({len(ck['pending'])}):"))
        for f in ck["pending"]:
            print(f"  ● {f['name']}")

    if want_logs and ck["failing"]:
        print()
        print(c.bold("Failed GHA logs (truncated):"))
        for f in ck["failing"]:
            m = re.search(r"/runs/(\d+)", f["url"])
            if not m:
                continue  # non-GHA (e.g. TeamCity) — use the integrator build id above
            run_id = m.group(1)
            print(c.dim(f"  --- {f['name']} (run {run_id}) ---"))
            r = subprocess.run(
                ["gh", "run", "view", run_id, "--log-failed", "--repo", REPO],
                capture_output=True, text=True, env={**os.environ, "GH_HOST": GH_HOST})
            for line in (r.stdout or r.stderr).splitlines()[:40]:
                print("    " + line)


# ------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser(description="Fast PR dashboard for game-engine.")
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--no-color", action="store_true")
        sp.add_argument("--json", action="store_true", help="dump raw cache JSON")

    sp_show = sub.add_parser("show", help="render tables (default)")
    sp_show.add_argument("--review", action="store_const", const="review", dest="which")
    sp_show.add_argument("--mine", action="store_const", const="mine", dest="which")
    sp_show.add_argument("--failing", action="store_true", help="only CI-red authored PRs")
    sp_show.add_argument("--refresh", action="store_true", help="force refresh first")
    sp_show.add_argument("--cached", action="store_true", help="never auto-refresh")
    add_common(sp_show)

    sub.add_parser("refresh", help="force a fetch + rewrite cache")

    sp_drill = sub.add_parser("drill", help="detail one PR")
    sp_drill.add_argument("number", type=int)
    sp_drill.add_argument("--logs", action="store_true", help="pull failing GHA logs")
    sp_drill.add_argument("--no-color", action="store_true")

    sp_watch = sub.add_parser("watch", help="refresh on a loop (daemon)")
    sp_watch.add_argument("--interval", type=int, default=300)

    args = p.parse_args()
    cmd = args.cmd or "show"
    if getattr(args, "no_color", False) or os.environ.get("NO_COLOR"):
        C.enabled = False
    if not sys.stdout.isatty():
        C.enabled = False

    if cmd == "refresh":
        print("Fetching...", file=sys.stderr)
        save(fetch())
        print(f"Cached {CACHE}")
        return

    if cmd == "watch":
        while True:
            try:
                save(fetch())
                print(f"[{datetime.now().strftime('%H:%M:%S')}] refreshed", file=sys.stderr)
            except Exception as e:  # a transient gh/network error shouldn't kill the loop
                print(f"[{datetime.now().strftime('%H:%M:%S')}] refresh failed: {e}", file=sys.stderr)
            time.sleep(args.interval)

    if cmd == "drill":
        drill(args.number, args.logs)
        return

    # show
    age = cache_age()
    need = args.refresh or age is None or (age > TTL and not args.cached)
    if need:
        print("Refreshing cache...", file=sys.stderr)
        save(fetch())
    data = load()
    if args.json:
        print(json.dumps(data, indent=2))
        return
    render(data, args.which or "all", args.failing)


if __name__ == "__main__":
    main()
