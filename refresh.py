#!/usr/bin/env python3
"""Periodic refresh: collectors -> validate -> index -> verify -> change log.

    python refresh.py --sample              # dry run on the synthetic sample data
    python refresh.py --collect             # run collectors/*.py first (real data)
    python refresh.py --offline             # force the free hashing embedder

Writes runs/<real|sample>/<timestamp>.json and runs/<real|sample>/latest.json (what the
dashboard's Sources & Freshness tab shows), including what changed since the previous run.
"""
import argparse
import csv
import importlib
import json
import pkgutil
import subprocess
import sys
import time
from pathlib import Path

from agents.verifier import check_with_llm, verify
from rag import config
from rag.cli import build_index
from rag.ingest import load_sources
from rag.llm import TRACKER, get_chat

TABLES = ["financials", "stock_prices", "token_pricing", "partnerships", "events", "guidance"]


def run_collectors():
    """Call run() on every module in collectors/ (written by Manny; each rewrites its own CSVs)."""
    import collectors

    results = {}
    ORDER = ["filings", "prices", "financials_from_releases", "pricing_pages", "announcements", "market_news", "outlook"]  # later ones read earlier ones' output
    names = sorted((m.name for m in pkgutil.iter_modules(collectors.__path__)), key=lambda n: (ORDER.index(n) if n in ORDER else len(ORDER), n))
    for m in [type("M", (), {"name": n}) for n in names]:
        try:
            mod = importlib.import_module("collectors." + m.name)
            if hasattr(mod, "run"):
                mod.run()
                results[m.name] = "ok"
        except Exception as e:  # one broken collector must not stop the refresh
            results[m.name] = "FAILED: %s: %s" % (type(e).__name__, e)
    return results


def count_rows(base):
    out = {}
    for t in TABLES:
        p = Path(base) / (t + ".csv")
        out[t] = max(sum(1 for _ in open(p, encoding="utf-8-sig")) - 1, 0) if p.exists() else 0
    return out


def diff(prev, cur):
    if not prev:
        return ["first run"]
    ch = []
    for t in TABLES:
        d = cur["tables"][t] - prev["tables"].get(t, 0)
        if d:
            ch.append("%+d %s rows" % (d, t))
    new = sorted(set(cur["sources"]) - set(prev.get("sources", [])))
    gone = sorted(set(prev.get("sources", [])) - set(cur["sources"]))
    if new:
        ch.append("+%d sources: %s" % (len(new), ", ".join(new[:8]) + ("..." if len(new) > 8 else "")))
    if gone:
        ch.append("-%d sources: %s" % (len(gone), ", ".join(gone[:8])))
    if cur["index"].get("added") or cur["index"].get("removed"):
        ch.append("index: +%d / -%d chunks" % (cur["index"].get("added", 0), cur["index"].get("removed", 0)))
    pv, cv = prev.get("verification", {}), cur["verification"]
    if pv and pv.get("not_found") != cv["not_found"]:
        ch.append("verifier not_found: %s -> %s" % (pv.get("not_found"), cv["not_found"]))
    return ch or ["no changes"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="use data/sample")
    ap.add_argument("--collect", action="store_true", help="run collectors first")
    ap.add_argument("--offline", action="store_true", help="force the free hashing embedder")
    ap.add_argument("--brief", action="store_true", help="build the market brief even without an LLM key (facts only)")
    args = ap.parse_args()

    TRACKER.reset()
    base = config.data_dir(args.sample)
    runs = config.ROOT / "runs" / ("sample" if args.sample else "real")
    runs.mkdir(parents=True, exist_ok=True)
    prev = json.loads((runs / "latest.json").read_text()) if (runs / "latest.json").exists() else None

    collectors_result = run_collectors() if args.collect else "skipped"
    v = subprocess.run([sys.executable, str(config.ROOT / "validate_data.py"), "--dir", str(base)],
                       capture_output=True, text=True, cwd=config.ROOT)
    store, skipped = build_index(args.sample, args.offline)
    report = verify(base)
    chat = get_chat()
    if chat and report["summary"]["not_found"]:
        report = check_with_llm(report, base, chat)

    crosscheck_result = None
    if not args.sample:  # independent second source: SEC XBRL vs the LLM-extracted financials
        try:
            from agents.crosscheck import crosscheck

            crosscheck_result = crosscheck(base)
        except Exception as e:  # network or SEC outage must not break the refresh
            crosscheck_result = {"summary": {"error": "%s: %s" % (type(e).__name__, e)}, "findings": []}

    brief_result = None
    if chat is not None or args.brief:  # a sourced market synopsis (LLM if a key exists, facts-only otherwise)
        try:
            from agents.brief import build_brief

            b = build_brief(sample=args.sample)
            brief_result = {"llm": b["llm"], "bullets": sum(len(c["bullets"]) for c in b["companies"].values()) + len(b["overall"]), "dropped": len(b["dropped"])}
        except Exception as e:
            brief_result = {"error": "%s: %s" % (type(e).__name__, e)}

    cur = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "sample" if args.sample else "real",
        "collectors": collectors_result,
        "validation": {"ok": v.returncode == 0, "output": v.stdout.strip().splitlines()[-6:]},
        "tables": count_rows(base),
        "sources": sorted(load_sources(base)),
        "sources_without_document": skipped,
        "embedder": store.embedder_name,
        "index": store.stats,
        "verification": report["summary"],
        "problems": [f for f in report["findings"] if f["status"] != "confirmed"],
        "brief": brief_result,
        "crosscheck": crosscheck_result["summary"] if crosscheck_result else None,
        "crosscheck_problems": [f for f in crosscheck_result["findings"] if f["status"] == "differs"] if crosscheck_result else [],
        "cost": TRACKER.summary(),
    }
    cur["changes"] = diff(prev, cur)
    (runs / (time.strftime("%Y%m%d-%H%M%S") + ".json")).write_text(json.dumps(cur, indent=2))
    (runs / "latest.json").write_text(json.dumps(cur, indent=2))

    print("refresh %s (%s)" % (cur["timestamp"], cur["mode"]))
    print("  validation:", "OK" if cur["validation"]["ok"] else "FAILED (see output below)")
    if not cur["validation"]["ok"]:
        print("\n".join("    " + line for line in v.stdout.strip().splitlines()[-12:]))
    print("  tables:", cur["tables"])
    print("  embedder:", cur["embedder"], "| index:", cur["index"])
    print("  verification:", cur["verification"])
    if cur["brief"]:
        print("  market brief:", cur["brief"])
    if cur["crosscheck"]:
        print("  SEC XBRL cross-check:", cur["crosscheck"])
    print("  changes:", "; ".join(cur["changes"]))
    print("  cost: $%.4f of $%.2f cap" % (cur["cost"]["total_usd"], cur["cost"]["cap_usd"]))
    sys.exit(0 if cur["validation"]["ok"] else 1)


if __name__ == "__main__":
    main()
