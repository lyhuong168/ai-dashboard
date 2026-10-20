"""Stock tab. Owner: Manny (Numbers); animation + styling by Reid. Manny: extend with returns around earnings
dates, volatility, drawdowns, correlation. Keep using theme.chart().

Press Replay to watch the lines draw themselves.
"""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from app.theme import ACCENT, COMPANY_COLORS, GOOD, BAD, TICKER_COMPANY, chart

RANGES = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "2Y": 730}
FRAMES = 30  # Replay animation frames; each one carries a copy of the lines, so more frames = slower page


def render(data):
    st.subheader("Stock performance")
    df = data["stock_prices"]
    if df.empty:
        st.info("No stock data yet. Fill data/stock_prices.csv.")
        return
    c1, c2 = st.columns([2, 2])
    rng = c1.segmented_control("Range", list(RANGES), default="1Y", key="stk_range") or "1Y"
    mode = c2.segmented_control("View", ["Indexed to 100", "Price (USD)"], default="Indexed to 100", key="stk_mode") or "Indexed to 100"

    df = df.sort_values("date")
    sub = df[df["date"] >= df["date"].max() - timedelta(days=RANGES[rng])].copy()
    if mode.startswith("Indexed"):
        sub["v"] = sub["close"] / sub.groupby("ticker")["close"].transform("first") * 100
    else:
        sub["v"] = sub["close"]

    tickers = [t for t in TICKER_COMPANY if t in set(sub["ticker"])]
    cols = st.columns(len(tickers))
    for col, t in zip(cols, tickers):
        g = sub[sub["ticker"] == t]
        ret = (g["close"].iloc[-1] / g["close"].iloc[0] - 1) * 100
        col.metric("%s · %s" % (t, TICKER_COMPANY[t]), "$%s" % format(g["close"].iloc[-1], ",.2f"), "%+.1f%% over %s" % (ret, rng))

    # plain lists with short date strings: every animation frame repeats the data, so this keeps the payload small
    series = {t: (sub.loc[sub["ticker"] == t, "date"].dt.strftime("%Y-%m-%d").tolist(),
                  sub.loc[sub["ticker"] == t, "v"].round(2).tolist()) for t in tickers}
    fig = go.Figure()
    for t, (x, y) in series.items():  # trace order: line, end-marker for each ticker
        col = COMPANY_COLORS[TICKER_COMPANY[t]]
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=t, line=dict(width=2, color=col),
                                 hovertemplate=t + "<br>%{x|%b %d, %Y}<br>%{y:,.2f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=x[-1:], y=y[-1:], mode="markers+text", showlegend=False, textposition="middle right",
                                 text=["  %s %.1f" % (t, y[-1])], textfont=dict(color=col),
                                 marker=dict(size=8, color=col), hoverinfo="skip"))
    n = max(len(x) for x, _ in series.values())
    steps = sorted({max(2, round(n * i / FRAMES)) for i in range(1, FRAMES + 1)})  # ~FRAMES evenly spaced frames
    frames = []
    for k in steps:
        fd = []
        for x, y in series.values():
            kk = min(k, len(x))
            fd += [dict(type="scatter", x=x[:kk], y=y[:kk]), dict(type="scatter", x=x[kk - 1:kk], y=y[kk - 1:kk])]
        frames.append(dict(data=fd, name=str(k)))
    fig.frames = frames
    fig.update_layout(
        height=500, hovermode="x unified", yaxis_title="Indexed (start = 100)" if mode.startswith("Indexed") else "USD",
        xaxis=dict(rangeslider=dict(visible=True, thickness=0.06, bgcolor="rgba(255,255,255,0.04)")),
        updatemenus=[dict(type="buttons", showactive=False, x=0, y=1.13, direction="left", buttons=[
            dict(label="▶  Replay", method="animate", args=[None, dict(frame=dict(duration=60, redraw=True), transition=dict(duration=0), fromcurrent=False)])])])
    chart(fig, key="stk_chart")
    st.caption("Source: Yahoo Finance via yfinance (tier 2 market data). Indexed view starts every stock at 100 for a fair comparison.")
