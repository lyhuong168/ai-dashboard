"""LangGraph multi-agent system.

  Supervisor (route) -> Researcher (RAG) -> Analyst (pandas tools) -> Verifier -> Writer

The Supervisor picks which specialists a question needs (an LLM when a key exists, keyword
rules otherwise). Specialists that are not needed are skipped. Every step appends to a trace
the dashboard shows. Numbers come from the Analyst's deterministic tools, never from LLM
arithmetic, and the Writer must cite document passages as [S#] and data rows by source_id.
"""
import json
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import analyst
from agents.verifier import check_with_llm, verify
from rag import config
from rag.answer import answer as rag_answer
from rag.ingest import load_sources
from rag.retrieve import detect_companies, load_retriever

ORDER = ["rag", "analyst", "verify", "write"]
NODE_NAMES = {"rag": "researcher", "analyst": "analyst", "verify": "verifier", "write": "writer"}
PUBLIC = {"Google", "Nvidia", "Apple"}


class State(TypedDict, total=False):
    question: str
    sample: bool
    route: list
    rag: dict
    analysis: dict
    verification: dict
    answer: str
    citations: list
    warnings: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def rules_route(question):
    q = question.lower()
    route = ["rag"]
    if any(w in q for w in ["compare", "growth", "grew", "trend", "cheapest", "cost", "price", "pricing", "revenue",
                            "income", "capex", "return", "stock", "performance", "how much", "per million",
                            "workload", "partner", "invest", "supply", "cloud", "financial", "margin", "next week", "coming week",
                            "this week", "upcoming", "expect", "scheduled", "guidance", "outlook", "calendar", "when "]):
        route.append("analyst")
    if any(w in q for w in ["verify", "verified", "trust", "accurate", "check", "mismatch", "confirm"]):
        route.append("verify")
    return route


def llm_route(question, chat):
    reply = chat.complete(
        [{"role": "system", "content": (
            "You are the supervisor of a research team. Reply with ONLY a JSON list choosing specialists: "
            '"rag" (search documents), "analyst" (compute from tables: financials, prices, token pricing, '
            'partnerships), "verify" (cross-check data against sources). Include "rag" whenever the answer '
            "should cite documents.")},
         {"role": "user", "content": question}],
        model=config.EXTRACT_MODEL, label="route")
    try:
        picked = json.loads(reply[reply.index("["): reply.rindex("]") + 1])
        picked = [p for p in ORDER[:3] if p in picked]
        if "verify" in picked and "verify" not in rules_route(question):
            picked.remove("verify")  # only when the user actually asks to check or trust the data
        if "verify" in picked:  # a check needs the figures and their documents too, or the answer is only counts
            picked = [p for p in ORDER[:3] if p in picked or p in rules_route(question)]
        return picked or rules_route(question)
    except (ValueError, TypeError):
        return rules_route(question)


def run_analyst_tools(question, sample):
    q, cos, out = question.lower(), detect_companies(question), {}
    stock_q = any(w in q for w in ["stock", "share price", "shares", "return", "market cap"])
    if any(w in q for w in ["token", "pricing", "cost", "cheap", "per million", "workload"]) or ("price" in q and not stock_q):
        out["workload_cost (1M in + 200k out tokens)"] = analyst.workload_cost(sample)
        changes = analyst.price_changes(sample)
        if changes:
            out["price_changes"] = changes
    if any(w in q for w in ["revenue", "income", "earnings", "financial", "capex", "grow", "grew", "margin", "compare"]):
        metric = "net_income" if "income" in q else "capex" if "capex" in q else "revenue"
        out["latest_" + metric] = analyst.latest_metric(sample, metric)
        for co in (cos or sorted(PUBLIC)):
            if co in PUBLIC:
                g = analyst.growth(sample, co, metric)
                if g:
                    out["qoq_growth_%s_%s" % (co, metric)] = g
        if metric == "revenue" and (not cos or set(cos) - PUBLIC):  # private companies: self-reported run-rate, not quarterly
            rows = [r for co in (sorted(set(cos) - PUBLIC) or [None]) for r in analyst.private_revenue(sample, co)]
            if rows:
                out["private_run_rate_revenue (annualized, self-reported, not quarterly)"] = rows
    if stock_q:
        out["stock_return_30d"] = analyst.stock_return(sample, days=30)
        out["stock_moves"] = analyst.stock_moves(sample)
    if any(w in q for w in ["next week", "coming week", "this week", "upcoming", "expect", "scheduled", "guidance", "outlook", "calendar",
                            "when ", "earnings date", "report earnings", "will report"]):
        days = 7 if "week" in q else 30 if "month" in q else 14
        out["upcoming_events"] = analyst.upcoming_events(sample, days)
        out["company_guidance_vs_actual"] = analyst.guidance_track_record(sample)
    if any(w in q for w in ["partner", "invest", "supply", "cloud", "deal", "compet", "relationship"]):
        for co in cos:
            out["partnerships_" + co] = analyst.partnerships_of(sample, co)
    return out


def _flatten(analysis):
    lines = []
    for name, rows in analysis.items():
        lines.append(name + ":")
        for r in rows if isinstance(rows, list) else [rows]:
            lines.append("  - " + ", ".join("%s=%s" % (k, v) for k, v in r.items()))
    return "\n".join(lines)


SYSTEM_WRITER = (
    "You write for an enterprise AI buyer/investor. Use ONLY the provided passages and computed data. "
    "Cite document passages as [S1]; cite computed rows by their source_id in parentheses. Never do "
    "your own arithmetic or add numbers from memory. If the evidence is missing or thin, say so. "
    "Flag tier-2 (press) evidence as less authoritative. Growth figures named qoq_growth are SEQUENTIAL "
    "quarter-over-quarter changes, not year-over-year: always say so, and warn that seasonal quarters "
    "(e.g. Apple's December quarter) make sequential swings look dramatic. private_run_rate_revenue rows are annualized "
    "figures a private company stated itself, with their wording (bound: approximately / at_least): say 'run-rate', keep the "
    "wording ('surpassed $30 billion'), and never compare them with quarterly revenue as if they were the same measure. When verification data "
    "is given, report both the document check and the independent SEC XBRL cross-check, and name the specific figures "
    "you discuss with their verifier status (found in the cited document or not). When a finding says 'quoted in [S#]', that "
    "passage is the exact place in the document where the figure appears: cite it as [S#] right after the figure, e.g. "
    "'$96,221 million, confirmed [S9]'. Prefer these [S#] tags over bare source_ids. "
    "NEVER predict or estimate future results yourself. For questions about what to expect, report only the dated events and the "
    "company-issued guidance in the computed data. If upcoming_events says nothing is scheduled, say so plainly and then give the next "
    "scheduled events. Events with status 'reported' come from press, not the company: you MUST write (press-reported, not yet confirmed by the company) right after each one. Present guidance_vs_actual as the "
    "company's track record against its own guidance, never as a forecast. Say when a company publishes no numeric guidance. "
    "Be concise: a short answer, then 2-4 bullets.")


def relevant_findings(analysis, ver, limit=30):
    """Verifier rows behind the figures the Analyst computed, plus every problem, so the Writer can name what was checked."""
    ids, metrics = set(), set()
    for name, rows in (analysis or {}).items():
        metrics.add(name.split("_", 3)[-1] if name.startswith("qoq_growth_") else name.replace("latest_", ""))  # qoq_growth_<Co>_<metric>
        for r in rows if isinstance(rows, list) else [rows]:
            if isinstance(r, dict):
                ids.update([r["source_id"]] if r.get("source_id") else r.get("source_ids") or [])
    picked = [f for f in ver["findings"] if f["status"] != "confirmed"
              or (f["source_id"] in ids and (f["table"] != "financials" or any(" %s " % m in f["row"] for m in metrics)))]
    return picked[:limit]


def evidence_passages(findings, registry, start, limit=12):
    """Citable passages (same shape as the Researcher's) quoting where the verifier found each confirmed figure."""
    out = []
    for f in findings:
        src = registry.get(f["source_id"])
        if f["status"] != "confirmed" or not f.get("evidence") or not src or len(out) >= limit:
            continue
        out.append({"tag": "S%d" % (start + len(out)), "chunk_id": "%s#verified" % f["source_id"], "source_id": f["source_id"],
                    "company": src.get("company", ""), "title": src.get("title", ""), "url": src.get("url", ""),
                    "tier": src.get("tier", ""), "published_date": src.get("published_date", ""), "score": None,
                    "verified_row": f["row"], "text": "%s (verified figure: %s)" % (f["evidence"], f["row"])})
    return out


def writer_messages(s):
    """The exact prompt the Writer sends (shared by the blocking and streaming paths)."""
    sources = s.get("rag", {}).get("sources", [])
    analysis, ver = s.get("analysis", {}), s.get("verification")
    checked = relevant_findings(analysis, ver) if ver else []
    quoted_in = {x["verified_row"]: x["tag"] for x in sources if x.get("verified_row")}
    ctx = "\n\n".join(filter(None, [
        "Document passages:\n" + "\n\n".join("[%s] %s | %s | tier %s | %s\n%s" % (
            x["tag"], x["company"], x["title"], x["tier"], x["source_id"], x["text"]) for x in sources) if sources else "",
        "Computed data (cite as (source_id)):\n" + _flatten(analysis) if analysis else "",
        "Verification summary: %s" % ver["summary"] if ver else "",
        "Verifier findings for these figures (row -> status, source; cite the [S#] given):\n" + "\n".join(
            "- %s -> %s (%s)%s" % (f["row"], f["status"], f["source_id"],
                                   ", quoted in [%s]" % quoted_in[f["row"]] if f["row"] in quoted_in else "") for f in checked) if checked else ""]))
    return [{"role": "system", "content": SYSTEM_WRITER},
            {"role": "user", "content": "%s\n\nQuestion: %s" % (ctx, s["question"])}]


def offline_text(s):
    """Extractive answer used when there is no LLM key."""
    sources = s.get("rag", {}).get("sources", [])
    analysis, ver = s.get("analysis", {}), s.get("verification")
    parts = []
    if sources:
        parts.append("Relevant passages:\n" + "\n".join("- [%s] %s" % (x["tag"], x["text"][:300]) for x in sources[:3]))
    if analysis:
        parts.append("Computed from the data tables:\n" + _flatten(analysis))
    if ver:
        m = ver["summary"]
        parts.append("Verification: %d/%d rows confirmed against their documents; %d not found; %d unverifiable." % (
            m["confirmed"], m["checked"], m["not_found"], m["no_document"]))
    return "(offline mode, no LLM key)\n\n" + ("\n\n".join(parts) or "Nothing relevant found.")


def finalize(s, text, llm_used):
    """Check the citations in a finished answer and return the state update."""
    from rag.answer import cited_tags

    sources = s.get("rag", {}).get("sources", [])
    tags, warnings = cited_tags(text), []
    if llm_used:
        if sources and not tags and not s.get("analysis"):
            warnings.append("answer has no citations")
        bad = [t for t in tags if "S" + t not in {x["tag"] for x in sources}]
        if bad:
            warnings.append("answer cites passages that were not retrieved: S" + ", S".join(bad))
    citations = [x for x in sources if x["tag"][1:] in set(tags)] or ([] if llm_used else sources[:3])
    return {"answer": text, "citations": citations, "warnings": warnings,
            "trace": ["writer: composed answer (%d citations)" % len(citations)]}


def build_graph(chat=None, retriever_factory=None, with_writer=True):
    """chat=None runs fully offline (rules + extractive answers). Returns a compiled graph."""
    retriever_factory = retriever_factory or load_retriever

    def supervisor(s):
        route = llm_route(s["question"], chat) if chat else rules_route(s["question"])
        route = [r for r in ORDER[:3] if r in route]
        return {"route": route, "trace": ["supervisor: %s -> %s" % ("LLM" if chat else "rules", route + ["write"])]}

    def researcher(s):
        try:
            res = rag_answer(s["question"], retriever_factory(s["sample"]), chat=None, k=6)  # retrieval only
        except FileNotFoundError as e:
            return {"rag": {"sources": []}, "warnings": [str(e)], "trace": ["researcher: no index (%s)" % e]}
        return {"rag": res, "trace": ["researcher: retrieved %d passages from %s" % (
            len(res["sources"]), sorted({x["source_id"] for x in res["sources"]}))]}

    def analyst_node(s):
        out = run_analyst_tools(s["question"], s["sample"])
        return {"analysis": out, "trace": ["analyst: ran %s" % (sorted(out) or "no tools matched")]}

    def verifier(s):
        base = config.data_dir(s["sample"])
        rep = verify(base)
        if chat and rep["summary"]["not_found"]:  # same second pass the refresh job uses, so both agree
            rep = check_with_llm(rep, base, chat)
        run_file = config.ROOT / "runs" / ("sample" if s["sample"] else "real") / "latest.json"
        if run_file.exists():  # independent SEC XBRL cross-check from the last refresh
            rep["summary"]["sec_xbrl_crosscheck (last refresh)"] = json.loads(run_file.read_text()).get("crosscheck")
        m = rep["summary"]
        rag = dict(s.get("rag") or {"sources": []})
        quotes = evidence_passages(relevant_findings(s.get("analysis"), rep), load_sources(base), start=len(rag.get("sources", [])) + 1)
        rag["sources"] = list(rag.get("sources", [])) + quotes
        return {"verification": rep, "rag": rag, "trace": [
            "verifier: %d checked, %d confirmed, %d not found, %d without document; quoted %d figures from their documents" % (
                m["checked"], m["confirmed"], m["not_found"], m["no_document"], len(quotes))]}

    def writer(s):
        if chat is None:
            return finalize(s, offline_text(s), False)
        return finalize(s, chat.complete(writer_messages(s), model=config.QA_MODEL, label="write"), True)

    def after(current):
        def pick(s):
            later = [n for n in ORDER[ORDER.index(current) + 1:] if (n == "write" and with_writer) or n in s["route"]]
            return later[0] if later else ("write" if with_writer else END)
        return pick

    g = StateGraph(State)
    nodes = {"supervisor": supervisor, "rag": researcher, "analyst": analyst_node, "verify": verifier, "write": writer}
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "supervisor")
    targets = {n: n for n in ORDER}
    targets[END] = END
    g.add_conditional_edges("supervisor", lambda s: next(
        (n for n in ORDER if (n == "write" and with_writer) or n in s["route"]), "write" if with_writer else END), targets)
    for n in ORDER[:3]:
        g.add_conditional_edges(n, after(n), targets)
    g.add_edge("write", END)
    return g.compile()


def ask(question, sample=False, chat="auto", retriever_factory=None):
    """One call for the UI: returns the final state (answer, citations, analysis, verification, trace)."""
    if chat == "auto":
        from rag.llm import get_chat

        chat = get_chat()
    return build_graph(chat, retriever_factory).invoke({"question": question, "sample": sample, "warnings": [], "trace": []})


def _merge(state, delta):
    for k, v in delta.items():
        state[k] = state.get(k, []) + v if k in ("warnings", "trace") else v


def ask_stream(question, sample=False, chat="auto", retriever_factory=None):
    """Generator for a live UI. Yields {"type": "step", "node", "state"} as each agent finishes,
    {"type": "write_start", "state"}, then {"type": "token", "text"} pieces of the answer, and
    finally {"type": "final", "state"} (same fields as ask())."""
    if chat == "auto":
        from rag.llm import get_chat

        chat = get_chat()
    graph = build_graph(chat, retriever_factory, with_writer=False)
    state = {"question": question, "sample": sample, "warnings": [], "trace": []}
    for update in graph.stream(dict(state), stream_mode="updates"):
        for node, delta in update.items():
            _merge(state, delta)
            yield {"type": "step", "node": node, "state": state}
    yield {"type": "write_start", "state": state}
    if chat is None:
        text = offline_text(state)
        for i in range(0, len(text), 18):
            yield {"type": "token", "text": text[i:i + 18]}
    else:
        parts = []
        for tok in chat.stream(writer_messages(state), model=config.QA_MODEL, label="write"):
            parts.append(tok)
            yield {"type": "token", "text": tok}
        text = "".join(parts)
    _merge(state, finalize(state, text, chat is not None))
    yield {"type": "final", "state": state}
