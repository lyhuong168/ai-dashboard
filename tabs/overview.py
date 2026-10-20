"""Overview tab. Owner: Reid. Animated KPIs, verification rings and insight cards.
Every number is computed by the Analyst tools or read from the refresh log, never by an LLM."""
import json

import streamlit as st

from agents import analyst
from app import components
from app.theme import ACCENT, COMPANY_COLORS, GOOD, VIOLET, WARN, logo_uri
from rag import config

PUBLIC = ["Google", "Nvidia", "Apple"]


def _run(sample):
    f = config.ROOT / "runs" / ("sample" if sample else "real") / "latest.json"
    return json.loads(f.read_text()) if f.exists() else None


def _n_chunks(sample):
    f = config.store_dir(sample) / "meta.json"
    return json.loads(f.read_text()).get("n_chunks", 0) if f.exists() else 0


def _revenue_cards(df):
    items = []
    for co in PUBLIC:
        sub = df[(df["company"] == co) & (df["metric"] == "revenue")].sort_values("period_end")
        if sub.empty:
            continue
        vals = [v / 1000.0 for v in sub["value"]]
        last = sub.iloc[-1]
        card = {"label": "%s · revenue" % co, "value": round(vals[-1], 1), "prefix": "$", "suffix": "B", "decimals": 1,
                "sub": "%s · %s" % (last["period"], last["source_id"]), "spark": vals, "color": COMPANY_COLORS[co], "logo": logo_uri(co)}
        if len(vals) > 1:
            d = (vals[-1] / vals[-2] - 1) * 100
            card.update({"delta": "%+.1f%% QoQ" % d, "delta_up": d >= 0})
        items.append(card)
    return items


def render(data, sample):
    st.subheader("Overview")
    st.caption("For an enterprise AI buyer / investor. Every figure carries a source_id; hover the cards for details.")
    run, fin = _run(sample), data["financials"]

    cards = _revenue_cards(fin)
    if cards:
        st.markdown("##### Latest quarterly revenue")
        components.kpi_cards(cards, height=200)
    else:
        st.info("No financial data yet.")

    src = data["sources"]
    tier1 = int((src["tier"].astype(str) == "1").sum()) if len(src) else 0
    stats = [
        {"label": "Sources tracked", "value": len(src), "sub": "%d primary (tier 1)" % tier1, "color": ACCENT},
        {"label": "Passages indexed", "value": _n_chunks(sample), "sub": "searchable by the agents", "color": VIOLET},
        {"label": "Financial figures", "value": len(fin), "sub": "extracted + verified", "color": GOOD},
        {"label": "Price points", "value": len(data["stock_prices"]), "sub": "daily closes", "color": WARN},
    ]
    st.markdown("##### The evidence base")
    components.kpi_cards(stats, height=150)

    if run:
        v, cc = run["verification"], run.get("crosscheck") or {}
        rings = [{"label": "Found in source documents", "pct": round(100.0 * v["confirmed"] / max(v["checked"], 1)),
                  "sub": "%d of %d figures" % (v["confirmed"], v["checked"]), "color": GOOD}]
        if "agrees" in cc and cc["agrees"] + cc["differs"]:
            n = cc["agrees"] + cc["differs"]
            rings.append({"label": "Match the SEC's own data", "pct": round(100.0 * cc["agrees"] / n),
                          "sub": "%d of %d checkable" % (cc["agrees"], n), "color": ACCENT})
        if len(src):
            rings.append({"label": "Primary sources", "pct": round(100.0 * tier1 / len(src)),
                          "sub": "SEC filings and company releases", "color": VIOLET})
        st.markdown("##### Trust scores")
        components.rings(rings, height=250)

    st.markdown("##### Insights (computed, not generated)")
    latest = analyst.latest_metric(sample, "revenue")
    if latest:
        top = max(latest, key=lambda r: r["value"])
        st.markdown('<div class="insight"><h4>Scale</h4><p><b>%s</b> reported the largest latest-quarter revenue: '
                    '<b>$%.1fB</b> (%s, source %s). Latest quarters differ by company fiscal calendar.</p></div>' % (
                        top["company"], top["value"] / 1000.0, top["period"], top["source_id"]), unsafe_allow_html=True)
    growers = []
    for co in PUBLIC:
        g = analyst.growth(sample, co, "revenue")
        if g:
            growers.append((co, g[-1]))
    if growers:
        co, g = max(growers, key=lambda x: x[1]["qoq_growth_pct"])
        st.markdown('<div class="insight"><h4>Momentum</h4><p><b>%s</b> had the strongest sequential revenue growth in its latest '
                    'quarter: <b>%+.1f%% QoQ</b> (%s; sources %s). Sequential, not year-over-year, and not seasonally adjusted.</p></div>' % (
                        co, g["qoq_growth_pct"], g["period"], ", ".join(g["source_ids"])), unsafe_allow_html=True)
    cost = analyst.workload_cost(sample)
    if len(cost) > 1:
        a, b = cost[0], cost[-1]
        st.markdown('<div class="insight"><h4>Cost to run AI</h4><p>For a standard workload (1M input + 200k output tokens) '
                    '<b>%s %s</b> is cheapest at <b>$%.2f</b>; <b>%s %s</b> costs <b>%.1fx</b> as much (sources %s, %s).</p></div>' % (
                        a["company"], a["model"], a["usd"], b["company"], b["model"], b["usd"] / a["usd"],
                        a["source_id"], b["source_id"]), unsafe_allow_html=True)
    elif not cost:
        st.caption("Token-pricing insight appears once pricing data is loaded (Lyhuong's table).")
