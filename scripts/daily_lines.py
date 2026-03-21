#!/usr/bin/env python3
"""
Daily Lines Counter
Usage:
  python daily_lines.py             # daily update
  python daily_lines.py --backfill  # scan last 365 days (first run)
  python daily_lines.py --debug     # print all author names found
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

TOKEN     = os.environ.get("GH_TOKEN", "")
USER      = "GaponovAlexey"
AUTHOR_NAMES = {"gaponovalexey", "alexey", "alexey gaponov", "gaponov alexey"}
BACKFILL  = "--backfill" in sys.argv
DEBUG     = "--debug"    in sys.argv
DAYS      = 365 if BACKFILL else 14
MAX_REPOS = 30

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"
else:
    print("Warning: No GH_TOKEN")

SKIP_MESSAGES = [
    "update daily lines stats", "update stats", "update readme",
    "auto update", "ci: update", "github actions",
]


# ── api ───────────────────────────────────────────────────────────────────────

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
    a = commit.get("author")
    if a and isinstance(a, dict) and a.get("login", "").lower() == USER.lower():
        return True
    name = commit.get("commit", {}).get("author", {}).get("name", "").lower()
    return name in AUTHOR_NAMES


def skip_msg(msg):
    m = (msg or "").lower().strip()
    return any(s in m for s in SKIP_MESSAGES)


# ── collect ───────────────────────────────────────────────────────────────────

def collect(repos, days):
    today = datetime.utcnow().date()
    stats = defaultdict(int)
    names_seen = set()

    for repo in repos:
        rname  = repo["full_name"]
        pushed = (repo.get("pushed_at") or "")[:10]
        cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        if pushed and pushed < cutoff:
            continue

        print(f"→ {rname}")
        since_dt = today - timedelta(days=days)
        commits = api(
            f"https://api.github.com/repos/{rname}/commits"
            f"?since={since_dt}T00:00:00Z&per_page=100"
        )
        if not commits or not isinstance(commits, list):
            continue

        for c in commits:
            if DEBUG:
                name  = c.get("commit", {}).get("author", {}).get("name", "")
                login = (c.get("author") or {}).get("login", "")
                names_seen.add(f"{name!r} login={login!r}")

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
                    print(f"  {date_str} +{adds:,}  {msg.split(chr(10))[0][:40]}")
                stats[date_str] += adds

    if DEBUG and names_seen:
        print("\n=== Author names found ===")
        for n in sorted(names_seen):
            print(" ", n)

    return stats


# ── SVG ───────────────────────────────────────────────────────────────────────

def generate_svg(stats):
    today    = datetime.utcnow().date()
    cur_year = today.year

    # ── monthly data (current year only) ──
    monthly = defaultdict(int)
    for date_str, val in stats.items():
        if date_str.startswith(str(cur_year)):
            monthly[date_str[:7]] += val

    # ── last 7 days ──
    week = []
    for d in range(6, -1, -1):
        dt  = today - timedelta(days=d)
        ds  = dt.strftime("%Y-%m-%d")
        lbl = dt.strftime("%a")          # Mon, Tue …
        week.append((lbl, stats.get(ds, 0)))

    # ── layout constants ──
    W         = 680
    PAD_L     = 32
    PAD_R     = 16
    usable    = W - PAD_L - PAD_R       # 632

    # monthly section
    N_MONTHS  = 12
    COL_GAP   = 6
    COL_W     = (usable - (N_MONTHS - 1) * COL_GAP) // N_MONTHS   # ~46
    BAR_MAX_M = 70
    SEC1_TOP  = 16
    LABEL_H   = 14
    SEC1_H    = BAR_MAX_M + LABEL_H + 4   # 88

    # separator
    SEP_Y     = SEC1_TOP + SEC1_H + 10

    # weekly section
    N_DAYS    = 7
    DAY_GAP   = 8
    DAY_W     = (usable - (N_DAYS - 1) * DAY_GAP) // N_DAYS        # ~82
    BAR_MAX_D = 48
    SEC2_TOP  = SEP_Y + 12
    SEC2_H    = BAR_MAX_D + LABEL_H + 4

    H = SEC2_TOP + SEC2_H + 12

    max_m = max(monthly.values(), default=1) or 1
    max_d = max(v for _, v in week) or 1

    def green(ratio):
        if ratio == 0:   return "#1c2128", "#30363d"
        if ratio > 0.6:  return "#3fb950", "#3fb950"
        if ratio > 0.2:  return "#238636", "#238636"
        return "#1a7f37", "#6e7681"

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {W} {H}">')

    # ── monthly columns ──
    for i, mn in enumerate(range(1, 13)):
        ym   = f"{cur_year}-{mn:02d}"
        val  = monthly.get(ym, 0)
        x    = PAD_L + i * (COL_W + COL_GAP)
        fut  = (mn > today.month)
        ratio = 0 if fut or val == 0 else val / max_m
        bh   = max(2, int(ratio * BAR_MAX_M)) if ratio > 0 else 2
        by   = SEC1_TOP + BAR_MAX_M - bh
        fill, nfill = green(ratio)
        op   = "0.25" if fut else "1"

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
            f'<text x="{x + COL_W//2}" y="{SEC1_TOP + BAR_MAX_M + LABEL_H}" '
            f'font-family="monospace" font-size="9" fill="#484f58" '
            f'text-anchor="middle" opacity="0.5">{mlbl}</text>'
        )

    # ── separator ──
    out.append(
        f'<line x1="{PAD_L}" y1="{SEP_Y}" x2="{W - PAD_R}" y2="{SEP_Y}" '
        f'stroke="#21262d" stroke-width="1" opacity="0.6"/>'
    )

    # ── weekly bars ──
    for i, (lbl, val) in enumerate(week):
        x     = PAD_L + i * (DAY_W + DAY_GAP)
        ratio = val / max_d if val > 0 else 0
        bh    = max(2, int(ratio * BAR_MAX_D)) if ratio > 0 else 2
        by    = SEC2_TOP + BAR_MAX_D - bh
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
            f'<text x="{x + DAY_W//2}" y="{SEC2_TOP + BAR_MAX_D + LABEL_H}" '
            f'font-family="monospace" font-size="9" fill="#484f58" '
            f'text-anchor="middle" opacity="0.5">{lbl}</text>'
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
    print(f"Mode: {'BACKFILL' if BACKFILL else 'DEBUG' if DEBUG else 'DAILY'}  user={USER}")

    repos = get_repos()
    print(f"Repos: {len(repos)}")

    cache_path = "img/daily_lines_cache.json"
    stats = defaultdict(int)

    # load cache (skip on backfill to rescan everything)
    if not BACKFILL and os.path.exists(cache_path):
        with open(cache_path) as f:
            for k, v in json.load(f).items():
                stats[k] = v
        print(f"Cache: {len(stats)} days loaded")

    # scan
    new = collect(repos, DAYS)
    for k, v in new.items():
        stats[k] = max(stats.get(k, 0), v)

    # save cache
    os.makedirs("img", exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(dict(stats), f, indent=2)

    # summary
    print("\n--- non-zero days ---")
    for d in sorted(stats):
        if stats[d]:
            print(f"  {d}: {stats[d]:,}")

    svg = generate_svg(stats)
    with open("img/daily_lines.svg", "w") as f:
        f.write(svg)

    update_readme()
    print("\nDone!")


if __name__ == "__main__":
    main()
