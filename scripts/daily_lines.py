#!/usr/bin/env python3
"""
Daily Lines Counter - counts real lines added by user, excluding workflow commits.
"""

import os
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"
DAYS = 14
MAX_REPOS = 20

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
    print("Using GH_TOKEN for authentication.")
else:
    print("Warning: No GH_TOKEN. Rate limits will be low.")

SKIP_MESSAGES = [
    "update daily lines stats",
    "update stats",
    "update readme",
]

def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                remaining = r.headers.get("X-RateLimit-Remaining", "?")
                data = json.loads(r.read())
                return data
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"Rate limit or forbidden. Waiting 15s... (attempt {attempt+1}/3)")
                time.sleep(15)
                continue
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
    print(f"Found {len(repos[:MAX_REPOS])} repos (limited to {MAX_REPOS} most recently updated)")
    return repos[:MAX_REPOS]

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
        # Skip workflow/bot commits
        msg = c.get("commit", {}).get("message", "")
        if should_skip_commit(msg):
            continue
        
        sha = c["sha"]
        detail = api(f"https://api.github.com/repos/{repo_full_name}/commits/{sha}")
        if detail and "stats" in detail:
            additions = detail["stats"].get("additions", 0)
            if additions > 0:
                print(f"  {USER} on {since_date}: +{additions} in {repo_full_name} ({msg[:40]})")
            total_add += additions
    
    return total_add

def generate_svg(data):
    w = 1000
    bar_h = 22
    gap = 6
    pad_left = 70
    pad_right = 60
    pad_top = 40
    h = pad_top + len(data) * (bar_h + gap) + 20
    
    max_val = max((v for _, v in data), default=0)
    max_scale = max_val if max_val > 0 else 1
    bar_area = w - pad_left - pad_right
    
    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    lines.append(f'<rect width="{w}" height="{h}" rx="12" fill="#0d1117"/>')
    lines.append(f'<text x="{w//2}" y="24" text-anchor="middle" fill="#8b949e" font-family="monospace" font-size="13">Daily Lines Added (last {DAYS} days)</text>')
    
    for i, (label, val) in enumerate(data):
        y = pad_top + i * (bar_h + gap)
        bw = int((val / max_scale) * bar_area) if val > 0 else 0
        ratio = val / max_scale if max_scale > 0 else 0
        
        if ratio > 0.75:
            color = "#39d353"
        elif ratio > 0.5:
            color = "#26a641"
        elif ratio > 0.25:
            color = "#006d32"
        elif val > 0:
            color = "#0e4429"
        else:
            color = "#161b22"
        
        lines.append(f'<text x="{pad_left - 8}" y="{y + bar_h - 6}" text-anchor="end" fill="#8b949e" font-family="monospace" font-size="12">{label}</text>')
        lines.append(f'<rect x="{pad_left}" y="{y}" width="{bar_area}" height="{bar_h}" rx="4" fill="#161b22"/>')
        if bw > 0:
            lines.append(f'<rect x="{pad_left}" y="{y}" width="{bw}" height="{bar_h}" rx="4" fill="{color}"/>')
        lines.append(f'<text x="{pad_left + bar_area + 8}" y="{y + bar_h - 6}" fill="#58a6ff" font-family="monospace" font-size="12">{val:,}</text>')
    
    lines.append("</svg>")
    return "\n".join(lines)

def update_readme(svg_content):
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        return
    with open(readme_path, "r") as f:
        content = f.read()
    
    import re
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
    print(f"Fetching repos for {USER}...")
    repos = get_repos()
    repo_list = [r["full_name"] for r in repos]
    
    today = datetime.utcnow().date()
    daily_stats = {}
    for d in range(DAYS):
        date = today - timedelta(days=d)
        daily_stats[date.strftime("%Y-%m-%d")] = 0

    for repo in repo_list:
        dates = list(daily_stats.keys())
        for date_str in dates:
            next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            adds = get_daily_additions(repo, date_str, next_day)
            daily_stats[date_str] += adds
    
    sorted_dates = sorted(daily_stats.keys())
    data = []
    for date_str in sorted_dates:
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
        data.append((label, daily_stats[date_str]))
        print(f"{label}: {daily_stats[date_str]:,} lines total")
    
    svg = generate_svg(data)
    os.makedirs("img", exist_ok=True)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)
    
    update_readme(svg)
    print("Done!")

if __name__ == "__main__":
    main()
