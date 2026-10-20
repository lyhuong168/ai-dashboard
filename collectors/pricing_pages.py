"""Token prices from the vendors' OFFICIAL pricing pages -> data/token_pricing.csv.

1. fetch(): download each page, save a dated plain-text snapshot to data/raw/<Company>/ and register it in
   data/sources/sources_R.csv (tier 1, pricing_page). A snapshot per capture date keeps the evidence for old prices.
2. extract(): an LLM reads the snapshot and proposes models + prices; a price is kept ONLY if the number appears in
   the snapshot as a dollar amount. History is append-only: a new captured_date adds rows, it never overwrites old ones,
   so the dashboard can show how prices change.

Needs OPENAI_API_KEY for step 2. OpenAI's marketing page (openai.com/api/pricing) refuses scripts (403); we use the
official developer docs page instead and do not try to work around the block.
"""
import csv
import json
import re
from datetime import date

import requests

from agents.verifier import _contains, _variants
from collectors.common import DATA, SOURCES_R, add_source, read_sources, today
from rag import config
from rag.ingest import html_to_text

PAGES = [
    ("Google", "https://ai.google.dev/gemini-api/docs/pricing", "Gemini Developer API pricing", "Google AI for Developers"),
    ("OpenAI", "https://developers.openai.com/api/docs/pricing", "OpenAI API pricing", "OpenAI"),
    ("Anthropic", "https://platform.claude.com/docs/en/about-claude/pricing", "Claude API pricing", "Anthropic"),
]
HINTS = {  # how each vendor lays out its page (the numbers are still verified against the page text)
    "Google": "Use the 'Paid Tier' column. For prompt-length tiers use the '<= 200k tokens' price. Cached = 'Context caching price'.",
    "OpenAI": ("The page has tabs Standard/Batch/Flex/Fast/Ultrafast. Use ONLY the 'Standard' table under 'Flagship models', "
               "the 'Short context' columns: Input, Cached input, Output (ignore 'Cache writes' and 'Long context')."),
    "Anthropic": ("Use the 'Model pricing' table: Base tokens 'Input' and 'Output' (not 5m/1h writes); cached = 'Hits and refreshes'. "
                  "Where a model has prompt-length tiers (e.g. 'for prompts up to 100,000 tokens') use the FIRST, shorter tier. "
                  "Use model names as written, e.g. 'Claude Haiku 5.5'."),
}
UA = "MIS556-student-research/1.0 (university course project; reads public pricing pages)"
COLS = ["company", "model", "input_usd_per_1m", "output_usd_per_1m", "cached_input_usd_per_1m", "context_window", "source_id", "captured_date"]
MAX_CHARS = 160_000


def fetch():
    """Snapshot each pricing page. Returns [(company, source_id, text)] for today's captures."""
    out = []
    for company, url, title, publisher in PAGES:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        text = html_to_text(r.text)
        m = re.search(r"[Ll]ast updated:?\s*(\d{4}-\d{2}-\d{2})", text)
        stamp = "Source: %s\nRetrieved: %s\nPublisher: %s\n\n" % (r.url, today(), publisher)
        row = {"company": company, "title": "%s (captured %s)" % (title, today()), "url": r.url + "#captured-" + today(),
               "publisher": publisher, "doc_type": "pricing_page", "tier": "1",
               "published_date": m.group(1) if m else today(), "retrieved_date": today(), "local_path": ""}
        sid = add_source(row, path=SOURCES_R, prefix="R")
        rel = "raw/%s/%s-%s.txt" % (company, sid, today().replace("-", ""))
        (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        (DATA / rel).write_text(stamp + text, encoding="utf-8")
        add_source({**row, "local_path": rel}, path=SOURCES_R, prefix="R")
        print("  %-9s %s  %d KB of text  (page last updated %s)" % (company, sid, len(text) // 1024, row["published_date"]))
        out.append((company, sid, stamp + text))
    return out


def _prompt(company, text):
    return (
        "Company: %s. Today is %s.\nFrom this OFFICIAL pricing page, list the general-purpose TEXT models a developer would "
        "use for chat/reasoning: the flagship, the mid-tier, and the smallest/cheapest (at most 5 models in total). Use the paid "
        "STANDARD tier (not batch, flex, priority, free tier, audio, image, video, embedding, realtime or fine-tuning). For "
        "prompts of any length use the base price (the one for prompts up to 200k tokens, if prices differ by length). If a price "
        "is scheduled to change on a future date, use the price in effect TODAY.\n"
        "Return JSON: {\"models\": [{\"model\": \"exact model name/id as written\", \"input\": USD per 1M input tokens, "
        "\"output\": USD per 1M output tokens, \"cached_input\": USD per 1M cached/cache-hit input tokens or null, "
        "\"quote\": a short VERBATIM excerpt from the page containing the input price}]}. "
        "Copy each price EXACTLY as written on the page. Do not rescale or convert: the page already quotes USD per 1M tokens unless it says otherwise. Omit anything you are unsure about.\n"
        "How to read this vendor's page: %s\n\nPage:\n%s"
        % (company, today(), HINTS.get(company, ""), text[:MAX_CHARS]))


def _num(x):
    """'$10.00', '$10 / MTok', 2.5 or '1,000' -> float (None for null/empty)."""
    if x in (None, "", 0):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"\d[\d,]*\.?\d*", str(x))
    return float(m.group(0).replace(",", "")) if m else None


def parse_models(company, source_id, captured, reply, doc_text):
    """JSON reply -> (rows, problems). A model is kept only if its input AND output prices appear in the page as dollar amounts."""
    try:
        models = json.loads(reply)["models"]
    except (ValueError, KeyError, TypeError) as e:
        return [], ["%s: unusable reply (%s)" % (source_id, e)]
    rows, problems = [], []
    for m in models:
        try:
            name, pin, pout, cached = str(m["model"]).strip(), _num(m["input"]), _num(m["output"]), _num(m.get("cached_input"))
            if pin is None or pout is None:
                raise ValueError("missing price")
        except (KeyError, TypeError, ValueError):
            problems.append("%s: unusable model entry %r" % (source_id, m))
            continue
        if not name or not (0.005 <= pin <= 500 and 0.005 <= pout <= 1000):
            problems.append("%s %s: implausible price in=%s out=%s, dropped" % (source_id, name, pin, pout))
            continue
        absent = [lab for lab, v in (("input", pin), ("output", pout), ("cached", cached)) if v is not None
                  and not any(_contains(doc_text, s) for s in _variants(("%g" % v), "usd"))]
        if absent:
            problems.append("%s %s: %s price not found on the page, dropped" % (source_id, name, "/".join(absent)))
            continue
        rows.append([company, name, "%g" % pin, "%g" % pout, "" if cached is None else "%g" % cached, "", source_id, captured])
    return rows, problems


def extract(captures, chat=None):
    from rag.llm import TRACKER, get_chat

    chat = chat or get_chat()
    if chat is None:
        print("pricing_pages: no OPENAI_API_KEY, extraction skipped (snapshots were saved)")
        return
    path = DATA / "token_pricing.csv"
    kept = [r for r in csv.reader(open(path, encoding="utf-8-sig"))][1:] if path.exists() else []
    problems, new = [], []
    for company, sid, doc in captures:
        reply = chat.complete(
            [{"role": "system", "content": "You read vendor pricing pages and extract exact prices. JSON only."},
             {"role": "user", "content": _prompt(company, doc)}], model=config.QA_MODEL, label="pricing", json_mode=True)
        rows, probs = parse_models(company, sid, today(), reply, doc)
        new += rows
        problems += probs
        print("  %-9s %d models: %s" % (company, len(rows), ", ".join(r[1] for r in rows)))
    fresh = {r[0] for r in new}  # same-day rerun replaces today's rows only for companies that returned new ones
    kept = [r for r in kept if r and not (r[7] == today() and r[0] in fresh)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(kept + new)
    print("token_pricing: %d rows (%d new) | spend $%.4f" % (len(kept) + len(new), len(new), TRACKER.total))
    for p in problems:
        print("  note:", p)


def run():
    print("fetching official pricing pages")
    extract(fetch())


if __name__ == "__main__":
    run()
