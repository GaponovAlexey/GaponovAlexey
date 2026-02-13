#!/usr/bin/env python3
"""
Daily Lines Counter - generates SVG bar chart of daily lines added.
Runs via GitHub Actions, updates README with img tag pointing to SVG.
Optimized version using GraphQL API.
"""

import os
import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"
DAYS = 14
MAX_REPOS = 20  # Limit to top 20 most active repos
INACTIVE_DAYS_THRESHOLD = 90  # Skip repos not updated in last 90 days

HEADERS = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}

def graphql_query(query):
                """Execute GraphQL query"""
                url = "https://api.github.com/graphql"
                headers = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}
                data = json.dumps({"query": query}).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                try:
                                    with urllib.request.urlopen(req) as r:
                                                            return json.loads(r.read())
                except urllib.error.HTTPError as e:
                                    print(f"GraphQL error: {e}")
                                    return None

            def get_active_repos():
                            """Get top MAX_REPOS most recently updated repositories using GraphQL"""
                            cutoff_date = (datetime.utcnow() - timedelta(days=INACTIVE_DAYS_THRESHOLD)).isoformat()

    query = f'''
        {{
              user(login: "{USER}") {{
                      repositories(first: {MAX_REPOS}, ownerAffiliations: OWNER, isFork: false, 
                                           orderBy: {{field: PUSHED_AT, direction: DESC}}) {{
                                                     nodes {{
                                                                 name
                                                                             pushedAt
                                                                                       }}
                                                                                               }}
                                                                                                     }}
                                                                                                         }}
                                                                                                             '''

    result = graphql_query(query)
    if not result or "data" not in result:
                        return []

    repos = result["data"]["user"]["repositories"]["nodes"]
    # Filter repos updated within threshold
    active_repos = [
                        r["name"] for r in repos 
                        if r["pushedAt"] and r["pushedAt"] >= cutoff_date
    ]

    print(f"Found {len(active_repos)} active repos (updated in last {INACTIVE_DAYS_THRESHOLD} days)")
    return active_repos

def api(url):
                """REST API fallback for commit details"""
                req = urllib.request.Request(url, headers=HEADERS)
                try:
                                    with urllib.request.urlopen(req) as r:
                                                            return json.loads(r.read())
                except urllib.error.HTTPError:
                                    return None

            def get_daily_additions(repo_name, date_str):
                            """Get additions for a specific day using REST API"""
                            since = f"{date_str}T00:00:00Z"
                            next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                            until = f"{next_day}T00:00:00Z"

    commits = api(
                        f"https://api.github.com/repos/{USER}/{repo_name}/commits"
                        f"?since={since}&until={until}&per_page=100"
    )

    if not commits:
                        return 0

    total_add = 0
    for c in commits:
                        detail = api(f"https://api.github.com/repos/{USER}/{repo_name}/commits/{c['sha']}")
                        if detail and "stats" in detail:
                                                total_add += detail["stats"].get("additions", 0)

                    return total_add

def generate_svg(data):
                """Generate dark-themed SVG bar chart. data = [(label, value), ...]"""
                w = 1000
                bar_h = 22
                gap = 6
                pad_left = 70
                pad_right = 60
                pad_top = 40
                h = pad_top + len(data) * (bar_h + gap) + 20
                max_val = max((v for _, v in data), default=1) or 1
                bar_area = w - pad_left - pad_right

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    lines.append(f'<rect width="{w}" height="{h}" rx="12" fill="#0d1117"/>')
    lines.append(f'<text x="{w//2}" y="24" text-anchor="middle" fill="#8b949e" font-family="monospace" font-size="13">Daily Lines Added (last {DAYS} days)</text>')

    for i, (label, val) in enumerate(data):
                        y = pad_top + i * (bar_h + gap)
                        bw = int((val / max_val) * bar_area) if val > 0 else 0
                        ratio = val / max_val if max_val > 0 else 0

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
    return "\\n".join(lines)

def update_readme(svg_content):
                """Update README with SVG image tag"""
                readme_path = "README.md"
                with open(readme_path, "r") as f:
                                    content = f.read()

                start_marker = "<!-- DAILY_LINES_START -->"
                end_marker = "<!-- DAILY_LINES_END -->"
                img_tag = '<img src="img/daily_lines.svg" alt="Daily Lines Added" width="100%">'
                block = f"{start_marker}\\n{img_tag}\\n{end_marker}"

    if start_marker in content:
                        content = re.sub(
                                                f"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
                                                block,
                                                content,
                                                flags=re.DOTALL,
                        )
else:
                    content += f"\\n\\n{block}\\n"

    with open(readme_path, "w") as f:
                        f.write(content)

def main():
                print(f"Fetching active repos for {USER}...")
                repo_names = get_active_repos()

    if not repo_names:
                        print("No active repositories found!")
                        return

    print(f"Processing {len(repo_names)} repos: {', '.join(repo_names)}")

    today = (datetime.utcnow() - timedelta(hours=6)).date()
    data = []

    for d in range(DAYS - 1, -1, -1):
                        date = today - timedelta(days=d)
                        date_str = date.strftime("%Y-%m-%d")
                        label = date.strftime("%b %d")
                        total = 0

        for repo in repo_names:
                                adds = get_daily_additions(repo, date_str)
                                if adds > 0:
                                                            print(f"  {repo} on {date_str}: +{adds}")
                                                        total += adds

        data.append((label, total))
        print(f"{label}: {total:,} lines")

    svg = generate_svg(data)
    os.makedirs("img", exist_ok=True)

    with open("img/daily_lines.svg", "w") as f:
                        f.write(svg)

    update_readme(svg)
    print("Done!")

if __name__ == "__main__":
                main()
