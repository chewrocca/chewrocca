#!/usr/bin/env python3
"""Fetch a GitHub contribution calendar and write it as contrib.json.

Reads the same public endpoint the profile page itself renders,
https://github.com/users/<login>/contributions, which needs no authentication.

That matters twice over. It keeps the CI job tokenless, and it keeps the graphic
honest: the GraphQL contributionsCollection returns only what the calling token
can see, which for this account reported 1075 against the 1435 the profile shows
visitors. A banner that contradicts the profile header right above it is worse
than no banner.

Output matches the GraphQL response shape so gen.py consumes either source.

Usage:  python3 fetch_contrib.py <login> [-o contrib.json]
"""
import argparse, json, re, sys, urllib.error, urllib.request
from datetime import date

URL = "https://github.com/users/{login}/contributions"
LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]

# id="contribution-day-component-<weekday>-<week>" gives the grid position
# directly, so the calendar is rebuilt from GitHub's own layout rather than
# inferred from document order.
DAY_RE = re.compile(
    r'id="contribution-day-component-(?P<wd>\d+)-(?P<wk>\d+)"'
    r'[^>]*data-date="(?P<date>\d{4}-\d{2}-\d{2})"'
    r'[^>]*data-level="(?P<level>\d)"')
# The same attributes also appear in the other order depending on the response.
DAY_RE_ALT = re.compile(
    r'data-date="(?P<date>\d{4}-\d{2}-\d{2})"'
    r'[^>]*id="contribution-day-component-(?P<wd>\d+)-(?P<wk>\d+)"'
    r'[^>]*data-level="(?P<level>\d)"')
COUNT_RE = re.compile(r"(?:(\d+)|No) contributions? on", re.I)
TOTAL_RE = re.compile(r">\s*([\d,]+)\s+contributions?\s+in\s+the last year", re.I)


def fetch(login):
    req = urllib.request.Request(
        URL.format(login=login),
        headers={"X-Requested-With": "XMLHttpRequest",
                 "User-Agent": "github-slayrat (+https://github.com/chewrocca)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        sys.exit(f"contribution fetch failed for {login!r}: HTTP {e.code}")
    except urllib.error.URLError as e:
        sys.exit(f"contribution fetch failed for {login!r}: {e.reason}")


def parse(html):
    days = [m.groupdict() for m in DAY_RE.finditer(html)]
    if not days:
        days = [m.groupdict() for m in DAY_RE_ALT.finditer(html)]
    if not days:
        sys.exit("could not parse any day cells; GitHub's markup has changed")

    # Tooltips carry the per-day counts and appear in the same order as the cells.
    counts = [0 if m.group(1) is None else int(m.group(1))
              for m in COUNT_RE.finditer(html)]
    if len(counts) != len(days):
        counts = [None] * len(days)   # keep going; only the total is load-bearing

    weeks = {}
    for i, d in enumerate(days):
        wk, wd = int(d["wk"]), int(d["wd"])
        n = counts[i]
        if n is None:                 # fall back to something monotone in level
            n = int(d["level"])
        weeks.setdefault(wk, {})[wd] = {
            "date": d["date"],
            "contributionCount": n,
            "contributionLevel": LEVELS[int(d["level"])],
            "weekday": wd,
        }

    m = TOTAL_RE.search(html)
    total = int(m.group(1).replace(",", "")) if m else sum(
        v["contributionCount"] for w in weeks.values() for v in w.values())

    return {"data": {"user": {"contributionsCollection": {"contributionCalendar": {
        "totalContributions": total,
        "weeks": [{"contributionDays": [weeks[wk][wd] for wd in sorted(weeks[wk])]}
                  for wk in sorted(weeks)],
    }}}}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("login", help="GitHub username")
    ap.add_argument("-o", "--out", default="contrib.json")
    args = ap.parse_args()

    cal = parse(fetch(args.login))["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = sum(len(w["contributionDays"]) for w in cal["weeks"])
    if not cal["weeks"] or days < 300:
        sys.exit(f"calendar looks wrong: {len(cal['weeks'])} weeks, {days} days")

    payload = {"data": {"user": {"contributionsCollection": {"contributionCalendar": cal}}}}
    with open(args.out, "w") as f:
        json.dump(payload, f)
    active = sum(1 for w in cal["weeks"] for d in w["contributionDays"]
                 if d["contributionLevel"] != "NONE")
    print(f"{args.out}: {len(cal['weeks'])} weeks, {days} days, "
          f"{active} active, {cal['totalContributions']:,} contributions")


if __name__ == "__main__":
    main()
