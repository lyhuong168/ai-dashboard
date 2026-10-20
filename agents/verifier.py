"""Verifier: cross-checks the CSV numbers against the source documents they cite.

Deterministic and free. For every financials / token_pricing row it looks for the stated
value in the cited document's text (allowing common formats: 1,111.1 / 1111.1 / $1.1 billion).
Statuses:
  confirmed    the value appears in the cited document
  not_found    the document exists but does not contain the value  <- investigate
  no_document  the source has no local file, so it can't be checked
An optional LLM pass (check_with_llm) re-examines not_found rows when a key is available.
"""
import csv
import re
from datetime import date
from pathlib import Path

from rag.ingest import load_sources, read_pages


def _comma(s):
    ip, _, fp = s.partition(".")
    return re.sub(r"(?<=\d)(?=(\d{3})+$)", ",", ip) + ("." + fp if fp else "")


def _variants(value, unit):
    """Strings that could legitimately represent `value` in a document. Uses the value as
    written plus comma and scale forms, never rounded guesses. Dollar prices need a '$'."""
    v = float(value)
    nums = {value.strip(), _comma(value.strip()), "%g" % v, _comma("%g" % v)}
    if unit == "USD_millions":  # 44100 million is also "44.1 billion"
        nums |= {"%.1f" % (v / 1000.0), "%.2f" % (v / 1000.0), "%g" % (v / 1000.0)}
    if unit in ("USD_per_share", "usd"):  # stored as 1.3 but printed as $1.30
        nums.add("%.2f" % v)
    if unit == "usd":
        words = set()
        if v >= 1e6:
            words.add("%g million" % (v / 1e6))
        if v >= 1e9:
            words.add("%g billion" % (v / 1e9))
            words.add("%gB" % (v / 1e9))
        if v >= 1e6:
            words.add("%gM" % (v / 1e6))
        return {"$" + n for n in nums | words}
    return {n for n in nums if n not in ("0", "0.0")}


def _doc_text(base, source):
    lp = source.get("local_path")
    if not lp or not (Path(base) / lp).exists():
        return None
    return " ".join(t for _, t in read_pages(Path(base) / lp))


def _find(text, needle):
    return re.search(r"(?<![\d.,])%s(?![\d]|,\d)" % re.escape(needle), text)


def _contains(text, needle):
    return _find(text, needle) is not None


def _snippet(text, match, before=170, after=90):
    """The words around a confirmed number, quotable as evidence. Table cells ('a | | b') become 'a · b'."""
    lo, hi = max(0, match.start() - before), min(len(text), match.end() + after)
    s = text[lo:hi]
    s = re.sub(r"\s*(?:\|\s*)+", " · ", s)
    s = re.sub(r"\s+", " ", s).strip(" ·")
    s = s.replace("$ · ", "$").replace(" · %", "%").replace("( · ", "(").replace(" · )", ")")  # signs sit in their own cells
    if lo > 0:
        s = s.split(" ", 1)[-1]  # drop the cut-off first word
    if hi < len(text):
        s = s.rsplit(" ", 1)[0]
    return ("…" if lo > 0 else "") + s.strip(" ·") + ("…" if hi < len(text) else "")


def _evidence(text, value, unit):
    """Snippet around the longest matching form of `value` (most specific first), or None."""
    for v in sorted(_variants(value, unit), key=len, reverse=True):
        m = _find(text, v)
        if m:
            return _snippet(text, m)
    return None


def _rows(base, name):
    p = Path(base) / name
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def verify(base):
    """Return {"findings": [...], "summary": {...}} for the data folder `base`."""
    base = Path(base)
    sources = load_sources(base)
    cache, findings = {}, []

    def doc(sid):
        if sid not in cache:
            cache[sid] = _doc_text(base, sources[sid]) if sid in sources else None
        return cache[sid]

    def check(table, row, label, values):
        sid = row["source_id"]
        text = doc(sid)
        evidence = None
        if sid not in sources:
            status, detail = "no_document", "source_id not in sources"
        elif text is None:
            status, detail = "no_document", "no local document for %s" % sid
        else:
            missing = [lab for lab, val, unit in values if val and not any(_contains(text, s) for s in _variants(val, unit))]
            status = "confirmed" if not missing else "not_found"
            detail = "all values found in %s" % sid if not missing else "not in document: %s" % ", ".join(missing)
            if not missing:  # quote where the (first) value was found, so answers can cite the passage itself
                evidence = next((e for e in (_evidence(text, val, unit) for _, val, unit in values if val) if e), None)
        findings.append({"table": table, "row": label, "source_id": sid, "status": status, "detail": detail,
                         "tier": sources.get(sid, {}).get("tier", ""), "evidence": evidence})

    for r in _rows(base, "financials.csv"):
        check("financials", r, "%s %s %s = %s %s" % (r["company"], r["period"], r["metric"], r["value"], r["unit"]),
              [("value " + r["value"], r["value"], r["unit"])])
    for r in _rows(base, "token_pricing.csv"):
        check("token_pricing", r, "%s %s in $%s / out $%s" % (r["company"], r["model"], r["input_usd_per_1m"], r["output_usd_per_1m"]),
              [("input " + r["input_usd_per_1m"], r["input_usd_per_1m"], "usd"),
               ("output " + r["output_usd_per_1m"], r["output_usd_per_1m"], "usd")])
    for r in _rows(base, "partnerships.csv"):
        vals = [("amount %s" % r["amount_usd"], r["amount_usd"], "usd")] if r.get("amount_usd") else []
        if vals:
            check("partnerships", r, "%s -> %s (%s)" % (r["from_company"], r["to_company"], r["relationship_type"]), vals)

    for r in _rows(base, "guidance.csv"):
        check("guidance", r, "%s %s %s guidance = %s %s" % (r["company"], r["target_period"], r["metric"], r["value"], r["unit"]),
              [("value " + r["value"], r["value"], r["unit"])])
    for r in _rows(base, "events.csv"):
        sid, text = r["source_id"], doc(r["source_id"])
        d = date.fromisoformat(r["event_date"])
        names = {"%s %d" % (m, d.day) for m in (d.strftime("%B"), d.strftime("%b"), d.strftime("%b."))} | {"%d %s" % (d.day, d.strftime("%B"))}
        if sid not in sources or text is None:
            status, detail = "no_document", "no local document for %s" % sid
        else:
            status = "confirmed" if any(n in text for n in names) else "not_found"
            detail = "date %s found in %s" % (r["event_date"], sid) if status == "confirmed" else "date %s not in document" % r["event_date"]
        findings.append({"table": "events", "row": "%s %s on %s" % (r["company"], r["event_type"], r["event_date"]), "source_id": sid,
                         "status": status, "detail": detail, "tier": sources.get(sid, {}).get("tier", ""), "evidence": None})

    summary = {s: sum(f["status"] == s for f in findings) for s in ("confirmed", "not_found", "no_document")}
    summary["checked"] = len(findings)
    summary["tier2_rows"] = sum(f["tier"] == "2" for f in findings)
    return {"findings": findings, "summary": summary}


def check_with_llm(report, base, chat):
    """Second opinion on not_found rows (formats the string match missed, e.g. 'forty-four billion')."""
    from rag import config

    base = Path(base)
    sources = load_sources(base)
    for f in report["findings"]:
        if f["status"] != "not_found":
            continue
        text = _doc_text(base, sources[f["source_id"]])[:12000]
        reply = chat.complete(
            [{"role": "system", "content": "Answer only YES or NO, then one short reason."},
             {"role": "user", "content": "Document:\n%s\n\nDoes this document state this figure (any format or unit)? %s"
                                         % (text, f["row"])}],
            model=config.EXTRACT_MODEL, label="verify")
        f["llm_opinion"] = reply.strip()
        if reply.strip().upper().startswith("YES"):
            f["status"], f["detail"] = "confirmed", "confirmed by LLM second pass"
    report["summary"] = {**{s: sum(f["status"] == s for f in report["findings"]) for s in ("confirmed", "not_found", "no_document")},
                         "checked": len(report["findings"]), "tier2_rows": report["summary"]["tier2_rows"]}
    return report
