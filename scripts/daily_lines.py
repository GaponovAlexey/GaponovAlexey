#!/usr/bin/env python3
"""
Daily Lines Counter
Usage:
  python daily_lines.py             # daily mode: last 14 days
  python daily_lines.py --backfill  # backfill mode: last 90 days
"""

import os
import re
import sys
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"
# Match commits by these author names (add your local git name if different)
AUTHOR_NAMES = {"gaponovalexey", "alexey", "alexey gaponov"}
DAYS = 90 if "--backfill" in sys.argv else 14
MAX_REPOS = 30

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
    print("Using GH_TOKEN for authentication.")
else:
    print("Warning: No GH_TOKEN. Rate limits will be very low.")

SKIP_MESSAGES = [
    "update daily lines stats",
    "update stats",
    "update readme",
    "auto update",
    "ci: update",
    "github actions",
]


def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  Rate limit. Waiting 20s... ({attempt+1}/3)")
                time.sleep(20)
                continue
            if e.code in (404, 409):
                return None
            print(f"  HTTP {e.code}: {url}")
            return None
        except Exception as ex:
            print(f"  Error: {ex}")
            return None
    return None


def get_repos():
    repos = []
    if TOKEN:
        data = api("https://api.github.com/user/repos?affiliation=owner&sort=pushed&direction=desc&per_page=100")
        if data:
            repos = [r for r in data if not r.get("fork")]
    if not repos:
        data = api(f"https://api.github.com/users/{USER}/repos?type=owner&sort=pushed&direction=desc&per_page=100")
        if data:
            repos = [r for r in data if not r.get("fork")]
    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    result = repos[:MAX_REPOS]
    print(f"Found {len(result)} repos")
    return result


def is_my_commit(commit):
    """Check if commit belongs to me by GitHub login or author name."""
    # Check GitHub login association
    author_obj = commit.get("author")
    if author_obj and isinstance(author_obj, dict):
        login = author_obj.get("login", "").lower()
        if login == USER.lower():
            return True

    # Check commit author name
    commit_data = commit.get("commit", {})
    author_name = commit_data.get("author", {}).get("name", "").lower()
    if author_name in AUTHOR_NAMES:
        return True

    return False


def should_skip(message):
    if not message:
        return False
    m = message.lower().strip()
    return any(s in m for s in SKIP_MESSAGES)


def get_repo_additions(repo_full_name, since_str, until_str):
    """Get total lines added by me in a repo between since and until."""
    url = (
        f"https://api.github.com/repos/{repo_full_name}/commits"
        f"?since={since_str}&until={until_str}&per_page=100"
    )
    commits = api(url)
    if not commits or not isinstance(commits, list):
        return 0

    total = 0
    for c in commits:
        if not is_my_commit(c):
            continue
        msg = c.get("commit", {}).get("message", "")
        if should_skip(msg):
            continue
        sha = c["sha"]
        detail = api(f"https://api.github.com/repos/{repo_full_name}/commits/{sha}")
        if detail and "stats" in detail:
            additions = detail["stats"].get("additions", 0)
            if additions > 0:
                short = msg.split("\n")[0][:40]
                print(f"    +{additions} [{short}]")
            total += additions
    return total


def generate_svg(data):
    w = 680
    bar_h = 4
    gap = 16
    pad_left = 52
    pad_right = 44
    pad_top = 28
    h = pad_top + len(data) * (bar_h + gap) + 12

    max_val = max((v for _, v in data), default=0)
    max_scale = max_val if max_val > 0 else 1
    bar_area = w - pad_left - pad_right

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {w} {h}">')

    for i, (label, val) in enumerate(data):
        y = pad_top + i * (bar_h + gap)
        mid = y + bar_h / 2

        bw = int((val / max_scale) * bar_area) if val > 0 else 0

        if val == 0:
            fill = "#1c2128"
            num_fill = "none"
        elif val / max_scale > 0.6:
            fill = "#3fb950"
            num_fill = "#3fb950"
        elif val / max_scale > 0.2:
            fill = "#238636"
            num_fill = "#238636"
        else:
            fill = "#1a7f37"
            num_fill = "#6e7681"

        # date label
        out.append(
            f'<text x="{pad_left - 6}" y="{mid + 4}" '
            f'font-family="monospace" font-size="9" '
            f'fill="#484f58" text-anchor="end">{label}</text>'
        )
        # track
        out.append(
            f'<rect x="{pad_left}" y="{mid - 1}" '
            f'width="{bar_area}" height="2" fill="#1c2128"/>'
        )
        # bar
        if bw > 0:
            out.append(
                f'<rect x="{pad_left}" y="{y}" '
                f'width="{bw}" height="{bar_h}" rx="1" fill="{fill}"/>'
            )
        # value
        if val > 0 and num_fill != "none":
            out.append(
                f'<text x="{pad_left + bar_area + 5}" y="{mid + 4}" '
                f'font-family="monospace" font-size="9" '
                f'fill="{num_fill}" text-anchor="start">{val:,}</text>'
            )

    out.append("</svg>")
    return "\n".join(out)


def update_readme():
    path = "README.md"
    if not os.path.exists(path):
        return
    with open(path) as f:
        content = f.read()
    s = "<!-- DAILY_LINES_START -->"
    e = "<!-- DAILY_LINES_END -->"
    img = '<img src="img/daily_lines.svg" alt="Daily Lines Added" width="100%">'
    block = f"{s}\n{img}\n{e}"
    if s in content:
        content = re.sub(
            f"{re.escape(s)}.*?{re.escape(e)}", block, content, flags=re.DOTALL
        )
    else:
        content += f"\n\n{block}\n"
    with open(path, "w") as f:
        f.write(content)


def main():
    backfill = "--backfill" in sys.argv
    print(f"Mode: {'BACKFILL 90 days' if backfill else 'DAILY 14 days'}")

    repos = get_repos()
    today = datetime.utcnow().date()

    daily_stats = {}
    for d in range(DAYS):
        date = today - timedelta(days=d)
        daily_stats[date.strftime("%Y-%m-%d")] = 0

    for repo in repos:
        rname = repo["full_name"]
        pushed = repo.get("pushed_at", "")
        print(f"\n→ {rname}  (pushed {pushed[:10]})")
        for date_str in list(daily_stats.keys()):
            next_day = (
                datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            since = f"{date_str}T00:00:00Z"
            until = f"{next_day}T00:00:00Z"
            # Skip repo if it was last pushed before this date
            if pushed and pushed[:10] < date_str:
                continue
            adds = get_repo_additions(rname, since, until)
            if adds:
                print(f"  {date_str}: +{adds}")
            daily_stats[date_str] += adds

    sorted_dates = sorted(daily_stats.keys())
    display_dates = sorted_dates[-14:]

    print("\n--- Summary ---")
    for d in sorted_dates:
        label = datetime.strptime(d, "%Y-%m-%d").strftime("%b %d")
        v = daily_stats[d]
        bar = "█" * min(40, v // 10) if v else ""
        print(f"{label}: {v:>6,}  {bar}")

    data = [
        (datetime.strptime(d, "%Y-%m-%d").strftime("%b %d"), daily_stats[d])
        for d in display_dates
    ]

    svg = generate_svg(data)
    os.makedirs("img", exist_ok=True)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)

    update_readme()
    print("\nDone! img/daily_lines.svg updated.")


if __name__ == "__main__":
    main()
