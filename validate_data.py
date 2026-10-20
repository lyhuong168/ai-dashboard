#!/usr/bin/env python3
"""Check the data files against contract.py. Standard library only.

Usage:
    python validate_data.py                  # check data/  (real data, strict)
    python validate_data.py --dir data/sample  # check the mock sample data

Run it before every push. Exit code 1 means at least one ERROR (fix before pushing).
Warnings are worth reading but do not block.
"""
import argparse
import csv
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import contract as C

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_RE = re.compile(r"^(FY|CY)\d{4}(Q[1-4])?$")
SOURCE_ID_RE = re.compile(r"^[A-Z]+-\d{3,}$")
SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, name, line, msg):
        self.errors.append("ERROR   %s%s - %s" % (name, ":%d" % line if line else "", msg))

    def warn(self, name, line, msg):
        self.warnings.append("warning %s%s - %s" % (name, ":%d" % line if line else "", msg))


def check_cell(kind, v):
    """Return an error message, or None if the value is fine."""
    if isinstance(kind, tuple):
        allowed = kind[1]
        return None if v in allowed else "'%s' is not one of %s" % (v, allowed)
    if kind == "str":
        return None
    if kind == "url":
        u = urlparse(v)
        return None if u.scheme == "https" and u.netloc else "must be a full https:// URL"
    if kind == "date":
        if not DATE_RE.match(v):
            return "'%s' must be YYYY-MM-DD" % v
        try:
            date.fromisoformat(v)
        except ValueError:
            return "'%s' is not a real date" % v
        return None
    if kind in ("float", "pos_float"):
        try:
            x = float(v)
        except ValueError:
            return "'%s' is not a number (no commas, $ or %% signs)" % v
        if not math.isfinite(x):
            return "'%s' is not a finite number" % v
        if kind == "pos_float" and x <= 0:
            return "must be greater than 0"
        return None
    if kind in ("int", "nonneg_int"):
        if not re.match(r"^-?\d+$", v):
            return "'%s' must be a whole number (no commas)" % v
        if kind == "nonneg_int" and int(v) < 0:
            return "must be 0 or more"
        return None
    if kind == "period":
        return None if PERIOD_RE.match(v) else "'%s' must look like FY2027Q1, CY2026Q3 or FY2026" % v
    if kind == "source_id":
        return None if SOURCE_ID_RE.match(v) else "'%s' must look like A-001" % v
    return "unknown kind %r in contract.py" % (kind,)


def read_table(path, schema, rep):
    """Read one CSV, check header and cells. Returns a list of row dicts (with _line)."""
    name = "/".join(path.parts[-2:]) if path.parent.name == "sources" else path.name
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = [h.strip() for h in (next(reader, None) or [])]
            raw = [(i, r) for i, r in enumerate(reader, start=2) if any(c.strip() for c in r)]
    except FileNotFoundError:
        rep.err(name, 0, "file is missing")
        return []
    cols = [c for c, _, _ in schema]
    if header != cols:
        rep.err(name, 1, "header must be exactly: %s" % ",".join(cols))
        return []
    rows = []
    for line, r in raw:
        if len(r) != len(cols):
            rep.err(name, line, "expected %d columns, found %d (unquoted comma?)" % (len(cols), len(r)))
            continue
        row = {c: v.strip() for c, v in zip(cols, r)}
        row["_line"] = line
        ok = True
        for col, kind, required in schema:
            v = row[col]
            if v == "":
                if required:
                    rep.err(name, line, "%s is required" % col)
                    ok = False
                continue
            msg = check_cell(kind, v)
            if msg:
                rep.err(name, line, "%s: %s" % (col, msg))
                ok = False
        if ok:
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="data", help="data folder to check (default: data)")
    args = ap.parse_args()

    base = Path(args.dir)
    sample_mode = base.name == "sample"
    rep = Report()
    summary = []

    # ---- sources (data/sources/sources_<TAG>.csv, one file per owner) ----
    sources = {}
    files = sorted((base / "sources").glob("*.csv"))
    if not files:
        rep.err("sources/", 0, "no sources_*.csv files found")
    for f in files:
        rows = read_table(f, C.SOURCES_SCHEMA, rep)
        tag = f.stem.split("_", 1)[1].upper() if "_" in f.stem else ""
        nm = "sources/" + f.name
        for r in rows:
            sid, ln = r["source_id"], r["_line"]
            if tag and not sid.startswith(tag + "-"):
                rep.err(nm, ln, "source_id %s must start with %s- in this file" % (sid, tag))
            if sid in sources:
                rep.err(nm, ln, "duplicate source_id %s" % sid)
            sources[sid] = r
            if r["doc_type"] in C.NEWS_ONLY_TIER2 and r["tier"] != "2":
                rep.err(nm, ln, "doc_type %s can only be tier 2" % r["doc_type"])
            if r["local_path"] and not (base / r["local_path"]).exists():
                rep.err(nm, ln, "local_path %s does not exist under %s/" % (r["local_path"], base))
            if r["retrieved_date"] < r["published_date"]:
                rep.warn(nm, ln, "retrieved_date is before published_date")
            if not sample_mode:
                if sid.startswith("SAMPLE-") or urlparse(r["url"]).netloc.endswith("example.com"):
                    rep.err(nm, ln, "sample/placeholder source in real data")
        summary.append(("sources/" + f.name, len(rows)))

    # ---- the four data tables ----
    tables = {}
    for fname, schema in C.SCHEMAS.items():
        rows = read_table(base / fname, schema, rep)
        tables[fname] = rows
        summary.append((fname, len(rows)))
        seen = {}
        for r in rows:
            ln = r["_line"]
            if "source_id" in r and r["source_id"] not in sources:
                rep.err(fname, ln, "source_id %s is not in any sources file (no source, no row)" % r["source_id"])
            key = tuple(r[k] for k in C.UNIQUE_KEYS.get(fname, []))
            if key:
                if key in seen:
                    rep.err(fname, ln, "duplicate row for %s (first on line %d)" % (key, seen[key]))
                seen[key] = ln

    # ---- table-specific rules ----
    for r in tables["financials.csv"]:
        m = r["metric"]
        if not SNAKE_RE.match(m):
            rep.err("financials.csv", r["_line"], "metric '%s' must be snake_case" % m)
        elif m not in C.RECOMMENDED_METRICS:
            rep.warn("financials.csv", r["_line"], "metric '%s' is not in the recommended list" % m)

    for r in tables["partnerships.csv"]:
        a, b = r["from_company"], r["to_company"]
        if a == b:
            rep.err("partnerships.csv", r["_line"], "from_company and to_company are the same")
        if a not in C.COMPANIES and b not in C.COMPANIES:
            rep.err("partnerships.csv", r["_line"], "at least one end must be one of %s" % C.COMPANIES)

    for r in tables["events.csv"]:
        src = sources.get(r["source_id"])
        if r["status"] == "confirmed" and src and src["tier"] != "1":
            rep.err("events.csv", r["_line"], "status 'confirmed' needs a tier-1 source (the company's own announcement); use 'reported' for press")

    for r in tables["token_pricing.csv"]:
        if r["output_usd_per_1m"] and float(r["output_usd_per_1m"]) < float(r["input_usd_per_1m"]):
            rep.warn("token_pricing.csv", r["_line"], "output price is lower than input price; double-check units (per 1M tokens)")

    # ---- coverage / freshness warnings (real data only) ----
    if not sample_mode:
        fin_cos = {r["company"] for r in tables["financials.csv"]}
        if tables["financials.csv"] and not {"Google", "Nvidia", "Apple"} <= fin_cos:
            rep.warn("financials.csv", 0, "missing companies: %s" % sorted({"Google", "Nvidia", "Apple"} - fin_cos))
        tp_cos = {r["company"] for r in tables["token_pricing.csv"]}
        if tables["token_pricing.csv"] and not {"Google", "OpenAI", "Anthropic"} <= tp_cos:
            rep.warn("token_pricing.csv", 0, "missing companies: %s" % sorted({"Google", "OpenAI", "Anthropic"} - tp_cos))
        sp = tables["stock_prices.csv"]
        if sp:
            if not any(s["doc_type"] == "market_data" for s in sources.values()):
                rep.warn("stock_prices.csv", 0, "add a sources row with doc_type market_data describing where prices came from")
            if max(r["date"] for r in sp) < (date.today() - timedelta(days=10)).isoformat():
                rep.warn("stock_prices.csv", 0, "latest price is more than 10 days old")

    for name, n in summary:
        print("  %-28s %d row%s" % (name, n, "" if n == 1 else "s"))
    for line in rep.warnings + rep.errors:
        print(line)
    print("\n%s: %d error(s), %d warning(s)" % ("FAILED" if rep.errors else "OK", len(rep.errors), len(rep.warnings)))
    sys.exit(1 if rep.errors else 0)


if __name__ == "__main__":
    main()
