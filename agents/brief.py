"""Market Brief: a sourced synopsis of the five companies.

Evidence = (a) FACTS computed from our verified tables (prices, latest quarter, guidance, dated events, deals, token prices)
and (b) NEWS ITEMS captured from official feeds (tier 1) and press headlines (tier 2).
An LLM may only restate that evidence. Two guards run on every bullet it writes:
  1. every citation id must exist, and
  2. every number in the bullet must literally appear in the evidence it cites.
Bullets that fail are dropped. Without an API key the brief is built from the facts alone. It never forecasts.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

from agents import analyst
from rag import config

COMPANIES = ["Google", "OpenAI", "Anthropic", "Nvidia", "Apple"]
TICKER = {"Google": "GOOGL", "Nvidia": "NVDA", "Apple": "AAPL"}
NUM = re.compile(r"\d[\d,]*\.?\d*")


def run_dir(sample):
    return config.ROOT / "runs" / ("sample" if sample else "real")


def load_brief(sample):
    f = run_dir(sample) / "brief.json"
    return json.loads(f.read_text()) if f.exists() else None


def _norm_nums(text):
    """Numbers in a text as comparable strings: '$1,234.50' -> '1234.5', '0.50' -> '0.5'. Single digits are ignored."""
    out = set()
    for m in NUM.findall(text.replace("%", " ")):
        m = m.replace(",", "").rstrip(".")
        if not m:
            continue
        if "." in m:
            m = m.rstrip("0").rstrip(".") if m.split(".")[1].strip("0") else m.split(".")[0]
        if len(m.replace(".", "")) >= 2:
            out.add(m)
    return out


def check_bullet(text, cites, evidence):
    """(ok, reason). Every cite must exist; every number in the text must appear in the cited evidence."""
    if not cites or not text.strip():
        return False, "no citation"
    missing = [c for c in cites if c not in evidence]
    if missing:
        return False, "unknown citation %s" % missing[0]
    pool = _norm_nums(" ".join(evidence[c]["text"] for c in cites))
    unsupported = _norm_nums(text) - pool
    if unsupported:
        return False, "number not in the cited evidence: %s" % sorted(unsupported)[0]
    return True, ""


YOY = [  # how each company's own release states year-over-year revenue growth
    re.compile(r"quarterly revenue of \$[\d.]+ billion, up (\d+) percent year over year"),
    re.compile(r"Revenue of \$[\d.]+ billion, up (\d+)% from a year ago"),
    re.compile(r"revenues increased (\d+)%(?:, or \d+% in constant currency,)? to \$[\d.]+ billion"),
]


def stated_yoy(text):
    """Year-over-year revenue growth exactly as the release states it (percent, as a string), or None."""
    for pat in YOY:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _fmt_money(musd):
    return "$%.1fB" % (musd / 1000.0)


def build_facts(sample, today=None):
    """Deterministic evidence from our own verified tables. Returns {company: [fact dicts]} and a flat evidence map."""
    d = analyst._data(sample)
    today = today or date.today()
    facts = {c: [] for c in COMPANIES + ["All"]}

    def add(company, text, source_ids, kind, tier="1"):
        n = len(facts[company]) + 1
        facts[company].append({"id": "%s-F%d" % (company[:3].upper(), n), "text": text, "source_ids": source_ids, "kind": kind, "tier": tier})

    wk = analyst.upcoming_events(sample, days=7, today=today)
    add("All", wk[0]["note"] if "note" in wk[0] else "Scheduled in the next 7 days: " + "; ".join("%s %s on %s" % (e["company"], e["what"], e["date"]) for e in wk if "what" in e) + ".", [], "week_ahead")
    nxt = [e for e in analyst.upcoming_events(sample, days=60, today=today) if "what" in e and e["type"] == "earnings"]
    if nxt:
        add("All", "Next scheduled earnings: " + "; ".join("%s on %s (%s)" % (e["company"], e["date"], "confirmed by the company" if e["status"] == "confirmed" else "press-reported, not yet confirmed by the company") for e in nxt) + ".", [e["source_id"] for e in nxt], "week_ahead")
    src = d["sources"]
    mkt = {r.company: r.source_id for r in src.itertuples() if r.doc_type == "market_data"}
    for m in analyst.stock_moves(sample):
        co = next((c for c, t in TICKER.items() if t == m["ticker"]), None)
        if co:
            bits = ["%s %.2f%% over 1 day" % ("+" if m["chg_1d_pct"] >= 0 else "-", abs(m["chg_1d_pct"])) if m["chg_1d_pct"] is not None else "",
                    "%+.2f%% over 5 trading days" % m["chg_5d_pct"] if m["chg_5d_pct"] is not None else "",
                    "%+.2f%% over about a month" % m["chg_1m_pct"] if m["chg_1m_pct"] is not None else ""]
            add(co, "%s closed at $%.2f on %s (%s); 52-week range $%.2f to $%.2f (Yahoo Finance market data)." % (
                m["ticker"], m["close"], m["as_of"], ", ".join(b for b in bits if b), m["range_52w"][0], m["range_52w"][1]),
                [mkt[co]] if co in mkt else [], "price", "2")
    fin = d["financials"]
    for co in ("Google", "Nvidia", "Apple"):
        rev = fin[(fin["company"] == co) & (fin["metric"] == "revenue")].sort_values("period_end")
        if len(rev):
            last = rev.iloc[-1]
            yoy = None
            row = src[src["source_id"] == last["source_id"]]
            if len(row) and isinstance(row.iloc[0]["local_path"], str):
                from rag.ingest import read_pages
                yoy = stated_yoy(" ".join(t for _, t in read_pages(config.data_dir(sample) / row.iloc[0]["local_path"])))
            extra = ", which the company's own release states was up %s%% year over year" % yoy if yoy else ""
            seq = ""
            if len(rev) > 1:
                seq = " Sequentially (quarter over quarter, not seasonally adjusted) revenue moved %+.1f%%." % ((last["value"] / rev.iloc[-2]["value"] - 1) * 100)
            add(co, "Latest reported quarter %s revenue was %s%s.%s" % (last["period"], _fmt_money(last["value"]), extra, seq), [last["source_id"]], "financials")
    for g in d["guidance"][d["guidance"]["metric"] == "revenue"].sort_values("issued_date").groupby("company").tail(1).itertuples():
        tol = "plus or minus %g%%" % g.tolerance_pct if g.tolerance_pct == g.tolerance_pct else ""
        add(g.company, "%s guided %s revenue to %s %s (issued %s). Company guidance, not our forecast." % (
            g.company, g.target_period, _fmt_money(g.value), tol, g.issued_date.date()), [g.source_id], "guidance")
    for r in analyst.guidance_track_record(sample):
        if "actual_musd" in r:
            pass
    track = [r for r in analyst.guidance_track_record(sample) if "actual_musd" in r]
    if track:
        by = {}
        for r in track:
            by.setdefault(r["company"], []).append(r)
        for co, rs in by.items():
            above = sum(r["result"].startswith("above") for r in rs)
            add(co, "In %d of the last %d guided quarters %s reported revenue above the top of its own guided range; the gaps vs the midpoint were %s." % (
                above, len(rs), co, ", ".join("%+.1f%%" % r["vs_midpoint_pct"] for r in rs)), sorted({r["guidance_source"] for r in rs} | {r["actual_source"] for r in rs}), "track_record")
    for e in analyst.upcoming_events(sample, days=60, today=today):
        if "note" in e:
            continue
        who = "confirmed by the company" if e["status"] == "confirmed" else "press-reported, not yet confirmed by the company"
        add(e["company"], "%s on %s (%s; %d days away)." % (e["what"], e["date"], who, e["days_until"]), [e["source_id"]], "event", "1" if e["status"] == "confirmed" else "2")
    pr = d["partnerships"].sort_values("date", ascending=False)
    for co in COMPANIES:
        sub = pr[((pr["from_company"] == co) | (pr["to_company"] == co)) & (pr["relationship_type"] != "competition")].head(3)
        for r in sub.itertuples():
            amt = " ($%.1fB)" % (r.amount_usd / 1e9) if r.amount_usd == r.amount_usd and r.amount_usd else ""
            add(co, "%s -> %s %s%s on %s: %s" % (r.from_company, r.to_company, r.relationship_type, amt, str(r.date.date()), r.description), [r.source_id], "deal")
    tp = d["token_pricing"]
    for co in ("Google", "OpenAI", "Anthropic"):
        sub = tp[tp["company"] == co].sort_values("captured_date").groupby("model").tail(1).sort_values("output_usd_per_1m")
        if len(sub):
            top, low = sub.iloc[-1], sub.iloc[0]
            add(co, "Token prices (per 1M tokens, captured %s): flagship %s $%g in / $%g out; cheapest %s $%g in / $%g out." % (
                str(top["captured_date"].date()), top["model"], top["input_usd_per_1m"], top["output_usd_per_1m"], low["model"],
                low["input_usd_per_1m"], low["output_usd_per_1m"]), sorted(set(sub["source_id"])), "pricing")
    return facts


def load_news(sample):
    f = run_dir(sample) / "news.json"
    return json.loads(f.read_text())["companies"] if f.exists() else {}


def build_evidence(facts, news):
    ev = {}
    for co, fs in facts.items():
        for f in fs:
            ev[f["id"]] = {"text": f["text"], "tier": f["tier"], "source_id": ",".join(f["source_ids"]), "kind": f["kind"], "company": co}
    for co, items in news.items():
        for it in items:
            ev[it["id"]] = {"text": "%s %s: %s. %s" % (it["date"], it["publisher"], it["title"], it["summary"]), "tier": it["tier"], "source_id": it["source_id"],
                            "kind": "news", "company": co, "title": it["title"], "publisher": it["publisher"], "url": it["url"], "date": it["date"]}
    return ev


PROMPT = (
    "You write a factual market brief for an enterprise AI buyer / investor from the EVIDENCE below. Rules:\n"
    "- Use ONLY the evidence. Each bullet must end its meaning with citations: a list of evidence ids it relies on.\n"
    "- Every number you write must appear exactly in the evidence you cite. Do not compute or round new numbers.\n"
    "- NEVER predict or estimate future results. You may restate dated events and company guidance exactly as given.\n"
    "- Press items (tier 2) must be attributed ('reported by <publisher>'). Prefer official (tier 1) items.\n"
    "- Mention an event as press-reported when its evidence says so.\n"
    "- For every company that has NEWS items, include at least one bullet about the most recent or most significant news item. Prefer official "
    "(tier 1) items, and attribute press items to their publisher.\n"
    "- Revenue growth: use the year-over-year figure when the evidence gives one. A sequential (quarter-over-quarter) change is NOT a trend; call it 'sequential'.\n"
    "- Headlines must be neutral one-line summaries of your own bullets. No adjectives that are not in the evidence, no causal claims.\n"
    "- 'overall' is for cross-company points (what is scheduled this week, the next earnings dates, themes shared by several companies). Do not repeat company bullets.\n"
    "Return JSON: {\"overall\": [bullet,...], \"companies\": {\"Google\": {\"headline\": \"one line\", \"bullets\": [bullet,...]}, ...}} where "
    "bullet = {\"text\": \"one or two sentences\", \"cites\": [\"evidence id\", ...]}. 3-4 bullets per company, 2-4 overall. "
    "Cover all five companies: Google, OpenAI, Anthropic, Nvidia, Apple.\n\nEVIDENCE:\n%s")


def facts_only_brief(facts, news):
    """No LLM: the deterministic facts are the brief, plus the newest headlines."""
    out = {}
    order = ("event", "guidance", "track_record", "price", "financials", "deal", "pricing")
    for co in COMPANIES:
        bullets = [{"text": f["text"], "cites": [f["id"]]} for k in order for f in facts[co] if f["kind"] == k][:4]
        out[co] = {"headline": "", "bullets": bullets}
    over = [{"text": f["text"], "cites": [f["id"]]} for f in facts.get("All", [])]
    return {"overall": over, "companies": out}


def build_brief(sample=False, chat="auto", today=None):
    from rag.llm import TRACKER, get_chat

    chat = get_chat() if chat == "auto" else chat
    today = today or date.today()
    before = TRACKER.total
    facts, news = build_facts(sample, today), load_news(sample)
    evidence = build_evidence(facts, news)
    dropped = []
    if chat is None:
        raw = facts_only_brief(facts, news)
    else:
        lines = []
        for co in ["All"] + COMPANIES:
            lines.append("== %s ==" % co)
            lines += ["[%s] (tier %s) %s" % (i, evidence[i]["tier"], evidence[i]["text"][:400]) for i, e in evidence.items() if e["company"] == co]
        reply = chat.complete([{"role": "system", "content": "You write sourced, non-speculative market briefs. JSON only."},
                               {"role": "user", "content": PROMPT % "\n".join(lines)}], model=config.QA_MODEL, label="brief", json_mode=True)
        try:
            raw = json.loads(reply)
        except ValueError:
            raw = facts_only_brief(facts, news)
    result = {"overall": [], "companies": {}}
    def keep(bullets, where):
        good = []
        for b in bullets or []:
            text, cites = str(b.get("text", "")).strip(), list(b.get("cites", []))
            ok, why = check_bullet(text, cites, evidence)
            if not ok:
                dropped.append({"where": where, "text": text[:160], "why": why})
                continue
            if all(evidence[c]["tier"] == "2" and evidence[c]["kind"] == "news" for c in cites) and not re.search(r"(?i)reported|according to|press", text):
                text += " (reported by %s)" % evidence[cites[0]].get("publisher", "press")  # press-only claims are always attributed
            good.append({"text": text, "cites": cites})
        return good
    result["overall"] = keep(raw.get("overall"), "overall")
    for co in COMPANIES:
        c = (raw.get("companies") or {}).get(co) or {}
        result["companies"][co] = {"headline": str(c.get("headline", ""))[:160], "bullets": keep(c.get("bullets"), co)}
    used = {c for b in result["overall"] for c in b["cites"]} | {c for v in result["companies"].values() for b in v["bullets"] for c in b["cites"]}
    brief = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "as_of": today.isoformat(), "mode": "sample" if sample else "real",
             "llm": chat is not None, "cost_usd": round(TRACKER.total - before, 4), "dropped": dropped,
             "week_ahead": analyst.upcoming_events(sample, days=7, today=today), "next_events": analyst.upcoming_events(sample, days=60, today=today),
             "guidance": analyst.guidance_track_record(sample), "moves": analyst.stock_moves(sample),
             "overall": result["overall"], "companies": result["companies"], "evidence": {i: evidence[i] for i in used if i in evidence},
             "headlines": {co: [dict(n) for n in news.get(co, [])][:8] for co in COMPANIES}}
    out = run_dir(sample)
    out.mkdir(parents=True, exist_ok=True)
    (out / "brief.json").write_text(json.dumps(brief, indent=2, default=str))
    return brief
