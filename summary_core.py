"""Building blocks shared by every summary source.

A source is a function that reads data (usually a file in one of the
emailer repos) and returns a *section*:

    {"ok": True, "as_of": "...", "note": "...", "blocks": [...], "text": [...]}

Blocks are generic, so the email and the dashboard can draw any section
without knowing where it came from:

    chart(series)          a line chart; series = [{"name", "points": [[date, value]]}]
    tiles(items)           small cards; item = {"label", "value", "change_pct", "period", "points"},
                           plus "note" shown in place of a missing change_pct
    table(columns, rows)   a table; column = {"label", "kind"} with kind
                           "text" | "num" | "change" | "link" (cell = [text, url])

Register a source with @source("id", "Title", icon="…"). Its options come
from the matching entry in config.json -> "summary_sources", so the same
function can be listed several times with different options.
"""
import csv
import io
import os
from collections import OrderedDict
from datetime import datetime, timedelta

import requests

OWNER = os.environ.get("GITHUB_OWNER") or "tuongphanbase"
TOKEN = os.environ.get("GH_READ_TOKEN") or ""
HISTORY_DAYS = 90  # how much history the charts get

SOURCES = OrderedDict()


def source(source_id, title, icon=""):
    """Register a summary source: fn(options) -> section dict."""
    def register(fn):
        SOURCES[source_id] = {"fn": fn, "title": title, "icon": icon}
        return fn
    return register


# --- Fetching -------------------------------------------------------------

def fetch_file(repo, path, ref="main", owner=None):
    """A file's text from GitHub, or None if it doesn't exist."""
    owner = owner or OWNER
    if TOKEN:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw+json"}
        resp = requests.get(url, headers=headers, params={"ref": ref}, timeout=30)
    else:
        resp = requests.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}", timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


def fetch_runs(repo, since, owner=None):
    """Workflow runs of a repo created at or after `since` (UTC datetime),
    newest first. Public repos need no token, but one raises the rate limit."""
    owner = owner or OWNER
    token = TOKEN or os.environ.get("GITHUB_TOKEN") or ""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/actions/runs", headers=headers,
                        params={"created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}", "per_page": 100},
                        timeout=30)
    resp.raise_for_status()
    return resp.json().get("workflow_runs", [])


# --- Series helpers ---------------------------------------------------------

def daily_last(points, days=HISTORY_DAYS):
    """[(datetime, value)] -> [["YYYY-MM-DD", value]]: the last value of each day, oldest first."""
    by_day = OrderedDict()
    for ts, value in sorted(points):
        by_day[ts.strftime("%Y-%m-%d")] = value
    return [[d, v] for d, v in list(by_day.items())[-days:]]


def pct_change(points, hours=24):
    """% change from the value ~`hours` before the latest point to the latest."""
    if len(points) < 2:
        return None
    latest_ts, latest = points[-1]
    earlier = [v for ts, v in points if ts <= latest_ts - timedelta(hours=hours)]
    base = earlier[-1] if earlier else None
    if not base:
        return None
    return round((latest - base) / base * 100, 2)


def parse_history_csv(text, key_col, value_col, time_col="timestamp", time_format="%Y-%m-%d %H:%M"):
    """CSV with time,key,value rows -> {key: [(datetime, float)]}."""
    series = OrderedDict()
    for row in csv.DictReader(io.StringIO(text)):
        try:
            ts = datetime.strptime(row[time_col], time_format)
            series.setdefault(row[key_col], []).append((ts, float(str(row[value_col]).replace(",", ""))))
        except (KeyError, ValueError, TypeError):
            continue
    return series


# --- Blocks -----------------------------------------------------------------

def chart(series, unit=""):
    return {"type": "chart", "unit": unit, "series": series}


def tiles(items, unit=""):
    return {"type": "tiles", "unit": unit, "items": items}


def table(columns, rows, caption=None):
    cols = [c if isinstance(c, dict) else {"label": c, "kind": "text"} for c in columns]
    return {"type": "table", "caption": caption, "columns": cols, "rows": rows}


def col(label, kind="text"):
    return {"label": label, "kind": kind}


def empty(reason):
    return {"ok": False, "reason": reason}
