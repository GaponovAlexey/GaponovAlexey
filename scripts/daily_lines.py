#!/usr/bin/env python3
"""
Daily Lines Counter - counts real lines added by user, excluding workflow commits.
Usage:
  python daily_lines.py           # last 14 days
  python daily_lines.py --backfill  # last 90 days (first run)
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
]


def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"Rate limit hit. Waiting 20s... (attempt {attempt+1}/3)")
                time.sleep(20)
                continue
            if e.code == 404:
                return None
            print(f"HTTP {e.code} for {url}")
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None
    return None


def get_repos():
    repos = []
    if TOKEN:
        url = "https://api.github.com/user/repos?affiliation=owner&sort=pushed&direction=desc&per_page=100"
        data = api(url)
        if data:
            repos = [r for r in data if not r.get("fork")]

    if not repos:
        url = f"https://api.github.com/users/{USER}/repos?type=owner&sort=pushed&direction=desc&per_page=100"
        data = api(url)
        if data:
            repos = [r for r in data if not r.get("fork")]

    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    result = repos[:MAX_REPOS]
    print(f"Found {len(result)} repos (limited to {MAX_REPOS} most recently updated)")
    return result


def should_skip_commit(message):
    if not message:
        return False
    msg_lower = message.lower().strip()
    return any(skip in msg_lower for skip in SKIP_MESSAGES)


def get_daily_additions(repo_full_name, since_date, until_date):
    since = f"{since_date}T00:00:00Z"
    until = f"{until_date}T00:00:00Z"

    commits_url = (
        f"https://api.github.com/repos/{repo_full_name}/commits"
        f"?author={USER}&since={since}&until={until}&per_page=100"
    )
    commits = api(commits_url)

    if not commits or not isinstance(commits, list):
        return 0

    total_add = 0
    for c in commits:
        msg = c.get("commit", {}).get("message", "")
        if should_skip_commit(msg):
            continue

        sha = c["sha"]
        detail = api(f"https://api.github.com/repos/{repo_full_name}/commits/{sha}")
        if detail and "stats" in detail:
            additions = detail["stats"].get("additions", 0)
            if additions > 0:
                short_msg = msg.split("\n")[0][:50]
                print(f"  +{additions} in {repo_full_name} — {short_msg}")
            total_add += additions

    return total_add


def generate_svg(data):
    w = 680
    bar_h = 14
    gap = 9
    pad_left = 80
    pad_right = 60
    pad_top = 44
    h = pad_top + len(data) * (bar_h + gap) + 20

    max_val = max((v for _, v in data), default=0)
    max_scale = max_val if max_val > 0 else 1
    bar_area = w - pad_left - pad_right

    period = f"LAST {DAYS} DAYS"

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {w} {h}">')
    lines.append(f'<rect width="{w}" height="{h}" fill="#0d1117"/>')
    lines.append(
        f'<text x="{pad_left}" y="22" font-family="monospace" font-size="11" '
        f'fill="#484f58" letter-spacing="0.08em">DAILY LINES ADDED · {period}</text>'
    )

    for i, (label, val) in enumerate(data):
        y = pad_top + i * (bar_h + gap)
        cy = y + bar_h // 2 + 4

        bw = int((val / max_scale) * bar_area) if val > 0 else 0

        if val == 0:
            bar_color = "#161b22"
            num_color = "#30363d"
        elif val / max_scale > 0.5:
            bar_color = "#39d353"
            num_color = "#39d353"
        elif val / max_scale > 0.15:
            bar_color = "#26a641"
            num_color = "#26a641"
        else:
            bar_color = "#0e4429"
            num_color = "#484f58"

        lines.append(
            f'<text x="{pad_left - 8}" y="{cy}" font-family="monospace" font-size="11" '
            f'fill="#484f58" text-anchor="end">{label}</text>'
        )
        lines.append(
            f'<rect x="{pad_left}" y="{y}" width="{bar_area}" height="{bar_h}" rx="2" fill="#161b22"/>'
        )
        if bw > 0:
            lines.append(
                f'<rect x="{pad_left}" y="{y}" width="{bw}" height="{bar_h}" rx="2" fill="{bar_color}"/>'
            )
        lines.append(
            f'<text x="{pad_left + bar_area + 8}" y="{cy}" font-family="monospace" font-size="11" '
            f'fill="{num_color}" text-anchor="start">{val:,}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def update_readme(svg_content):
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        return

    with open(readme_path, "r") as f:
        content = f.read()

    start_marker = "<!-- DAILY_LINES_START -->"
    end_marker = "<!-- DAILY_LINES_END -->"
    img_tag = '<img src="img/daily_lines.svg" alt="Daily Lines Added" width="100%">'
    block = f"{start_marker}\n{img_tag}\n{end_marker}"

    if start_marker in content:
        content = re.sub(
            f"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
            block,
            content,
            flags=re.DOTALL,
        )
    else:
        content += f"\n\n{block}\n"

    with open(readme_path, "w") as f:
        f.write(content)


def main():
    mode = "BACKFILL (90 days)" if "--backfill" in sys.argv else "DAILY (14 days)"
    print(f"Mode: {mode}")
    print(f"Fetching repos for {USER}...")

    repos = get_repos()
    repo_list = [r["full_name"] for r in repos]

    today = datetime.utcnow().date()
    daily_stats = {}
    for d in range(DAYS):
        date = today - timedelta(days=d)
        daily_stats[date.strftime("%Y-%m-%d")] = 0

    for repo in repo_list:
        print(f"\nChecking {repo}...")
        for date_str in list(daily_stats.keys()):
            next_day = (
                datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            adds = get_daily_additions(repo, date_str, next_day)
            daily_stats[date_str] += adds

    sorted_dates = sorted(daily_stats.keys())

    # For SVG: show only last 14 days even after backfill
    display_dates = sorted_dates[-14:]

    data = []
    for date_str in display_dates:
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
        data.append((label, daily_stats[date_str]))

    print("\n--- Results ---")
    for date_str in sorted_dates:
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
        print(f"{label}: {daily_stats[date_str]:,} lines")

    svg = generate_svg(data)
    os.makedirs("img", exist_ok=True)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)

    update_readme(svg)
    print("\nDone!")


if __name__ == "__main__":
    main()
