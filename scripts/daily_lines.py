#!/usr/bin/env python3
"""
Daily Lines Counter (Final Version) - generates SVG bar chart of daily lines added.
Optimized for GitHub API limits and accurate commit statistics.
"""

import os
import re
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"
DAYS = 14
MAX_REPOS = 30

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
    print("Using provided GH_TOKEN for authentication.")
else:
    print("Warning: No GH_TOKEN found. API rate limits will be very low.")

def api(url):
    """Fetch data from GitHub API with retry logic and error handling."""
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403 and "rate limit" in str(e.reason).lower():
                print(f"Rate limit hit. Waiting 10s... (Attempt {attempt+1}/3)")
                time.sleep(10)
                continue
            print(f"API Error {e.code} for {url}: {e.reason}")
            return None
        except Exception as e:
            print(f"Unexpected error for {url}: {e}")
            return None
    return None

def get_repos():
    """Fetch all repositories owned by the user, sorted by recent activity."""
    repos = []
    # Public repos via user profile
    url = f"https://api.github.com/users/{USER}/repos?type=owner&sort=pushed&direction=desc&per_page=100"
    data = api(url)
    if data:
        repos = [r for r in data if not r.get("fork")]
    
    # If token is present, fetch all repos (including private ones)
    if TOKEN:
        private_url = "https://api.github.com/user/repos?affiliation=owner&sort=pushed&direction=desc&per_page=100"
        private_data = api(private_url)
        if private_data:
            existing_ids = {r["id"] for r in repos}
            for r in private_data:
                if r["id"] not in existing_ids and not r.get("fork"):
                    repos.append(r)
    
    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    return repos[:MAX_REPOS]

def get_daily_additions(repo_full_name, date_str):
    """Calculate lines added by the user in a specific repo on a specific date."""
    since = f"{date_str}T00:00:00Z"
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    until = f"{next_day}T00:00:00Z"
    
    # Fetch commits by the user in the given time range
    commits_url = (
        f"https://api.github.com/repos/{repo_full_name}/commits"
        f"?author={USER}&since={since}&until={until}&per_page=100"
    )
    commits = api(commits_url)
    
    if not commits:
        return 0
    
    total_add = 0
    for c in commits:
        sha = c['sha']
        # Fetch commit details for additions statistics
        detail = api(f"https://api.github.com/repos/{repo_full_name}/commits/{sha}")
        if detail and "stats" in detail:
            # ONLY count additions, exclude deletions for "Lines Added"
            additions = detail["stats"].get("additions", 0)
            total_add += additions
    
    return total_add

def generate_svg(data):
    """Generate dark-themed SVG bar chart with accurate values."""
    w = 1000
    bar_h = 22
    gap = 6
    pad_left = 70
    pad_right = 60
    pad_top = 40
    h = pad_top + len(data) * (bar_h + gap) + 20
    
    max_val = max((v for _, v in data), default=0)
    # Ensure max_val is at least 1 to avoid division by zero
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
        
        # GitHub-like green colors
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
    print(f"Starting accurate stats generation for {USER}...")
    repos = get_repos()
    repo_list = [r["full_name"] for r in repos]
    print(f"Scanning {len(repo_list)} repositories for user commits...")
    
    today = datetime.utcnow().date()
    daily_stats = {}
    for d in range(DAYS):
        date = today - timedelta(days=d)
        daily_stats[date.strftime("%Y-%m-%d")] = 0

    for repo in repo_list:
        print(f" Checking {repo}...")
        for date_str in daily_stats.keys():
            adds = get_daily_additions(repo, date_str)
            if adds > 0:
                print(f"  {date_str}: +{adds} lines")
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
    print("Successfully updated daily lines stats with real values!")

if __name__ == "__main__":
    main()
