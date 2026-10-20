"""Download recent SEC filings for Google (Alphabet), Nvidia and Apple into data/raw/<Company>/
and register each in data/sources/sources_A.csv, so the RAG index can read and cite them.

Per company: the latest 10-K, the latest 2 10-Qs, and the latest 4 earnings releases
(8-K item 2.02, Exhibit 99.1). Re-runnable: documents already registered are skipped.
Primary sources only (tier 1).
"""
import re
from pathlib import Path

from collectors.common import DATA, add_source, get, read_sources, sec_session, today

COMPANIES = {
    "Google": ("0001652044", "Alphabet Inc."),
    "Nvidia": ("0001045810", "NVIDIA Corporation"),
    "Apple": ("0000320193", "Apple Inc."),
}
N_10K, N_10Q, N_8K = 1, 2, 4


def _recent(session, cik):
    r = get(session, "https://data.sec.gov/submissions/CIK%s.json" % cik).json()["filings"]["recent"]
    return [dict(zip(r, vals)) for vals in zip(*r.values())]


def _exhibit_name(session, base, primary=""):
    """Find the earnings press release inside an 8-K filing folder. Most companies name it
    like Exhibit 99.1; some (Nvidia: q2fy27pr.htm) use their own naming, so fall back to
    press-release-style names, then to the largest non-index document."""
    items = get(session, base + "index.json").json()["directory"]["item"]
    docs = [(i["name"], int(i.get("size") or 0)) for i in items
            if i["name"].lower().endswith((".htm", ".html")) and i["name"] != primary
            and not re.match(r"r\d+\.htm$", i["name"].lower()) and "index" not in i["name"].lower()]
    for pattern in (r"ex-?99[-_.]?1|exhibit[-_]?99", r"(^|[^a-z])pr\.htm$|press|release|earnings"):
        for n, _ in docs:
            if re.search(pattern, n.lower()) and "commentary" not in n.lower():
                return n
    return max(docs, key=lambda d: d[1])[0] if docs else None


def _save(session, company, url, title, doc_type, filed, sources_by_url):
    have = sources_by_url.get(url)
    if have and have["local_path"] and (DATA / have["local_path"]).exists():
        return "skip (already have %s)" % have["source_id"]
    content = get(session, url).content  # download first: a failure must not leave a registered source
    row = {"company": company, "title": title, "url": url, "publisher": "SEC EDGAR", "doc_type": doc_type,
           "tier": "1", "published_date": filed, "retrieved_date": today()}
    sid = add_source(row)
    rel = "raw/%s/%s%s" % (company, sid, Path(url).suffix.lower() or ".htm")
    (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
    (DATA / rel).write_bytes(content)
    add_source({**row, "local_path": rel})
    return "saved %s (%d KB)" % (sid, (DATA / rel).stat().st_size // 1024)


def run():
    try:
        _run()
    except PermissionError as e:
        print("STOPPED: %s" % e)
        raise


def _run():
    s = sec_session()
    for company, (cik, legal) in COMPANIES.items():
        existing = {r["url"]: r for r in read_sources()}
        filings = _recent(s, cik)
        picks = (
            [f for f in filings if f["form"] == "10-K"][:N_10K]
            + [f for f in filings if f["form"] == "10-Q"][:N_10Q]
            + [f for f in filings if f["form"] == "8-K" and "2.02" in (f.get("items") or "")][:N_8K])
        for f in picks:
            base = "https://www.sec.gov/Archives/edgar/data/%d/%s/" % (int(cik), f["accessionNumber"].replace("-", ""))
            if f["form"] == "8-K":
                name = _exhibit_name(s, base, f["primaryDocument"])
                if not name:
                    print("%-7s 8-K %s: no Exhibit 99.1 found, skipped" % (company, f["filingDate"]))
                    continue
                title, dtype, url = "%s earnings release (8-K Ex. 99.1) filed %s" % (legal, f["filingDate"]), "earnings_release", base + name
            else:
                title = "%s %s for period ended %s (filed %s)" % (legal, f["form"], f["reportDate"], f["filingDate"])
                dtype, url = f["form"], base + f["primaryDocument"]
            print("%-7s %-16s %s" % (company, dtype, _save(s, company, url, title, dtype, f["filingDate"], existing)))


if __name__ == "__main__":
    try:
        run()
    except PermissionError:
        raise SystemExit(1)
