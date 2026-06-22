#!/usr/bin/env python3
"""
DAILY UPDATE — runs in GitHub Actions every night.
Loads cache from img/daily_lines_cache.json, scans last 7 days, rebuilds SVG.
Uses America/Winnipeg timezone for accurate date tracking.
"""

import os
import re
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

TOKEN = os.environ.get("GH_TOKEN", "")
USER  = "GaponovAlexey"
DAYS  = 7
MAX_REPOS = 30

TZ = ZoneInfo("America/Vancouver")

AUTHOR_NAMES = {"gaponovalexey", "alexey", "alexey gaponov", "gaponov alexey"}

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
else:
    print("Warning: No GH_TOKEN")

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
                print(f"  rate limit, waiting 20s... ({attempt+1}/3)")
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
    a = commit.get("author")
    if a and isinstance(a, dict) and a.get("login", "").lower() == USER.lower():
        return True
    name = commit.get("commit", {}).get("author", {}).get("name", "").lower()
    return name in AUTHOR_NAMES


def skip_msg(msg):
    return any(s in (msg or "").lower() for s in SKIP_MESSAGES)


def utc_to_winnipeg_date(date_str):
    """Convert UTC ISO date string (e.g. '2025-03-24T23:45:00Z') to Winnipeg local date string."""
    dt_utc = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    dt_local = dt_utc.astimezone(TZ)
    return dt_local.strftime("%Y-%m-%d")


def collect(repos):
    today  = datetime.now(TZ).date()
    cutoff = (today - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    stats  = defaultdict(int)

    print(f"Winnipeg date: {today}, cutoff: {cutoff}")

    for repo in repos:
        rname  = repo["full_name"]
        pushed = (repo.get("pushed_at") or "")[:10]
        if pushed and pushed < cutoff:
            continue

        print(f"→ {rname}")
        commits = api(
            f"https://api.github.com/repos/{rname}/commits"
            f"?since={cutoff}T00:00:00Z&per_page=100"
        )
        if not commits or not isinstance(commits, list):
            continue

        for c in commits:
            if not is_mine(c):
                continue
            msg = c.get("commit", {}).get("message", "")
            if skip_msg(msg):
                continue
            # Convert UTC commit time to Winnipeg local date
            utc_date_str = c["commit"]["author"]["date"]
            local_date   = utc_to_winnipeg_date(utc_date_str)
            sha          = c["sha"]
            detail       = api(f"https://api.github.com/repos/{rname}/commits/{sha}")
            if detail and "stats" in detail:
                adds = detail["stats"].get("additions", 0)
                dels = detail["stats"].get("deletions", 0)
                changed = adds + dels
                if changed:
                        print(f"  {local_date} +{adds:,}/-{dels:,}  {msg.split(chr(10))[0][:40]}")
                    stats[local_date] += changed
    return stats


def generate_svg(stats):
    today    = datetime.now(TZ).date()
    cur_year = today.year

    # monthly (current year)
    monthly = defaultdict(int)
    for date_str, val in stats.items():
        if date_str.startswith(str(cur_year)):
            monthly[date_str[:7]] += val

    # last 7 days
    week = []
    for d in range(6, -1, -1):
        dt  = today - timedelta(days=d)
        ds  = dt.strftime("%Y-%m-%d")
        lbl = dt.strftime("%a")
        week.append((lbl, stats.get(ds, 0)))

    W       = 680
    PAD_L   = 32
    PAD_R   = 16
    usable  = W - PAD_L - PAD_R  # 632

    # monthly section
    N_M     = 12
    COL_GAP = 6
    COL_W   = (usable - (N_M - 1) * COL_GAP) // N_M
    BAR_M   = 70
    LABEL_H = 14
    SEC1_T  = 16
    SEC1_H  = BAR_M + LABEL_H + 4

    SEP_Y   = SEC1_T + SEC1_H + 10

    # weekly section
    N_D     = 7
    DAY_GAP = 8
    DAY_W   = (usable - (N_D - 1) * DAY_GAP) // N_D
    BAR_D   = 48
    SEC2_T  = SEP_Y + 12
    SEC2_H  = BAR_D + LABEL_H + 4

    H = SEC2_T + SEC2_H + 12

    max_m = max(monthly.values(), default=1) or 1
    max_d = max((v for _, v in week), default=1) or 1

    def green(ratio):
        if ratio == 0:  return "#1c2128", "#30363d"
        if ratio > 0.6: return "#3fb950", "#3fb950"
        if ratio > 0.2: return "#238636", "#238636"
        return "#1a7f37", "#6e7681"

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {W} {H}">')

    # monthly columns
    for i, mn in enumerate(range(1, 13)):
        ym    = f"{cur_year}-{mn:02d}"
        val   = monthly.get(ym, 0)
        x     = PAD_L + i * (COL_W + COL_GAP)
        fut   = (mn > today.month)
        ratio = 0 if fut or val == 0 else val / max_m
        bh    = max(2, int(ratio * BAR_M)) if ratio > 0 else 2
        by    = SEC1_T + BAR_M - bh
        fill, nfill = green(ratio)
        op    = "0.2" if fut else "1"

        out.append(
            f'<rect x="{x}" y="{by}" width="{COL_W}" height="{bh}" '
            f'rx="2" fill="{fill}" opacity="{op}"/>'
        )
        if val > 0 and not fut:
            lv = f"{val//1000}k" if val >= 1000 else str(val)
            out.append(
                f'<text x="{x + COL_W//2}" y="{by - 3}" '
                f'font-family="monospace" font-size="8" fill="{nfill}" '
                f'text-anchor="middle">{lv}</text>'
            )
        mlbl = datetime(cur_year, mn, 1).strftime("%b")
        out.append(
            f'<text x="{x + COL_W//2}" y="{SEC1_T + BAR_M + LABEL_H}" '
            f'font-family="monospace" font-size="9" fill="#484f58" '
            f'text-anchor="middle" opacity="0.5">{mlbl}</text>'
        )

    # separator
    out.append(
        f'<line x1="{PAD_L}" y1="{SEP_Y}" x2="{W - PAD_R}" y2="{SEP_Y}" '
        f'stroke="#21262d" stroke-width="1" opacity="0.6"/>'
    )

    # weekly bars
    for i, (lbl, val) in enumerate(week):
        x     = PAD_L + i * (DAY_W + DAY_GAP)
        ratio = val / max_d if val > 0 else 0
        bh    = max(2, int(ratio * BAR_D)) if ratio > 0 else 2
        by    = SEC2_T + BAR_D - bh
        fill, nfill = green(ratio)

        out.append(
            f'<rect x="{x}" y="{by}" width="{DAY_W}" height="{bh}" '
            f'rx="2" fill="{fill}"/>'
        )
        if val > 0:
            out.append(
                f'<text x="{x + DAY_W//2}" y="{by - 3}" '
                f'font-family="monospace" font-size="8" fill="{nfill}" '
                f'text-anchor="middle">{val:,}</text>'
            )
        out.append(
            f'<text x="{x + DAY_W//2}" y="{SEC2_T + BAR_D + LABEL_H}" '
            f'font-family="monospace" font-size="9" fill="#484f58" '
            f'text-anchor="middle" opacity="0.5">{lbl}</text>'
        )

    out.append("</svg>")
    return "\n".join(out)


def update_readme():
    path = "README.md"
    if not os.path.exists(path):
        return
    with open(path) as f:
        content = f.read()
    s   = "<!-- DAILY_LINES_START -->"
    e   = "<!-- DAILY_LINES_END -->"
    img = '<img src="img/daily_lines.svg" alt="Daily Lines Added" width="100%">'
    block = f"{s}\n{img}\n{e}"
    if s in content:
        content = re.sub(f"{re.escape(s)}.*?{re.escape(e)}", block, content, flags=re.DOTALL)
    else:
        content += f"\n\n{block}\n"
    with open(path, "w") as f:
        f.write(content)


def main():
    print(f"Daily update for {USER}, last {DAYS} days")
    print(f"Current Vancouver date/time: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M %Z')}")

    repos = get_repos()
    print(f"Repos: {len(repos)}")

    # load cache
    stats = defaultdict(int)
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            for k, v in json.load(f).items():
                stats[k] = v
        print(f"Cache loaded: {len(stats)} days")

    # scan fresh data
    new = collect(repos)
    for k, v in new.items():
        stats[k] = v
    # save updated cache
    os.makedirs("img", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(dict(stats), f, indent=2, sort_keys=True)

    svg = generate_svg(stats)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)

    update_readme()
    print("Done!")


if __name__ == "__main__":
    main()
