"""Shared helpers for the collectors: polite SEC session + idempotent source registry."""
import csv
import os
import time
from datetime import date
from pathlib import Path

import requests

import contract as C

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCES_A = DATA / "sources" / "sources_A.csv"
SOURCES_R = DATA / "sources" / "sources_R.csv"
COLS = [c for c, _, _ in C.SOURCES_SCHEMA]


def sec_session():
    """SEC requires a descriptive User-Agent with contact info: set SEC_USER_AGENT in .env."""
    ua = os.getenv("SEC_USER_AGENT")
    if not ua:
        print("note: SEC_USER_AGENT is not set in .env; using a generic agent. Add your name + email there.")
    s = requests.Session()
    s.headers["User-Agent"] = ua or "MIS556-student-project (set SEC_USER_AGENT in .env)"
    return s


def get(session, url):
    time.sleep(0.2)  # SEC fair-access limit is 10 requests/second; stay well under
    r = session.get(url, timeout=90)
    if r.status_code == 403:
        raise PermissionError(
            "SEC returned 403 Forbidden. The SEC requires a real contact in the User-Agent. "
            "Add this line to .env:  SEC_USER_AGENT=Your Name your.email@school.edu")
    r.raise_for_status()
    return r


def read_sources(path=SOURCES_A):
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def add_source(row, path=SOURCES_A, prefix="A"):
    """Add a source row (dict of contract columns except source_id). Idempotent by URL:
    an existing row is refreshed and its id reused. Returns the source_id."""
    rows = read_sources(path)
    for r in rows:
        if r["url"] == row["url"]:
            r.update({k: v for k, v in row.items() if k != "local_path" or v})
            _write(rows, path)
            return r["source_id"]
    nums = [int(r["source_id"].split("-")[1]) for r in rows if r["source_id"].startswith(prefix + "-")]
    sid = "%s-%03d" % (prefix, max(nums, default=0) + 1)
    rows.append({"source_id": sid, **{c: row.get(c, "") for c in COLS if c != "source_id"}})
    _write(rows, path)
    return sid


def _write(rows, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLS} for r in rows)


def today():
    return date.today().isoformat()
