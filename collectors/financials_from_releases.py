"""Extract quarterly figures from the downloaded earnings releases -> data/financials.csv.

This is the course's Assignment 2-b technique (LLM extraction from earnings documents) with
guards: the model must quote the exact text it read, the quote must exist in the document, and
the Verifier later re-checks every stored number against the same document.

Needs OPENAI_API_KEY. Uses the cheap extraction model. Re-runnable: rewrites the CSV.
Run after collectors.filings (the name sorts after it, so refresh --collect orders correctly).
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

from agents.verifier import _contains, _variants
from collectors.common import DATA, read_sources, today
from rag import config
from rag.ingest import read_pages

SEGMENT = {  # company -> (metric name, what to look for)
    "Google": ("cloud_revenue", "Google Cloud segment revenues"),
    "Nvidia": ("data_center_revenue", "Data Center revenue"),
    "Apple": ("services_revenue", "Services net sales"),
}
SCALE = {"billion": 1000.0, "million": 1.0, "thousand": 0.001, "units": 0.000001}
MAX_CHARS = 150_000


def fiscal_label(company, period_end):
    """The company's own fiscal label for a quarter ending on period_end (a date)."""
    m, y = period_end.month, period_end.year
    if company == "Google":      # calendar fiscal year
        return "FY%dQ%d" % (y, (m - 1) // 3 + 1)
    if company == "Apple":       # fiscal year ends late September
        q = {12: 1, 1: 1, 3: 2, 4: 2, 6: 3, 7: 3, 9: 4, 10: 4}.get(m)
        return "FY%dQ%d" % (y + 1 if m == 12 else y, q) if q else None  # the December quarter opens the NEXT fiscal year
    if company == "Nvidia":      # fiscal year ends late January, named for the year it ends in
        q = {4: 1, 5: 1, 7: 2, 8: 2, 10: 3, 11: 3, 1: 4, 2: 4}.get(m)
        return "FY%dQ%d" % (y if m in (1, 2) else y + 1, q) if q else None
    return None


def to_row(company, source_id, period_end, metric, item):
    """Convert one extracted metric to a financials.csv row, or return None if it is unusable."""
    try:
        value = float(item["value"])
        scale = item.get("scale", "million")
    except (KeyError, TypeError, ValueError):
        return None
    label = fiscal_label(company, period_end)
    if label is None or value <= 0:
        return None
    if scale == "per_share":
        val, unit = value, "USD_per_share"
    elif scale in SCALE:
        val, unit = round(value * SCALE[scale], 3), "USD_millions"
        if val < 1000:  # every tracked quarterly line is at least $1 billion, so this is a unit mix-up
            return None
    else:
        return None
    return [company, label, period_end.isoformat(), metric, ("%g" % val), unit, source_id, today()]


def _norm(s):
    """Letters and digits only, so table separators ('|', '$') and spacing can't cause a false mismatch.
    A fabricated number still can't match: every digit has to be present, in order."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def parse_reply(company, source_id, reply, doc_text, filed=None):
    """Turn the model's JSON reply into (rows, problems). Drops any metric that is neither quoted
    verbatim nor present as a number in the document. If `filed` (the filing date) is given, the
    quarter must have ended 0-120 days before it, which catches the model reading a prior-period column."""
    rows, problems = [], []
    try:
        data = json.loads(reply)
        period_end = date.fromisoformat(data["period_end"])
        metrics = data["metrics"]
    except (ValueError, KeyError, TypeError) as e:
        return [], ["%s: unusable reply (%s)" % (source_id, e)]
    if filed is not None and not 0 <= (filed - period_end).days <= 120:
        return [], ["%s: quarter end %s is not within 120 days before the filing date %s, whole document dropped" % (
            source_id, period_end, filed)]
    doc = _norm(doc_text)
    allowed = {"revenue", "net_income", "operating_income", "eps_diluted", SEGMENT[company][0]}
    for metric, item in metrics.items():
        if metric not in allowed or not isinstance(item, dict):
            continue
        row = to_row(company, source_id, period_end, metric, item)
        if row is None:
            problems.append("%s %s: unusable value %r" % (source_id, metric, item.get("value")))
            continue
        quote = _norm(str(item.get("quote", "")))
        quote_ok = len(quote) >= 8 and quote in doc
        # Models often paraphrase the quote while getting the number right (it came from a table), so
        # accept a metric when the quote is verbatim OR the number itself appears in the document.
        if not quote_ok and not any(_contains(doc_text, s) for s in _variants(row[4], row[5])):
            problems.append("%s %s: neither the quote nor the number %s was found in the document, dropped" % (
                source_id, metric, row[4]))
            continue
        rows.append(row)
    return rows, problems


def _prompt(company, text):
    seg, desc = SEGMENT[company]
    return (
        "Company: %s\nExtract results for the MOST RECENT QUARTER reported in this earnings release "
        "(not year-ago comparisons, not full-year or year-to-date figures, not guidance).\n"
        "Return JSON: {\"period_end\": \"YYYY-MM-DD\" (last day of the quarter), \"metrics\": {...}}.\n"
        "metrics may contain these keys: revenue (total revenue), net_income (the plain 'Net income' line, NOT "
        "'net income available to common stockholders' and NOT attributable-to subsets), operating_income, eps_diluted "
        "(diluted earnings per share), %s (%s). Tables are usually in MILLIONS: use scale \"million\" for a table "
        "figure like 112,193 and \"billion\" only when the text itself says 'billion'. Each value is "
        "{\"value\": number as written, \"scale\": \"billion\"|\"million\"|\"thousand\"|\"units\"|\"per_share\", "
        "\"quote\": a short VERBATIM excerpt from the document that contains the number}. "
        "Omit any metric the document does not state for that quarter.\n\nDocument:\n%s" % (company, seg, desc, text[:MAX_CHARS]))


def run(chat=None):
    from rag.llm import TRACKER, get_chat

    chat = chat or get_chat()
    if chat is None:
        print("financials_from_releases: no OPENAI_API_KEY, skipped")
        return
    out, problems = {}, []
    for src in read_sources():
        if src["doc_type"] != "earnings_release" or src["company"] not in SEGMENT or not src["local_path"]:
            continue
        text = " ".join(t for _, t in read_pages(DATA / src["local_path"]))
        reply = chat.complete(
            [{"role": "system", "content": "You extract figures from earnings releases. Use only the document. JSON only."},
             {"role": "user", "content": _prompt(src["company"], text)}],
            model=config.EXTRACT_MODEL, label="extract", json_mode=True)
        rows, probs = parse_reply(src["company"], src["source_id"], reply, text,
                                  filed=date.fromisoformat(src["published_date"]))
        problems += probs
        for r in rows:
            key = (r[0], r[1], r[3])  # one row per company/period/metric
            if key in out and out[key][4] != r[4]:
                problems.append("CONFLICT %s %s %s: %s says %s, %s says %s; kept the first" % (
                    r[0], r[1], r[3], out[key][6], out[key][4], r[6], r[4]))
                continue
            out.setdefault(key, r)
        print("  %s %s: %d metrics" % (src["company"], src["source_id"], len(rows)))
    with open(DATA / "financials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "period", "period_end", "metric", "value", "unit", "source_id", "as_of"])
        w.writerows(sorted(out.values(), key=lambda r: (r[0], r[2], r[3])))
    print("financials: %d rows | spend $%.4f" % (len(out), TRACKER.total))
    for p in problems:
        print("  note:", p)


if __name__ == "__main__":
    run()
