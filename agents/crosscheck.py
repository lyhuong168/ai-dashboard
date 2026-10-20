"""Independent cross-check: compare financials.csv (extracted by an LLM from earnings releases)
with the SEC's structured XBRL "company facts" for the same quarter.

Statuses per row:
  agrees                 the SEC's XBRL value for that quarter matches within tolerance
  differs                the SEC's value is different  <- investigate
  no_independent_source  XBRL has no discrete value for that quarter/metric (e.g. Q4, segment lines)
Two unrelated pipelines (LLM reading prose vs SEC's machine-readable filing data) agreeing is much
stronger evidence than the number merely appearing in the document it was read from.
"""
import csv
from datetime import date
from pathlib import Path

CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}


def quarter_value(facts, metric, period_end):
    """(value in USD millions or USD/share, concept, accession) for the 3-month period ending
    period_end, or None. Uses the most recently filed value if there are several."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in CONCEPTS.get(metric, []):
        for unit, entries in gaap.get(concept, {}).get("units", {}).items():
            best = None
            for e in entries:
                if e.get("end") != period_end or "start" not in e:
                    continue
                days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
                if 80 <= days <= 100 and (best is None or e.get("filed", "") > best.get("filed", "")):
                    best = e
            if best:
                return best["val"] / (1.0 if unit == "USD/shares" else 1e6), concept, best.get("accn", "")
    return None


def compare(rows, facts_by_company, tol=0.005):
    """rows: dicts from financials.csv. facts_by_company: {company: companyfacts JSON or None}."""
    findings = []
    for r in rows:
        label = "%s %s %s = %s" % (r["company"], r["period"], r["metric"], r["value"])
        facts = facts_by_company.get(r["company"])
        hit = quarter_value(facts, r["metric"], r["period_end"]) if facts else None
        if hit is None:
            status, detail = "no_independent_source", "no discrete XBRL value for %s ending %s" % (r["metric"], r["period_end"])
        else:
            ours, theirs = float(r["value"]), hit[0]
            off = abs(ours - theirs) / abs(theirs) if theirs else float("inf")
            status = "agrees" if off <= tol else "differs"
            detail = "SEC XBRL (%s, %s) = %s" % (hit[1], hit[2], ("%.4g" % theirs) if abs(theirs) < 1000 else format(theirs, ",.1f"))
        findings.append({"row": label, "source_id": r["source_id"], "status": status, "detail": detail})
    return {"findings": findings,
            "summary": {s: sum(f["status"] == s for f in findings) for s in ("agrees", "differs", "no_independent_source")}}


def fetch_facts(companies):
    """Download company facts for each company (needs SEC_USER_AGENT in .env). {company: json or None}."""
    from collectors.common import get, sec_session
    from collectors.filings import COMPANIES

    s, out = sec_session(), {}
    for c in companies:
        if c in COMPANIES:
            out[c] = get(s, "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % COMPANIES[c][0]).json()
    return out


def crosscheck(base, facts_by_company=None):
    """Cross-check base/financials.csv. Fetches SEC facts unless supplied (tests supply them)."""
    p = Path(base) / "financials.csv"
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig"))) if p.exists() else []
    if facts_by_company is None:
        facts_by_company = fetch_facts({r["company"] for r in rows})
    return compare(rows, facts_by_company)
