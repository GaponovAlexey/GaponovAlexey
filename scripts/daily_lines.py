#!/usr/bin/env python3
"""
Daily Lines Counter
Usage:
  python daily_lines.py             # daily update: last 14 days + rebuild SVG
  python daily_lines.py --backfill  # scan last 365 days (first run)
  python daily_lines.py --debug     # print all author names found (for setup)
"""

import os
import re
import sys
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from collections import defaultdict

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"

# All name variants from your git commits (run --debug to discover)
AUTHOR_NAMES = {"gaponovalexey", "alexey", "alexey gaponov", "gaponov alexey"}

BACKFILL = "--backfill" in sys.argv
DEBUG    = "--debug" in sys.argv
DAYS     = 365 if BACKFILL else 14
MAX_REPOS = 30

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
else:
    print("Warning: No GH_TOKEN")

SKIP_MESSAGES = [
    "update daily lines stats",
    "update stats",
    "update readme",
    "auto update",
    "ci: update",
    "github actions",
]

# ── helpers ──────────────────────────────────────────────────────────────────

def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  rate limit, wait 20s ({attempt+1}/3)")
                time.sleep(20)
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
    if TOKEN:
        d = api("https://api.github.com/user/repos?affiliation=owner&sort=pushed&direction=desc&per_page=100")
        if d:
            repos = [r for r in d if not r.get("fork")]
    if not repos:
        d = api(f"https://api.github.com/users/{USER}/repos?type=owner&sort=pushed&direction=desc&per_page=100")
        if d:
            repos = [r for r in d if not r.get("fork")]
    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    return repos[:MAX_REPOS]


def is_mine(commit):
    # by GitHub login
    a = commit.get("author")
    if a and isinstance(a, dict) and a.get("login", "").lower() == USER.lower():
        return True
    # by commit author name
    name = commit.get("commit", {}).get("author", {}).get("name", "").lower()
    return name in AUTHOR_NAMES


def skip_msg(msg):
    m = (msg or "").lower().strip()
    return any(s in m for s in SKIP_MESSAGES)


# ── data collection ───────────────────────────────────────────────────────────

def collect(repos, days):
    today = datetime.utcnow().date()
    stats = defaultdict(int)
    author_names_seen = set()

    for repo in repos:
        rname = repo["full_name"]
        pushed = (repo.get("pushed_at") or "")[:10]
        cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        # skip repo entirely if not touched in our window
        if pushed and pushed < cutoff:
            continue

        print(f"→ {rname}")

        since_dt = today - timedelta(days=days)
        url = (
            f"https://api.github.com/repos/{rname}/commits"
            f"?since={since_dt}T00:00:00Z&per_page=100"
        )
        commits = api(url)
        if not commits or not isinstance(commits, list):
            continue

        for c in commits:
            # collect all names for --debug
            if DEBUG:
                name = c.get("commit", {}).get("author", {}).get("name", "")
                login = (c.get("author") or {}).get("login", "")
                author_names_seen.add(f"{name!r} / login={login!r}")

            if not is_mine(c):
                continue
            msg = c.get("commit", {}).get("message", "")
            if skip_msg(msg):
                continue

            date_str = c["commit"]["author"]["date"][:10]
            sha = c["sha"]
            detail = api(f"https://api.github.com/repos/{rname}/commits/{sha}")
            if detail and "stats" in detail:
                adds = detail["stats"].get("additions", 0)
                if adds:
                    short = msg.split("\n")[0][:40]
                    print(f"  {date_str} +{adds:,}  {short}")
                stats[date_str] += adds

    if DEBUG and author_names_seen:
        print("\n=== Author names found in your repos ===")
        for n in sorted(author_names_seen):
            print(" ", n)

    return stats


# ── SVG: two-year monthly column chart ───────────────────────────────────────

def generate_svg(stats):
    """
    Two rows of month columns (prev year / current year).
    Each column = one month, height proportional to total lines that month.
    """
    today = datetime.utcnow().date()
    cur_year  = today.year
    prev_year = cur_year - 1

    # aggregate by month
    monthly = defaultdict(int)
    for date_str, val in stats.items():
        ym = date_str[:7]  # "2025-03"
        monthly[ym] += val

    months = [f"{m:02d}" for m in range(1, 13)]

    def month_label(m):
        return datetime(2000, int(m), 1).strftime("%b")

    # dimensions
    W        = 680
    col_w    = 44
    col_gap  = 8
    row_gap  = 28
    pad_l    = 32
    pad_top  = 20
    bar_max  = 80   # max bar height px
    row_h    = bar_max + 20   # bar + label below
    H        = pad_top + row_h * 2 + row_gap + 24

    all_vals = [monthly.get(f"{y}-{m}", 0) for y in (prev_year, cur_year) for m in months]
    max_val  = max(all_vals) if any(all_vals) else 1

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {W} {H}">')

    for row_i, year in enumerate((prev_year, cur_year)):
        row_y = pad_top + row_i * (row_h + row_gap)

        # year label
        out.append(
            f'<text x="{pad_l}" y="{row_y + bar_max + 14}" '
            f'font-family="monospace" font-size="9" fill="#484f58" opacity="0.4">{year}</text>'
        )

        for col_i, m in enumerate(months):
            ym  = f"{year}-{m}"
            val = monthly.get(ym, 0)
            x   = pad_l + 28 + col_i * (col_w + col_gap)
            bh  = max(2, int((val / max_val) * bar_max)) if val > 0 else 2
            by  = row_y + bar_max - bh

            # is this month in the future?
            future = (year == cur_year and
                      int(m) > today.month)

            if future:
                bar_fill  = "#1c2128"
                text_fill = "#30363d"
                opacity   = "0.3"
            elif val == 0:
                bar_fill  = "#1c2128"
                text_fill = "#484f58"
                opacity   = "0.5"
            elif val / max_val > 0.6:
                bar_fill  = "#3fb950"
                text_fill = "#3fb950"
                opacity   = "1"
            elif val / max_val > 0.2:
                bar_fill  = "#238636"
                text_fill = "#238636"
                opacity   = "1"
            else:
                bar_fill  = "#1a7f37"
                text_fill = "#6e7681"
                opacity   = "1"

            # bar
            out.append(
                f'<rect x="{x}" y="{by}" width="{col_w}" height="{bh}" '
                f'rx="2" fill="{bar_fill}" opacity="{opacity}"/>'
            )

            # value on top of bar (skip zeros and future)
            if val > 0 and not future:
                label_val = f"{val//1000}k" if val >= 1000 else str(val)
                out.append(
                    f'<text x="{x + col_w//2}" y="{by - 3}" '
                    f'font-family="monospace" font-size="8" fill="{text_fill}" '
                    f'text-anchor="middle">{label_val}</text>'
                )

            # month label below bar
            out.append(
                f'<text x="{x + col_w//2}" y="{row_y + bar_max + 13}" '
                f'font-family="monospace" font-size="8" fill="#484f58" '
                f'text-anchor="middle" opacity="0.5">{month_label(m)}</text>'
            )

    out.append("</svg>")
    return "\n".join(out)


# ── readme ────────────────────────────────────────────────────────────────────

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
        content = re.sub(f"{re.escape(s)}.*?{re.escape(e)}", block, content, flags=re.DOTALL)
    else:
        content += f"\n\n{block}\n"
    with open(path, "w") as f:
        f.write(content)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    mode = "BACKFILL 365d" if BACKFILL else ("DEBUG" if DEBUG else "DAILY 14d")
    print(f"Mode: {mode}  user={USER}")

    repos = get_repos()
    print(f"Repos: {len(repos)}")

    # Load existing cache if daily mode (don't rescan old data)
    cache_path = "img/daily_lines_cache.json"
    stats = defaultdict(int)

    if not BACKFILL and os.path.exists(cache_path):
        with open(cache_path) as f:
            cached = json.load(f)
        for k, v in cached.items():
            stats[k] = v
        print(f"Loaded {len(stats)} days from cache")

    # Collect new data
    new_stats = collect(repos, DAYS)
    for k, v in new_stats.items():
        stats[k] = max(stats.get(k, 0), v)

    # Save cache
    os.makedirs("img", exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(dict(stats), f, indent=2)

    # Print summary
    print("\n--- Summary (non-zero) ---")
    for d in sorted(stats):
        v = stats[d]
        if v:
            print(f"  {d}: {v:,}")

    svg = generate_svg(stats)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)

    update_readme()
    print("\nDone!")


if __name__ == "__main__":
    main()
