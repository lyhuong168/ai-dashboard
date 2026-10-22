"""Sources & Freshness tab. Owner: Reid. Shows trust tiers, verification results, last refresh, cost."""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import add_source, live_prices
from app.theme import GOOD, WARN, chart
from rag import config


def render(data, sample):
    src = data["sources"]
    head, action = st.columns([5, 1], vertical_alignment="center")
    head.subheader("Sources, verification and freshness")
    if not sample:
        with action:
            add_source.button(set(src["url"]))
        add_source.notice()
    run_file = config.ROOT / "runs" / ("sample" if sample else "real") / "latest.json"
    run = json.loads(run_file.read_text()) if run_file.exists() else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sources", len(src))
    c2.metric("Tier 1 (primary)", int((src["tier"].astype(str) == "1").sum()) if len(src) else 0)
    c3.metric("Tier 2 (press/market)", int((src["tier"].astype(str) == "2").sum()) if len(src) else 0)
    if run:
        v = run["verification"]
        c4.metric("Rows verified", "%d / %d" % (v["confirmed"], v["checked"]))
    else:
        c4.metric("Rows verified", "n/a")

    if run:
        st.markdown("**Last refresh:** %s · embedder `%s` · cost \\$%.4f of \\$%.2f cap" % (
            live_prices.refreshed_et(run), run["embedder"], run["cost"]["total_usd"], run["cost"]["cap_usd"]))
        st.markdown("**What changed since the previous run:** " + "; ".join(run["changes"]))
        if not run["validation"]["ok"]:
            st.error("Data validation failed on the last refresh:\n\n" + "\n".join(run["validation"]["output"]))
        cc = run.get("crosscheck")
        if cc and "agrees" in cc:
            checkable = cc["agrees"] + cc["differs"]
            st.markdown("**Independent check against the SEC's structured (XBRL) data:** %d of %d checkable figures agree; "
                        "%d have no discrete SEC value to compare (e.g. segment lines, Q4)." % (cc["agrees"], checkable, cc["no_independent_source"]))
            if run.get("crosscheck_problems"):
                st.error("%d figure(s) differ from the SEC's data:" % len(run["crosscheck_problems"]))
                st.dataframe(pd.DataFrame(run["crosscheck_problems"]))
        elif cc and "error" in cc:
            st.warning("SEC cross-check could not run: %s" % cc["error"])
        if run["problems"]:
            st.markdown("**Needs attention**")
            st.dataframe(pd.DataFrame(run["problems"]))
        else:
            st.success("Every checkable number was found in its cited source document.")
    else:
        st.info("No refresh has run yet. Run `python refresh.py%s` in a terminal." % (" --sample" if sample else ""))

    if len(src):
        st.markdown("**Source registry**")
        by = src.groupby(["company", "tier"]).size().reset_index(name="sources")
        fig = go.Figure()
        for tier, color, label in (("1", GOOD, "Tier 1 · primary"), ("2", WARN, "Tier 2 · press / market data")):
            s = by[by["tier"].astype(str) == tier]
            fig.add_trace(go.Bar(x=s["company"], y=s["sources"], name=label, marker_color=color,
                                 hovertemplate="%{x}<br>" + label + ": %{y}<extra></extra>"))
        fig.update_layout(barmode="stack", height=340, yaxis_title="sources")
        chart(fig, key="src_tiers")
        st.dataframe(src.drop(columns=["local_path"], errors="ignore"))
