#!/usr/bin/env python3
"""
BACKFILL — manual full cache rebuild.

What it does:
- Rebuilds img/daily_lines_cache.json from scratch
- Scans the last 365 Winnipeg-local days
- Scans only owned non-fork repositories that were active in the current Winnipeg year
- Uses GitHub REST pagination for both repositories and commits
- Uses America/Winnipeg timezone for daily attribution
"""

import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

TOKEN = os.environ.get("GH_TOKEN", "")
USER = "GaponovAlexey"
DAYS = 365

TZ = ZoneInfo("America/Winnipeg")

AUTHOR_NAMES = {
    USER.lower(),
    "gaponovalexey",
    "alexey",
    "alexey gaponov",
    "gaponov alexey",
}

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
else:
    print("ERROR: GH_TOKEN not set. Add GH_TOKEN secret and run again.")
    raise SystemExit(1)

SKIP_MESSAGES = [
    "update daily lines stats",
    "backfill stats",
    "update stats",
    "update readme",
    "auto update",
    "ci: update",
    "github actions",
]

CACHE_PATH = "img/daily_lines_cache.json"


def get_rate_limit_wait_seconds(headers, fallback=30):
    """Return a safe wait time using GitHub rate limit headers."""
    reset_value = headers.get("X-RateLimit-Reset")
    if reset_value:
        try:
            return max(5, int(reset_value) - int(time.time()) + 2)
        except (TypeError, ValueError):
            pass
    return fallback


def api(url):
    """Fetch JSON from GitHub API and return (data, headers)."""
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(6):
        try:
            with urllib.request.urlopen(req) as response:
                raw = response.read()
                data = json.loads(raw) if raw else None
                return data, response.headers

        except urllib.error.HTTPError as e:
            if e.code == 403:
                wait_s = get_rate_limit_wait_seconds(e.headers, fallback=30)
                print(f"  rate limit, waiting {wait_s}s... ({attempt + 1}/6)")
                time.sleep(wait_s)
                continue

            if e.code in (404, 409, 422):
                return None, {}

            print(f"  HTTP {e.code}: {url}")
            return None, {}

        except Exception as ex:
            print(f"  err: {ex}")
            return None, {}

    return None, {}


def parse_next_link(link_header):
    """Extract next page URL from GitHub Link header."""
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' not in part:
            continue

        left = part.find("<")
        right = part.find(">")

        if left != -1 and right != -1 and right > left:
            return part[left + 1:right]

    return None


def iter_api_pages(url):
    """Yield all items across paginated GitHub API responses."""
    next_url = url

    while next_url:
        data, headers = api(next_url)
        if data is None:
            break

        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data

        next_url = parse_next_link(headers.get("Link", ""))


def normalize_author_name(name):
    """Normalize author name for stable matching."""
    return " ".join((name or "").strip().lower().split())


def parse_github_datetime(value):
    """Parse GitHub ISO datetime into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc_to_winnipeg_datetime(value):
    """Convert GitHub UTC datetime string into Winnipeg datetime."""
    return parse_github_datetime(value).astimezone(TZ)


def utc_to_winnipeg_date(value):
    """Convert GitHub UTC datetime string into Winnipeg date string."""
    return utc_to_winnipeg_datetime(value).strftime("%Y-%m-%d")


def iso_z(dt):
    """Format aware datetime as GitHub-compatible UTC string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_midnight_to_utc(local_date):
    """Convert Winnipeg local midnight to UTC."""
    local_dt = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        0,
        0,
        0,
        tzinfo=TZ,
    )
    return local_dt.astimezone(timezone.utc)


def get_current_local_year():
    """Return current year in Winnipeg timezone."""
    return datetime.now(TZ).year


def get_current_local_year_start_utc():
    """Return the start of current Winnipeg year converted to UTC."""
    current_year = get_current_local_year()
    local_dt = datetime(current_year, 1, 1, 0, 0, 0, tzinfo=TZ)
    return local_dt.astimezone(timezone.utc)


def skip_msg(msg):
    """Skip automation commits and generated update commits."""
    lowered = (msg or "").lower()
    return any(item in lowered for item in SKIP_MESSAGES)


def is_mine(commit):
    """Check whether the commit belongs to the target user."""
    author = commit.get("author")
    if isinstance(author, dict):
        if author.get("login", "").lower() == USER.lower():
            return True

    name = normalize_author_name(
        commit.get("commit", {}).get("author", {}).get("name", "")
    )

    if name in AUTHOR_NAMES:
        return True

    return name.replace(" ", "") == USER.lower()


def get_repos():
    """
    Load only owned non-fork repositories that were active
    in the current Winnipeg year.
    """
    current_year = get_current_local_year()
    year_start_utc = get_current_local_year_start_utc()
    since_param = iso_z(year_start_utc)

    repos = []

    url = (
        "https://api.github.com/user/repos"
        f"?affiliation=owner&sort=pushed&direction=desc&since={since_param}"
        "&per_page=100&page=1"
    )

    for repo in iter_api_pages(url):
        if not isinstance(repo, dict):
            continue

        if repo.get("fork"):
            continue

        pushed_at = repo.get("pushed_at")
        if not pushed_at:
            continue

        pushed_local = utc_to_winnipeg_datetime(pushed_at)
        if pushed_local.year != current_year:
            continue

        repos.append(repo)

    repos.sort(key=lambda x: x.get("pushed_at", ""), reverse=True)
    return repos


def build_monthly_totals(stats, year):
    """Build monthly totals for the given year from daily stats."""
    monthly = defaultdict(int)

    for date_str, value in stats.items():
        if date_str.startswith(f"{year}-"):
            monthly[date_str[:7]] += value

    return monthly


def main():
    today = datetime.now(TZ).date()
    current_year = today.year
    window_start = today - timedelta(days=DAYS - 1)

    since_utc = local_midnight_to_utc(window_start) - timedelta(seconds=1)
    since_param = iso_z(since_utc)

    print(f"=== BACKFILL for {USER} ===")
    print(f"Timezone: {TZ.key}")
    print(f"Today: {today}")
    print(f"Window: {window_start} .. {today}")
    print(f"Repos filter: owned, non-fork, active in Winnipeg year {current_year}")
    print(f"GitHub commits since: {since_param}\n")

    repos = get_repos()
    print(f"Active repos in current year: {len(repos)}\n")

    stats = defaultdict(int)
    names_seen = set()

    for repo in repos:
        repo_name = repo["full_name"]
        pushed_local = utc_to_winnipeg_datetime(repo["pushed_at"]).strftime("%Y-%m-%d %H:%M")
        print(f"→ {repo_name}  (last push local: {pushed_local})")

        commits_url = (
            f"https://api.github.com/repos/{repo_name}/commits"
            f"?since={since_param}&per_page=100&page=1"
        )

        found_any = False
        matched_any = False

        for commit in iter_api_pages(commits_url):
            if not isinstance(commit, dict):
                continue

            found_any = True

            author_name = commit.get("commit", {}).get("author", {}).get("name", "")
            author_login = (commit.get("author") or {}).get("login", "")
            names_seen.add(f"{author_name!r}  login={author_login!r}")

            if not is_mine(commit):
                continue

            message = commit.get("commit", {}).get("message", "")
            if skip_msg(message):
                continue

            local_date = utc_to_winnipeg_date(commit["commit"]["author"]["date"])
            if local_date < window_start.isoformat() or local_date > today.isoformat():
                continue

            sha = commit.get("sha")
            if not sha:
                continue

            detail, _ = api(f"https://api.github.com/repos/{repo_name}/commits/{sha}")
            if not detail or "stats" not in detail:
                continue

            additions = int(detail["stats"].get("additions", 0) or 0)
            if additions:
                matched_any = True
                short_msg = message.split("\n", 1)[0][:60]
                print(f"  {local_date}  +{additions:>7,}  {short_msg}")

            stats[local_date] += additions

        if not found_any:
            print("  no commits in window")
        elif not matched_any:
            print("  no matching commits")
        print()

    print("=== All author names found in scanned commits ===")
    for item in sorted(names_seen):
        mine = "✓ MINE" if any(part in item.lower() for part in list(AUTHOR_NAMES) + [USER.lower()]) else ""
        print(f"  {item}  {mine}")

    active_days = [date_str for date_str, value in stats.items() if value]
    print(f"\n=== Results: {len(active_days)} active days ===")
    for date_str in sorted(stats):
        value = stats[date_str]
        if value:
            bar = "▓" * min(50, max(1, value // 200))
            print(f"  {date_str}  {value:>8,}  {bar}")

    monthly = build_monthly_totals(stats, current_year)
    print(f"\n=== Monthly totals for {current_year} ===")
    for month in range(1, 13):
        ym = f"{current_year}-{month:02d}"
        print(f"  {ym}  {monthly.get(ym, 0):>8,}")

    os.makedirs("img", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as file:
        json.dump(dict(stats), file, indent=2, sort_keys=True)

    print(f"\nSaved to {CACHE_PATH}")
    print("Backfill finished.")
    print("You can now refresh the README chart from your existing daily workflow.")


if __name__ == "__main__":
    main()
