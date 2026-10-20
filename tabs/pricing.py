"""Pricing tab. Owner: Lyhuong (Facts); styling by Reid.

Working starter: input vs output price per 1M tokens, plus the cost of a standard workload. Ideas: cached-input
savings, price vs context window, how prices changed between captured_date snapshots.
"""
import plotly.graph_objects as go
import streamlit as st

from agents import analyst
from app.theme import COMPANY_COLORS, chart


def render(data, sample=False):
    st.subheader("Token pricing (USD per 1M tokens)")
    df = data["token_pricing"]
    if df.empty:
        st.info("No pricing data yet. Fill data/token_pricing.csv (official pricing pages only, each with a source_id).")
        return
    latest = df.sort_values("captured_date").groupby(["company", "model"]).tail(1)
    fig = go.Figure()
    for label, col, op in (("Input", "input_usd_per_1m", 1.0), ("Output", "output_usd_per_1m", 0.55)):
        fig.add_trace(go.Bar(name=label, x=latest["model"], y=latest[col], opacity=op,
                             marker_color=[COMPANY_COLORS.get(c, "#00E5FF") for c in latest["company"]],
                             hovertemplate="%{x}<br>" + label + ": $%{y:,.2f} per 1M tokens<extra></extra>"))
    fig.update_layout(barmode="group", height=420, yaxis_title="USD per 1M tokens", showlegend=False)
    chart(fig, key="price_bars")
    st.caption("Bright bar = input price, faded bar = output price. Colors are the vendors: Google blue, OpenAI green, Anthropic orange.")
    st.markdown("##### Cost of a standard workload (1M input + 200k output tokens)")
    cost = analyst.workload_cost(sample)
    if cost:
        fig2 = go.Figure(go.Bar(x=[c["usd"] for c in cost], y=["%s · %s" % (c["company"], c["model"]) for c in cost], orientation="h",
                                marker_color=[COMPANY_COLORS.get(c["company"], "#00E5FF") for c in cost],
                                text=["$%.2f" % c["usd"] for c in cost], textposition="outside"))
        fig2.update_layout(height=60 + 60 * len(cost), xaxis_title="USD", yaxis=dict(autorange="reversed"))
        chart(fig2, key="price_cost")
    st.dataframe(df)
