"""What is coming, and what the companies themselves said to expect -> data/events.csv and data/guidance.csv.

No LLM and no forecasting. Everything is parsed from a document with plain patterns, so it can be re-checked by eye:
  * earnings dates   from the company's own announcement page (status 'confirmed') or a press article ('reported').
                     The stated weekday must match the date, otherwise the event is rejected.
  * price changes    'through <date> ... starting <date>' statements on the vendors' pricing-page snapshots.
  * promo endings    'promotional pricing is available at least through <date>'.
  * guidance         'Revenue is expected to be $X billion, plus or minus Y%' in earnings releases (Nvidia publishes this;
                     Alphabet and Apple do not, and we do not invent it).
Rows are replaced only for the documents this script processed; rows added by hand for other sources are kept.
"""
import csv
import re
from datetime import date, datetime, timedelta

import requests

from collectors.common import DATA, SOURCES_R, add_source, read_sources, today
from rag.ingest import html_to_text, read_pages

UA = "MIS556-student-research/1.0 (university course project; reads public announcements)"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# (company, URL, doc_type, tier, status, label) for pages that announce an earnings date
EARNINGS_PAGES = [
    ("Google", "https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Date-of-Third-Quarter-2026-Financial-Results-Conference-Call-2026-8tpGZsLS6v/default.aspx",
     "press_release", "1", "confirmed", "Alphabet Q3 2026 results and conference call"),
    ("Apple", "https://www.mactrast.com/2026/10/apple-to-announce-fiscal-q4-2026-earnings-on-november-2/",
     "news", "2", "reported", "Apple fiscal Q4 2026 results and conference call"),
]
EVENT_COLS = ["company", "event_type", "event_date", "description", "source_id", "status"]
GUIDE_COLS = ["company", "metric", "target_period", "value", "tolerance_pct", "unit", "source_id", "issued_date"]


def parse_event_date(text, default_year=None):
    """'on Wednesday, October 28, at 1:30pm Pacific' -> (date, 'Wed ... 1:30pm PT') or None. The weekday must match."""
    pat = r"\b(%s),? (%s) (\d{1,2})(?:,? (20\d\d))?" % ("|".join(WEEKDAYS), "|".join(MONTHS))
    for m in re.finditer(pat, text):
        wd, mon, day, year = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        year = int(year) if year else default_year
        if not year:
            continue
        try:
            d = date(year, MONTHS.index(mon) + 1, day)
        except ValueError:
            continue
        if WEEKDAYS[d.weekday()] != wd:  # a date whose weekday disagrees with the text is not trusted
            continue
        t = re.search(r"(\d{1,2}(?::\d{2})?\s?[ap]\.?m\.?)\s*(Pacific|PT|ET|Eastern|P\.T\.)?", text[m.end(): m.end() + 80], re.I)
        when = (t.group(1).replace(" ", "").replace(".", "") + " " + ("PT" if t.group(2) and t.group(2).upper()[0] in "PP" and "ASTERN" not in t.group(2).upper() else "ET" if t.group(2) else "")).strip() if t else ""
        return d, when
    return None


def _long_date(s):
    return datetime.strptime(s, "%B %d, %Y").date()


def price_change_events(text, company="Google", only_models=None):
    """Scheduled price changes on a pricing page: '$2.00 through November 30, 2026. $4.00 starting December 1, 2026.'"""
    out = []
    pat = re.compile(r"(Input price|Output price)[^$]{0,90}\$([\d.]+)[^$\n]{0,30}?through\s+([A-Z][a-z]+ \d{1,2}, 20\d\d)\.?\s*\$([\d.]+)[^$\n]{0,30}?starting\s+([A-Z][a-z]+ \d{1,2}, 20\d\d)")
    models = [(m.start(), m.group(1)) for m in re.finditer(r"\n\s*(gemini-[\w.\-]+)\s*\n", text)]
    seen = set()
    for m in pat.finditer(text):
        before = [name for pos, name in models if pos < m.start()]
        model = before[-1] if before else "a model"
        label, old, new, when = m.group(1).split()[0].lower(), float(m.group(2)), float(m.group(4)), m.group(5)
        if (only_models is not None and model not in only_models) or (model, label) in seen:
            continue  # the page repeats each model for Batch/Priority tiers; the first occurrence is the Standard price
        seen.add((model, label))
        try:
            d = _long_date(when)
        except ValueError:
            continue
        verb = "rises" if new > old else "falls"
        out.append((company, "price_change", d, "%s: %s price %s from $%.2f to $%.2f per 1M tokens" % (model, label, verb, old, new)))
    return out


def tracked_models(company):
    """Models we show in the pricing tab: scheduled changes are only reported for these."""
    p = DATA / "token_pricing.csv"
    return {r["model"] for r in csv.DictReader(open(p, encoding="utf-8-sig")) if r["company"] == company} if p.exists() else set()


def promo_events(text, company="OpenAI"):
    out = []
    for m in re.finditer(r"([A-Z][\w.\- ]{2,40}?)(?:’s|'s) promotional pricing is available at least through\s+([A-Z][a-z]+ \d{1,2}, 20\d\d)", text):
        try:
            d = _long_date(m.group(2))
        except ValueError:
            continue
        out.append((company, "promo_end", d, "%s promotional pricing is available at least through %s" % (m.group(1).strip(), m.group(2))))
    return out


def next_period(label):
    """FY2027Q2 -> FY2027Q3; FY2027Q4 -> FY2028Q1."""
    m = re.match(r"(FY|CY)(\d{4})Q([1-4])$", label)
    if not m:
        return None
    y, q = int(m.group(2)), int(m.group(3))
    return "%s%dQ%d" % (m.group(1), y + (q == 4), q % 4 + 1)


def guidance_rows(text, company, period, source_id, issued):
    """Numeric outlook stated in an earnings release (only what the text says)."""
    target, rows = next_period(period or ""), []
    if not target:
        return rows
    m = re.search(r"Revenue is expected to be \$([\d.,]+) (billion|million),? plus or minus ([\d.]+)%", text)
    if m:
        v = float(m.group(1).replace(",", "")) * (1000 if m.group(2) == "billion" else 1)
        rows.append([company, "revenue", target, "%g" % v, m.group(3), "USD_millions", source_id, issued])
    m = re.search(r"gross margins? (?:are|is) expected to be ([\d.]+)%[^.]{0,60}?plus or minus ([\d.]+) basis points", text)
    if m:
        rows.append([company, "gross_margin_pct", target, m.group(1), "%g" % (float(m.group(2)) / 100), "percent", source_id, issued])
    return rows


def _write(path, cols, new_rows, processed_sources):
    old = [r for r in csv.reader(open(path, encoding="utf-8-sig"))][1:] if path.exists() else []
    si = cols.index("source_id")
    kept = [r for r in old if r and r[si] not in processed_sources]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(sorted(kept + new_rows, key=lambda r: (r[cols.index("company")], r[2], r[3])))


def run():
    cutoff = date.today() - timedelta(days=7)
    events, processed = [], set()

    # earnings dates: official page, or a press article labelled 'reported'
    cached = {r["url"]: r for r in read_sources(SOURCES_R)}
    for company, url, dtype, tier, status, label in EARNINGS_PAGES:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            html = r.text
        except requests.RequestException as e:
            c = cached.get(url)
            if not (c and c["local_path"] and (DATA / c["local_path"]).exists()):
                print("  SKIP %s (%s)" % (url, type(e).__name__))
                continue
            html = (DATA / c["local_path"]).read_text(encoding="utf-8")
        text = html_to_text(html)
        published = (re.search(r"(20\d\d)-(\d\d)-(\d\d)", url) or re.search(r"/(20\d\d)/(\d\d)/", url) or [None])
        title = re.sub(r"\s+", " ", (re.search(r"<title[^>]*>(.*?)</title>", html, re.S) or [None, label])[1]).strip()[:140]
        pub_year = int(re.search(r"/(20\d\d)/", url).group(1)) if re.search(r"/(20\d\d)/", url) else date.today().year
        found = parse_event_date(text, default_year=pub_year)
        row = {"company": company, "title": title, "url": url, "publisher": re.sub(r"https?://(www\.)?", "", url).split("/")[0],
               "doc_type": dtype, "tier": tier, "published_date": today(), "retrieved_date": today(), "local_path": ""}
        sid = add_source(row, path=SOURCES_R, prefix="R")
        rel = "raw/%s/%s.txt" % (company, sid)
        (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        (DATA / rel).write_text("Source: %s\nRetrieved: %s\n\n%s" % (url, today(), text), encoding="utf-8")
        add_source({**row, "local_path": rel}, path=SOURCES_R, prefix="R")
        processed.add(sid)
        if found:
            d, when = found
            events.append([company, "earnings", d.isoformat(), "%s%s" % (label, " (%s)" % when if when else ""), sid, status])
            print("  %-7s %s  earnings %s %s [%s]" % (company, sid, d, when, status))
        else:
            print("  %-7s %s  no date found on the page" % (company, sid))

    # scheduled price changes + promotions from today's pricing-page snapshots
    for src in read_sources(SOURCES_R):
        if src["doc_type"] != "pricing_page" or not src["local_path"] or not (DATA / src["local_path"]).exists():
            continue
        text = "\n".join(t for _, t in read_pages(DATA / src["local_path"]))
        found = (price_change_events(text, src["company"], tracked_models("Google")) if src["company"] == "Google" else []) + \
                (promo_events(text, src["company"]) if src["company"] == "OpenAI" else [])
        processed.add(src["source_id"])
        for company, etype, d, desc in found:
            events.append([company, etype, d.isoformat(), desc, src["source_id"], "confirmed"])

    events = [e for e in events if date.fromisoformat(e[2]) >= cutoff]
    seen, uniq = set(), []
    for e in events:
        if tuple(e[:4]) not in seen:
            seen.add(tuple(e[:4]))
            uniq.append(e)
    _write(DATA / "events.csv", EVENT_COLS, uniq, processed)

    # numeric guidance stated in earnings releases
    fin = {}
    for r in csv.DictReader(open(DATA / "financials.csv", encoding="utf-8-sig")):
        if r["metric"] == "revenue":
            fin[r["source_id"]] = r["period"]
    guide, gproc = [], set()
    for src in read_sources():
        if src["doc_type"] != "earnings_release" or not src["local_path"]:
            continue
        text = "\n".join(t for _, t in read_pages(DATA / src["local_path"]))
        guide += guidance_rows(text, src["company"], fin.get(src["source_id"]), src["source_id"], src["published_date"])
        gproc.add(src["source_id"])
    _write(DATA / "guidance.csv", GUIDE_COLS, guide, gproc)
    print("events: %d rows | guidance: %d rows (companies: %s)" % (len(uniq), len(guide), sorted({g[0] for g in guide}) or "none"))


if __name__ == "__main__":
    run()
