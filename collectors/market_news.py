"""Recent news about the five companies -> dated snapshots (for the chatbot) + runs/<mode>/news.json (for the brief).

Sources, all public feeds:
  * official newsroom/blog feeds (Nvidia, Apple, Google, OpenAI)
  * Google News search RSS for every company (press headlines, and Anthropic's own posts via site search)
An item is TIER 1 when it was published on the company's (or a partner's) own domain, otherwise TIER 2 (press).
Each (company, tier) gets one snapshot document registered in sources_R.csv, so every brief claim can cite a source row.
Only headlines, dates, publishers and the feed's own summary are stored, never full articles.
"""
import html as _html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree as ET

import requests

from collectors.common import DATA, ROOT, SOURCES_R, add_source, today

UA = "MIS556-student-research/1.0 (university course project; reads public news feeds)"
OFFICIAL = {
    "Nvidia": [("https://nvidianews.nvidia.com/releases.xml", "NVIDIA Newsroom")],
    "Apple": [("https://www.apple.com/newsroom/rss-feed.rss", "Apple Newsroom")],
    "Google": [("https://blog.google/rss/", "Google blog")],
    "OpenAI": [("https://openai.com/news/rss.xml", "OpenAI News")],
}
PRESS_QUERY = {"Google": "Alphabet Google stock", "OpenAI": "OpenAI", "Anthropic": "Anthropic Claude", "Nvidia": "Nvidia stock", "Apple": "Apple AAPL stock"}
OWN_DOMAINS = ("anthropic.com", "openai.com", "nvidia.com", "apple.com", "blog.google", "google.com", "abc.xyz", "sec.gov",
               "microsoft.com", "aboutamazon.com", "amd.com", "oracle.com")
WINDOW_DAYS, MAX_PER_DOC = 10, 12


def _text(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None and (found.text or found.attrib):
            return (found.text or "").strip()
    return ""


def _strip(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_feed(xml_text):
    """RSS 2.0 or Atom -> [{title, link, date (aware datetime), summary, publisher, publisher_url}]."""
    root = ET.fromstring(xml_text)
    items = []
    for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
        ns = "{http://www.w3.org/2005/Atom}" if it.tag.startswith("{") else ""
        link = _text(it, "link")
        if ns and not link:
            l = it.find(ns + "link")
            link = l.attrib.get("href", "") if l is not None else ""
        raw = _text(it, "pubDate", ns + "published", ns + "updated", "{http://purl.org/dc/elements/1.1/}date")
        try:
            d = parsedate_to_datetime(raw) if raw and not raw[:4].isdigit() else datetime.fromisoformat(raw.replace("Z", "+00:00"))
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        src = it.find("source")
        items.append({"title": _strip(_text(it, "title", ns + "title")), "link": link, "date": d,
                      "summary": _strip(_text(it, "description", ns + "summary"))[:280],
                      "publisher": (src.text or "").strip() if src is not None else "", "publisher_url": src.attrib.get("url", "") if src is not None else ""})
    return items


def tier_for(item):
    host = urlparse(item["publisher_url"] or item["link"]).netloc.lower().replace("www.", "")
    return "1" if any(host == d or host.endswith("." + d) for d in OWN_DOMAINS) else "2"


def _get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
    r.raise_for_status()
    return r.text


def gather(company, cutoff):
    items = []
    for url, name in OFFICIAL.get(company, []):
        try:
            for it in parse_feed(_get(url)):
                it["publisher"] = it["publisher"] or name
                it["publisher_url"] = it["publisher_url"] or url
                items.append(it)
        except Exception as e:  # one dead feed must not stop the rest
            print("  skip official feed %s (%s)" % (name, type(e).__name__))
    queries = [PRESS_QUERY[company]] + (["site:anthropic.com/news"] if company == "Anthropic" else [])
    for q in queries:
        try:
            for it in parse_feed(_get("https://news.google.com/rss/search?q=%s+when:%dd&hl=en-US&gl=US&ceid=US:en" % (quote_plus(q), WINDOW_DAYS))):
                it["title"] = re.sub(r"\s+-\s+%s$" % re.escape(it["publisher"]), "", it["title"]) if it["publisher"] else it["title"]
                items.append(it)
        except Exception as e:
            print("  skip news search %r (%s)" % (q, type(e).__name__))
        time.sleep(0.8)
    seen, out = set(), []
    for it in sorted(items, key=lambda i: i["date"], reverse=True):
        key = re.sub(r"\W+", "", it["title"].lower())[:60]
        if it["date"] >= cutoff and key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def run(sample=False):
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    news = {}
    for company in PRESS_QUERY:
        items = gather(company, cutoff)
        news[company] = []
        for tier in ("1", "2"):
            chosen = [i for i in items if tier_for(i) == tier][:MAX_PER_DOC]
            if not chosen:
                continue
            kind = "official" if tier == "1" else "press"
            row = {"company": company, "title": "%s %s news, last %d days (captured %s)" % (company, kind, WINDOW_DAYS, today()),
                   "url": "https://news.google.com/search?q=%s#captured-%s-tier%s" % (quote_plus(PRESS_QUERY[company]), today(), tier),
                   "publisher": "Official newsrooms and own-site posts" if tier == "1" else "Press headlines via Google News",
                   "doc_type": "newsroom" if tier == "1" else "news", "tier": tier, "published_date": today(), "retrieved_date": today(), "local_path": ""}
            sid = add_source(row, path=SOURCES_R, prefix="R")
            rel = "raw/%s/%s-%s-news-t%s.txt" % (company, sid, today().replace("-", ""), tier)
            lines = ["Headlines about %s, captured %s (%s)." % (company, today(), "official/own-site posts" if tier == "1" else "press, tier 2")]
            for n, it in enumerate(chosen, 1):
                lines.append("[%d] %s | %s | %s\n    %s\n    %s" % (n, it["date"].date(), it["publisher"] or "?", it["title"], it["summary"], it["link"]))
                news[company].append({"id": "%s#%d" % (sid, n), "source_id": sid, "tier": tier, "date": str(it["date"].date()), "title": it["title"],
                                      "publisher": it["publisher"] or "?", "url": it["link"], "summary": it["summary"]})
            (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
            (DATA / rel).write_text("\n".join(lines), encoding="utf-8")
            add_source({**row, "local_path": rel}, path=SOURCES_R, prefix="R")
        print("  %-9s %d items (%d official, %d press)" % (company, len(news[company]), sum(i["tier"] == "1" for i in news[company]), sum(i["tier"] == "2" for i in news[company])))
    out = ROOT / "runs" / ("sample" if sample else "real")
    out.mkdir(parents=True, exist_ok=True)
    (out / "news.json").write_text(json.dumps({"captured": today(), "window_days": WINDOW_DAYS, "companies": news}, indent=2))
    return news


if __name__ == "__main__":
    run()
