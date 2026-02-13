#!/usr/bin/env python3
"""
Daily Lines Counter - generates SVG bar chart of daily lines added.
Runs via GitHub Actions, updates README with img tag pointing to SVG.
OPTIMIZED: Uses GraphQL API, filters active repos, and limits date range.
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
MAX_REPOS = 20  # Limit to top N most recently updated repos
INACTIVE_DAYS_THRESHOLD = 90  # Skip repos inactive for more than 90 days

HEADERS = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}


def graphql_query(query, variables=None):
        """Execute GraphQL query - more efficient than REST API"""
        req_data = {"query": query}
        if variables:
                    req_data["variables"] = variables

        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps(req_data).encode(),
            headers=HEADERS
        )

    try:
                with urllib.request.urlopen(req) as r:
                                return json.loads(r.read())
    except urllib.error.HTTPError as e:
                print(f"GraphQL Error: {e}")
                return None


def get_active_repos():
        """Get recently active repositories using GraphQL - ONE API call instead of 200+"""
        query = """
        query($user: String!, $first: Int!) {
          user(login: $user) {
            repositories(
              first: $first
              ownerAffiliations: OWNER
              isFork: false
              orderBy: {field: PUSHED_AT, direction: DESC}
            ) {
              nodes {
                name
                pushedAt
              }
            }
          }
        }
        """

    variables = {"user": USER, "first": MAX_REPOS}
    result = graphql_query(query, variables)

    if not result or "data" not in result:
                print("Failed to fetch repos via GraphQL")
                return []

    repos = result["data"]["user"]["repositories"]["nodes"]

    # Filter out repos that haven't been updated recently
    cutoff_date = datetime.utcnow() - timedelta(days=INACTIVE_DAYS_THRESHOLD)
    active_repos = []

    for repo in repos:
                pushed_at = datetime.strptime(repo["pushedAt"], "%Y-%m-%dT%H:%M:%SZ")
                if pushed_at >= cutoff_date:
                                active_repos.append(repo["name"])

            return active_repos


def get_daily_additions_graphql(repo_names, date_str):
        """Get additions for ALL repos for a specific date using GraphQL - MUCH faster"""
        since = f"{date_str}T00:00:00Z"
        next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        until = f"{next_day}T00:00:00Z"

    # Build query for multiple repos at once
        repo_queries = []
        for i, repo_name in enumerate(repo_names):
                    repo_queries.append(f"""
                            repo{i}: repository(owner: "{USER}", name: "{repo_name}") {{
                      defaultBranchRef {{
                        target {{
                          ... on Commit {{
                            history(since: "{since}", until: "{until}") {{
                              nodes {{
                                additions
                              }}
                                                                        }}
                                        }}
                               }}
                                       }}
                                                                                      }}
                    """)

                query = "query {" + "\n".join(repo_queries) + "}"

                result = graphql_query(query)

                if not result or "data" not in result:
                    return {}

                # Parse results
                repo_additions = {}
                for i, repo_name in enumerate(repo_names):
                    repo_key = f"repo{i}"
                    if repo_key in result["data"] and result["data"][repo_key]:
                        repo_data = result["data"][repo_key]
                        if (repo_data and 
                            repo_data.get("defaultBranchRef") and 
                            repo_data["defaultBranchRef"].get("target") and
                            repo_data["defaultBranchRef"]["target"].get("history")):

                            commits = repo_data["defaultBranchRef"]["target"]["history"]["nodes"]
                            total = sum(c.get("additions", 0) for c in commits)
                            if total > 0:
                                repo_additions[repo_name] = total

                return repo_additions


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
                return "\n".join(lines)


            def update_readme(svg_content):
                readme_path = "README.md"
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
                print(f"Fetching active repos for {USER}...")
                repo_names = get_active_repos()
                print(f"Found {len(repo_names)} active repos (filtered from top {MAX_REPOS} recent)")

                today = (datetime.utcnow() - timedelta(hours=6)).date()
                data = []

                for d in range(DAYS - 1, -1, -1):
                    date = today - timedelta(days=d)
                    date_str = date.strftime("%Y-%m-%d")
                    label = date.strftime("%b %d")

                    # Get additions for all repos at once using GraphQL
                    additions_by_repo = get_daily_additions_graphql(repo_names, date_str)

                    total = 0
                    for repo, adds in additions_by_repo.items():
                        print(f"  {repo} on {date_str}: +{adds}")
                        total += adds

                    data.append((label, total))
                    print(f"{label}: {total:,} lines")

                svg = generate_svg(data)

                os.makedirs("img", exist_ok=True)
                with open("img/daily_lines.svg", "w") as f:
                    f.write(svg)

                update_readme(svg)
                print("Done! ✨ Optimized with GraphQL API, active repo filtering, and date limiting.")


            if __name__ == "__main__":
                main()
