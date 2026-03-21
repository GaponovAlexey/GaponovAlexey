#!/usr/bin/env python3
"""
BACKFILL — run once locally to scan all commits for the past 365 days.
Usage:
  GH_TOKEN=your_token python backfill.py

After it finishes:
  git add img/
  git commit -m "Backfill stats"
  git push origin main
"""

import os
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from collections import defaultdict

TOKEN = os.environ.get("GH_TOKEN", "")
USER  = "GaponovAlexey"
DAYS  = 365
MAX_REPOS = 50

AUTHOR_NAMES = {"gaponovalexey", "alexey", "alexey gaponov", "gaponov alexey"}

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
else:
    print("ERROR: GH_TOKEN not set. Run: GH_TOKEN=your_token python backfill.py")
    exit(1)

SKIP_MESSAGES = [
    "update daily lines stats", "update stats", "update readme",
    "auto update", "ci: update", "github actions",
]

CACHE_PATH = "img/daily_lines_cache.json"


def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  rate limit, waiting 30s... ({attempt+1}/3)")
                time.sleep(30)
                continue
            if e.code in (404, 409, 422):
                return None
            print(f"  HTTP {e.code}: {url}")
            return None
        except Exception as ex:
            print(f"  err: {ex}")
            return None
    return None


def get_repos():
    repos = []
    d = api("https://api.github.com/user/repos?affiliation=owner&sort=pushed&direction=desc&per_page=100")
    if d:
        repos = [r for r in d if not r.get("fork")]
    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    return repos[:MAX_REPOS]


def is_mine(commit):
    a = commit.get("author")
    if a and isinstance(a, dict) and a.get("login", "").lower() == USER.lower():
        return True
    name = commit.get("commit", {}).get("author", {}).get("name", "").lower()
    return name in AUTHOR_NAMES


def skip_msg(msg):
    return any(s in (msg or "").lower() for s in SKIP_MESSAGES)


def main():
    print(f"=== BACKFILL: scanning {DAYS} days for {USER} ===\n")

    repos = get_repos()
    print(f"Found {len(repos)} repos\n")

    today  = datetime.utcnow().date()
    cutoff = (today - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    stats  = defaultdict(int)
    names_seen = set()

    for repo in repos:
        rname  = repo["full_name"]
        pushed = (repo.get("pushed_at") or "")[:10]


        print(f"→ {rname}  (last push: {pushed})")

        commits = api(
            f"https://api.github.com/repos/{rname}/commits"
            f"?since={cutoff}T00:00:00Z&per_page=100"
        )
        if not commits or not isinstance(commits, list):
            print("  no commits")
            continue

        for c in commits:
            name  = c.get("commit", {}).get("author", {}).get("name", "")
            login = (c.get("author") or {}).get("login", "")
            names_seen.add(f"{name!r}  login={login!r}")

            if not is_mine(c):
                continue
            msg = c.get("commit", {}).get("message", "")
            if skip_msg(msg):
                continue

            date_str = c["commit"]["author"]["date"][:10]
            sha      = c["sha"]
            detail   = api(f"https://api.github.com/repos/{rname}/commits/{sha}")
            if detail and "stats" in detail:
                adds = detail["stats"].get("additions", 0)
                if adds:
                    short = msg.split("\n")[0][:45]
                    print(f"  {date_str}  +{adds:>6,}  {short}")
                stats[date_str] += adds

    print("\n=== All author names found in your repos ===")
    for n in sorted(names_seen):
        mine = "✓ MINE" if any(
            p in n.lower() for p in list(AUTHOR_NAMES) + [USER.lower()]
        ) else ""
        print(f"  {n}  {mine}")

    print(f"\n=== Results: {len([v for v in stats.values() if v])} active days ===")
    for d in sorted(stats):
        if stats[d]:
            bar = "▓" * min(50, stats[d] // 20)
            print(f"  {d}  {stats[d]:>7,}  {bar}")

    os.makedirs("img", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(dict(stats), f, indent=2, sort_keys=True)

    print(f"\nSaved to {CACHE_PATH}")
    print("Now run:")
    print("  git add img/")
    print('  git commit -m "Backfill stats"')
    print("  git push origin main")


if __name__ == "__main__":
    main()
