"""Official announcements -> RAG documents + data/partnerships.csv.

1. fetch(): download each OFFICIAL announcement page in SEED (company newsrooms, SEC-style press releases, partner
   blogs), save a dated text snapshot to data/raw/<Company>/ and register it in data/sources/sources_R.csv (tier 1).
   These snapshots are what lets the chatbot answer questions about OpenAI and Anthropic (no SEC filings exist).
2. extract(): an LLM lists the relationships each page STATES. A relationship is kept only if its supporting quote is
   verbatim in the page, or its dollar amount appears in the page and both parties are named in it. Pages that refuse
   scripts (HTTP 403) are skipped and reported; we do not work around the block.

Rows written by this script have source_ids starting with R-; rows from other people (A-/B-) are left untouched.
Needs OPENAI_API_KEY for step 2.
"""
import csv
import json
import re
import time
from datetime import date

import requests

from agents.verifier import _contains, _variants
from collectors.common import DATA, SOURCES_R, add_source, read_sources, today
from rag import config
from rag.ingest import html_to_text

# (company the page is mainly about, URL). Found via web search of the vendors' own newsrooms; every one is a primary source.
SEED = [
    ("Anthropic", "https://www.anthropic.com/news/anthropic-amazon-compute"),
    ("Anthropic", "https://www.aboutamazon.com/news/company-news/amazon-invests-additional-5-billion-anthropic-ai"),
    ("Anthropic", "https://www.anthropic.com/news/expanding-our-use-of-google-cloud-tpus-and-services"),
    ("Anthropic", "https://www.googlecloudpresscorner.com/2025-10-23-Anthropic-to-Expand-Use-of-Google-Cloud-TPUs-and-Services"),
    ("Anthropic", "https://www.googlecloudpresscorner.com/2026-04-06-Anthropic-Expands-Use-of-Google-Cloud-and-TPUs"),
    ("Anthropic", "https://www.anthropic.com/news/google-broadcom-partnership-compute"),
    ("Anthropic", "https://www.anthropic.com/news/microsoft-nvidia-anthropic-announce-strategic-partnerships"),
    ("Anthropic", "https://blogs.nvidia.com/blog/microsoft-nvidia-anthropic-announce-partnership"),
    ("Anthropic", "https://www.anthropic.com/news/series-h"),
    ("OpenAI", "https://blogs.microsoft.com/blog/2025/10/28/the-next-chapter-of-the-microsoft-openai-partnership/"),
    ("OpenAI", "https://blogs.microsoft.com/blog/2026/04/27/the-next-phase-of-the-microsoft-openai-partnership/"),
    ("OpenAI", "https://investor.nvidia.com/news/press-release-details/2025/OpenAI-and-NVIDIA-Announce-Strategic-Partnership-to-Deploy-10-Gigawatts-of-NVIDIA-Systems/"),
    ("OpenAI", "https://ir.amd.com/news-events/press-releases/detail/1260/amd-and-openai-announce-strategic-partnership-to-deploy-6-gigawatts-of-amd-gpus"),
    ("OpenAI", "https://openai.com/index/five-new-stargate-sites/"),
    ("OpenAI", "https://openai.com/index/stargate-advances-with-partnership-with-oracle/"),
    ("OpenAI", "https://openai.com/index/openai-and-apple-announce-partnership/"),
    ("Apple", "https://www.apple.com/newsroom/2024/06/introducing-apple-intelligence-for-iphone-ipad-and-mac/"),
    ("Google", "https://blog.google/company-news/inside-google/company-announcements/joint-statement-google-apple/"),
]
UA = "MIS556-student-research/1.0 (university course project; reads public announcements)"
COLS = ["from_company", "to_company", "relationship_type", "description", "amount_usd", "date", "source_id", "confidence"]
TYPES = {"investment", "supply", "cloud", "distribution", "competition", "financing"}
GENERIC = re.compile(r"(?i)customers|users|advertisers|developers|enterprises|consumers|publishers|merchants|partners$|shareholders")
SUPPLY_KW = ["TSMC", "Taiwan Semiconductor", "Samsung", "SK hynix", "SK Hynix", "Micron", "Foxconn", "Hon Hai", "Pegatron", "Wistron", "Quanta", "foundr"]
FIVE = {"Google", "OpenAI", "Anthropic", "Nvidia", "Apple"}
ALIASES = {"alphabet": "Google", "google cloud": "Google", "nvidia": "Nvidia", "openai": "OpenAI", "anthropic": "Anthropic", "apple": "Apple", "google": "Google",
           "amazon web services": "Amazon", "aws": "Amazon"}
MAX_CHARS = 60_000


CLOUD_PROVIDERS = {"Amazon", "Microsoft", "Google", "Oracle", "CoreWeave"}
PRODUCT_MAKERS = {"OpenAI", "Anthropic", "Google"}
INTEGRATORS = {"Apple", "Microsoft", "Amazon"}
INVESTORS = {"Amazon", "Microsoft", "Nvidia", "Google", "SoftBank", "Apple"}
INVESTEES = {"OpenAI", "Anthropic"}
FILING_KEYWORDS = ["TSMC", "Taiwan Semiconductor", "Samsung", "SK hynix", "Micron", "Foxconn", "Hon Hai", "Pegatron", "Wistron",
                   "Quanta", "OpenAI", "Anthropic", "CoreWeave", "Oracle", "Microsoft Azure", "Amazon Web Services", "strategic investment",
                   "Gemini", "ChatGPT", "foundry", "foundries"]


def fix_direction(a, b, typ):
    """The model sometimes reverses an edge; fix the unambiguous cases (provider -> customer, maker -> integrator, investor -> investee)."""
    if typ == "cloud" and a not in CLOUD_PROVIDERS and b in CLOUD_PROVIDERS:
        return b, a
    if typ == "distribution" and a in INTEGRATORS and a not in PRODUCT_MAKERS and b in PRODUCT_MAKERS:
        return b, a
    if typ == "investment" and a in INVESTEES and b in INVESTORS:
        return b, a
    return a, b


HARDWARE = {"Nvidia", "AMD", "Broadcom", "Intel", "TSMC", "Samsung", "SK Hynix", "Micron"}
INVEST_WORDS = ("invest", "stake", "shareholder", "funding", "raised", "raise", "equity", "valuation")


def normalize(a, b, typ):
    """Fix unambiguous label/direction mistakes. Returns (from, to, type)."""
    if typ == "cloud" and (a in HARDWARE or b in HARDWARE):          # chips are supply, not cloud
        typ = "supply"
        return (b, a, typ) if b in HARDWARE and a not in HARDWARE else (a, b, typ)
    if typ == "investment" and a in INVESTEES and b in {"Oracle", "CoreWeave"}:   # buying compute is cloud, provider -> customer
        return b, a, "cloud"
    a, b = fix_direction(a, b, typ)
    return a, b, typ


TYPE_SYNONYMS = {"guarantee": "financing", "guarantees": "financing", "loan": "financing", "credit": "financing", "warrant": "financing",
                 "credit support": "financing", "partnership": "distribution", "compute": "cloud", "hardware": "supply", "competitor": "competition"}
NAME_ALIASES = {"TSMC": ["tsmc", "taiwan semiconductor"], "Hon Hai": ["hon hai", "foxconn"], "SK Hynix": ["sk hynix", "hynix"],
                "Google": ["google", "alphabet"], "Amazon": ["amazon", "aws"], "Microsoft": ["microsoft", "azure"], "Micron": ["micron"],
                "Samsung": ["samsung"], "Intel": ["intel"], "Broadcom": ["broadcom"], "Cisco": ["cisco"], "Nvidia": ["nvidia"], "Apple": ["apple"]}


def _aliases(name):
    key = next((k for k in NAME_ALIASES if k.lower() in name.lower() or name.lower() in k.lower()), None)
    return NAME_ALIASES[key] if key else [re.split(r"[ ,]", name.lower())[0]]


def cooccur(doc_text, a, b, filer=None):
    """True if some paragraph names both parties: a looser check for paraphrased quotes, used only when no quote or amount matched.
    In an SEC filing the filer writes 'we', so the filer counts as present in every paragraph."""
    for para in re.split(r"\n+", doc_text):
        low = para.lower()
        if all(n == filer or any(x in low for x in _aliases(n)) for n in (a, b)):
            return True
    return False


def canon(name):
    return ALIASES.get(str(name).strip().lower(), str(name).strip())


def page_date(html, url):
    """Best-effort publication date (YYYY-MM-DD) from meta tags, JSON-LD, the URL, or visible text; None if unknown."""
    for pat in (r'article:published_time"[^>]*content="(\d{4}-\d{2}-\d{2})', r'content="(\d{4}-\d{2}-\d{2})[^"]*"[^>]*property="article:published_time',
                r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    m = re.search(r"/(20\d\d)/(\d\d)/(\d\d)/", url) or re.search(r"(20\d\d)-(\d\d)-(\d\d)", url)
    if m:
        return "-".join(m.groups())
    m = re.search(r"/newsroom/(20\d\d)/(\d\d)/", url)
    mo = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    t = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}),? (20\d\d)\b", html_to_text(html)[:6000])
    if t:
        return "%s-%02d-%02d" % (t.group(3), mo[t.group(1).lower()], int(t.group(2)))
    return ("%s-%s-01" % m.groups()) if m else None


def doc_type_for(url):
    return "press_release" if any(k in url for k in ("press", "investor.", "ir.amd", "aboutamazon.com/news")) else \
           "newsroom" if "newsroom" in url else "blog"


def fetch():
    """Snapshot every reachable page. Returns [(company, source_id, text, published_date)]."""
    out = []
    cached = {r["url"]: r for r in read_sources(SOURCES_R)}
    for company, url in SEED:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            failure = None if r.status_code == 200 else "HTTP %d" % r.status_code
        except requests.RequestException as e:
            r, failure = None, type(e).__name__
        if failure:
            c = cached.get(url)
            if c and c["local_path"] and (DATA / c["local_path"]).exists():  # a flaky 403 must not discard evidence we already hold
                body = (DATA / c["local_path"]).read_text(encoding="utf-8").split("\n\n", 1)[-1]
                print("  CACHED   %s  %s (%s now; using the saved snapshot)" % (c["source_id"], c["published_date"], failure))
                out.append((company, c["source_id"], body, c["published_date"]))
            else:
                print("  SKIP %s (%s: not fetchable by script)" % (url, failure))
            continue
        html = r.text
        title = re.sub(r"\s+", " ", (re.search(r"<title[^>]*>(.*?)</title>", html, re.S) or [None, url])[1]).strip()[:140]
        pub = page_date(html, r.url) or today()
        text = html_to_text(html)
        host = re.sub(r"^www\.", "", re.sub(r"https?://", "", r.url).split("/")[0])
        row = {"company": company, "title": title, "url": r.url, "publisher": host, "doc_type": doc_type_for(r.url), "tier": "1",
               "published_date": pub, "retrieved_date": today(), "local_path": ""}
        sid = add_source(row, path=SOURCES_R, prefix="R")
        rel = "raw/%s/%s.txt" % (company, sid)
        (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        (DATA / rel).write_text("Source: %s\nRetrieved: %s\nPublisher: %s\n\n%s" % (r.url, today(), host, text), encoding="utf-8")
        add_source({**row, "local_path": rel}, path=SOURCES_R, prefix="R")
        print("  %-9s %s  %s  %s" % (company, sid, pub, title[:70]))
        out.append((company, sid, text, pub))
        time.sleep(1.0)  # be polite
    return out


MODES = {
    "filing_supply": ("This is an EXCERPT FROM AN SEC FILING by one of the five companies. Report ONLY: named suppliers, foundries and "
                      "memory makers that supply the filer (supply: from = supplier, to = the filer); named investments, guarantees or "
                      "credit support given to other companies (investment or financing); and named cloud or distribution partners. "
                      "Do NOT report competitors.\n"),
    "filing_competition": ("This is an EXCERPT FROM AN SEC FILING. Report ONLY companies the filing says it competes with "
                           "(type competition, from = the filer). Never report anything else.\n"),
}


def _prompt(text, mode=""):
    return MODES.get(mode, "") + (
        "Below is an OFFICIAL announcement page. List the business relationships it STATES that involve at least one of: "
        "Google (Alphabet), OpenAI, Anthropic, Nvidia, Apple. Relationship types and direction: investment (from = investor, "
        "to = company invested in), supply (from = supplier of chips/hardware, to = buyer), cloud (from = cloud/compute provider, "
        "to = customer), distribution (from = provider of a model/product, to = company that integrates or distributes it), "
        "competition (only if the page itself says they compete).\n"
        "Return JSON: {\"edges\": [{\"from\": name, \"to\": name, \"type\": one of the types, \"description\": ONE factual sentence "
        "of at most 200 characters using only this page, \"amount_usd\": a number in US dollars or null (only if the page states a "
        "dollar figure for THIS relationship; 'up to' amounts are fine), \"quote\": a short VERBATIM excerpt from the page that supports it}]}. "
        "Use the names Google, OpenAI, Anthropic, Nvidia, Apple for those five and the page's own names for others (Microsoft, "
        "Amazon, Oracle, SoftBank, AMD, Broadcom). At most 8 edges. No speculation, nothing the page does not state.\n\nPage:\n%s"
        % text[:MAX_CHARS])


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def parse_edges(source_id, published, reply, doc_text, filer=None):
    """JSON reply -> (rows, problems). Kept only if the quote is verbatim, or the amount appears and both parties are named."""
    try:
        edges = json.loads(reply)["edges"]
    except (ValueError, KeyError, TypeError) as e:
        return [], ["%s: unusable reply (%s)" % (source_id, e)]
    rows, problems, doc, low = [], [], _norm(doc_text), doc_text.lower()
    for e in edges:
        try:
            a, b, typ = canon(e["from"]), canon(e["to"]), str(e["type"]).strip().lower()
            typ = TYPE_SYNONYMS.get(typ, typ)
            desc = re.sub(r"\s+", " ", str(e["description"])).strip()[:200]
        except (KeyError, TypeError):
            problems.append("%s: malformed edge %r" % (source_id, e))
            continue
        a, b, typ = normalize(a, b, typ)
        if typ == "investment" and not any(w in (desc + " " + str(e.get("quote", ""))).lower() for w in INVEST_WORDS):
            problems.append("%s: %s -> %s investment dropped (page text does not talk about investing)" % (source_id, a, b))
            continue
        if typ not in TYPES or a == b or not (a in FIVE or b in FIVE) or not desc or GENERIC.search(a + " " + b) \
                or a.lower() in b.lower() or b.lower() in a.lower():  # generic parties and a company's own products
            problems.append("%s: rejected %s -> %s (%s)" % (source_id, a, b, typ))
            continue
        amount = e.get("amount_usd")
        try:
            amount = float(amount) if amount not in (None, "", 0) else None
        except (TypeError, ValueError):
            amount = None
        quote = _norm(e.get("quote", ""))
        quote_ok = len(quote) >= 12 and quote in doc
        amount_ok = amount is not None and any(_contains(doc_text, s) for s in _variants("%d" % amount, "usd")) \
            and a.lower() in low and b.lower() in low
        if not (quote_ok or amount_ok or cooccur(doc_text, a, b, filer)):
            problems.append("%s: %s -> %s dropped (quote not in page, amount not confirmed, parties never named together)" % (source_id, a, b))
            continue
        if amount is not None and not any(_contains(doc_text, s) for s in _variants("%d" % amount, "usd")):
            amount = None  # keep the relationship, drop a figure the page does not show
        rows.append([a, b, typ, desc, "" if amount is None else "%d" % amount, published, source_id, "high"])
    return rows, problems


def dedupe(rows):
    """One row per (from, to, type, amount), earliest announcement wins. Amount-less rows are dropped when the same
    (from, to, type) has a row with a dollar amount, because the amount row already says it."""
    first = {}
    for r in sorted(rows, key=lambda r: (r[5], r[6])):
        first.setdefault((r[0], r[1], r[2], r[4]), r)
    has_amount = {k[:3] for k in first if k[3]}
    out = [r for k, r in first.items() if k[3] or k[:3] not in has_amount]
    return sorted(out, key=lambda r: (r[0], r[1], r[2], r[5]))


def extract(docs, chat=None):
    from rag.llm import TRACKER, get_chat

    chat = chat or get_chat()
    if chat is None:
        print("announcements: no OPENAI_API_KEY, extraction skipped (snapshots were saved)")
        return
    new, problems = [], []
    for company, sid, text, pub, *mode in docs:
        reply = chat.complete([{"role": "system", "content": "You extract stated business relationships from official documents. JSON only."},
                               {"role": "user", "content": _prompt(text, mode[0] if mode else "")}], model=config.QA_MODEL, label="partnerships", json_mode=True)
        rows, probs = parse_edges(sid, pub, reply, text, filer=company if mode else None)
        new += rows
        problems += probs
        print("  %s %-9s %d relationships" % (sid, company, len(rows)))
    path = DATA / "partnerships.csv"
    kept = [r for r in csv.reader(open(path, encoding="utf-8-sig"))][1:] if path.exists() else []
    owned = {d[1] for d in docs}  # rows citing documents this script processed are replaced; anyone else's rows stay
    kept = [r for r in kept if r and r[6] not in owned]
    merged = dedupe(new)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(kept + merged)
    print("partnerships: %d rows (%d from announcements, %d from others) | spend $%.4f" % (len(kept) + len(merged), len(merged), len(kept), TRACKER.total))
    for p in problems:
        print("  note:", p)


def filing_docs():
    """Excerpts of the downloaded 10-K/10-Qs: only paragraphs that name suppliers, partners or the AI labs."""
    from collectors.common import read_sources
    from rag.ingest import read_pages

    out = []
    for src in read_sources():
        if src["doc_type"] not in ("10-K", "10-Q") or not src["local_path"] or src["company"] not in FIVE:
            continue
        text = "\n\n".join(t for _, t in read_pages(DATA / src["local_path"]))
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 60 and any(k in p for k in FILING_KEYWORDS)]
        paras.sort(key=lambda p: not any(k in p for k in SUPPLY_KW))  # named suppliers first, so the size cap never cuts them
        excerpt = "\n\n".join(paras)[:20000]
        if excerpt:
            out.append((src["company"], src["source_id"], excerpt, src["published_date"], "filing_supply"))
            out.append((src["company"], src["source_id"], excerpt, src["published_date"], "filing_competition"))
    return out


def run():
    print("fetching official announcements")
    docs = fetch()
    print("scanning SEC filings for named suppliers and partners")
    extract(docs + filing_docs())


if __name__ == "__main__":
    run()
