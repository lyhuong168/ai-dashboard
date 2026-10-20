"""Financials tab. Owner: Manny (Numbers); animation + styling by Reid. Manny: extend with YoY growth,
margins, segment mix, Q4 quarters. Keep using theme.chart() so everything matches.

Companies have different fiscal calendars, so every period is also mapped to the NEAREST calendar
quarter (e.g. Nvidia's quarter ending 2026-07-26 sits with Apple's ending 2026-06-27) for the race.
"""
import calendar
from datetime import date

import plotly.graph_objects as go
import streamlit as st

from app.theme import ACCENT, COMPANY_COLORS, MUTED, chart

NICE = {"revenue": "Revenue", "net_income": "Net income", "operating_income": "Operating income",
        "eps_diluted": "Diluted EPS", "cloud_revenue": "Google Cloud revenue",
        "data_center_revenue": "Nvidia Data Center revenue", "services_revenue": "Apple Services revenue",
        "capex": "Capital expenditures", "gross_margin_pct": "Gross margin %"}


def calendar_quarter(d):
    """'2026 Q2' for the calendar quarter whose end is nearest to date d."""
    d = d.date() if hasattr(d, "date") else d
    best = min((date(y, m, calendar.monthrange(y, m)[1]) for y in (d.year - 1, d.year, d.year + 1) for m in (3, 6, 9, 12)),
               key=lambda q: abs((q - d).days))
    return "%d Q%d" % (best.year, best.month // 3)


def _scaled(sub):
    """USD millions -> $B for display; EPS and percentages stay as they are."""
    unit = sub["unit"].iloc[0]
    if unit == "USD_millions":
        return sub["value"] / 1000.0, "$ billions"
    return sub["value"], "$ per share" if unit == "USD_per_share" else unit


def render(data):
    st.subheader("Financials")
    df = data["financials"]
    if df.empty:
        st.info("No financial data yet. Fill data/financials.csv.")
        return
    df = df.copy()
    df["cal_q"] = df["period_end"].map(calendar_quarter)

    metrics = sorted(df["metric"].unique(), key=lambda m: (m != "revenue", m))
    c1, c2 = st.columns([3, 2])
    metric = c1.segmented_control("Metric", metrics, default=metrics[0], format_func=lambda m: NICE.get(m, m), key="fin_metric") or metrics[0]
    view = c2.segmented_control("View", ["Race", "Trend", "Sequential change"], default="Race", key="fin_view") or "Race"

    sub = df[df["metric"] == metric].sort_values("period_end").copy()
    sub["y"], ylabel = _scaled(sub)
    if view == "Race":
        _race(sub, ylabel)
    elif view == "Trend":
        _trend(sub, ylabel)
    else:
        _sequential(sub)

    with st.expander("Data and sources"):
        st.dataframe(sub[["company", "period", "period_end", "metric", "value", "unit", "source_id"]])


def _race(sub, ylabel):
    quarters = list(dict.fromkeys(sub.sort_values("period_end")["cal_q"]))
    ymax = float(sub["y"].max()) * 1.18
    cos = [c for c in COMPANY_COLORS if c in set(sub["company"])]

    def frame_bars(q):
        s = sub[sub["cal_q"] == q].set_index("company")
        return go.Bar(x=cos, y=[float(s["y"].get(c, 0)) if c in s.index else 0 for c in cos],
                      marker=dict(color=[COMPANY_COLORS[c] for c in cos]),
                      text=[("%.1f" % s["y"][c]) if c in s.index else "" for c in cos], textposition="outside",
                      customdata=[[s["period"].get(c, ""), s["source_id"].get(c, "")] for c in cos],
                      hovertemplate="%{x}<br>%{y:,.2f}<br>%{customdata[0]} · %{customdata[1]}<extra></extra>")

    fig = go.Figure(data=[frame_bars(quarters[0])], frames=[go.Frame(data=[frame_bars(q)], name=q) for q in quarters])
    fig.update_layout(
        title=None, margin=dict(t=64, l=10, r=10, b=10),
        yaxis=dict(range=[0, ymax], title=ylabel), height=470, showlegend=False,
        updatemenus=[dict(type="buttons", showactive=False, x=0, y=1.13, direction="left", buttons=[
            dict(label="▶  Play", method="animate", args=[None, dict(frame=dict(duration=1100, redraw=True),
                                                                      transition=dict(duration=700, easing="cubic-in-out"), fromcurrent=True)]),
            dict(label="❚❚  Pause", method="animate", args=[[None], dict(frame=dict(duration=0), mode="immediate")])])],
        sliders=[dict(active=0, x=0.0, len=1.0, y=-0.02, currentvalue=dict(prefix="Quarter: ", font=dict(color=ACCENT)),
                      steps=[dict(label=q, method="animate", args=[[q], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                                                                transition=dict(duration=500))]) for q in quarters])])
    chart(fig, key="fin_race")
    st.caption("Press Play. Bars are each company's figure for that calendar quarter; hover for the fiscal label and source.")


def _trend(sub, ylabel):
    fig = go.Figure()
    for co in [c for c in COMPANY_COLORS if c in set(sub["company"])]:
        s = sub[sub["company"] == co]
        col = COMPANY_COLORS[co]
        fig.add_trace(go.Scatter(x=s["period_end"], y=s["y"], name=co, mode="lines+markers", line=dict(width=2, color=col),
                                 marker=dict(size=7, color=col),
                                 customdata=s[["period", "source_id"]].values,
                                 hovertemplate=co + "<br>%{y:,.2f}<br>%{customdata[0]} · %{customdata[1]}<extra></extra>"))
    fig.update_layout(yaxis_title=ylabel, height=470, hovermode="x unified")
    chart(fig, key="fin_trend")


def _sequential(sub):
    rows = []
    for co, s in sub.groupby("company"):
        s = s.sort_values("period_end")
        for prev, cur in zip(s.itertuples(), s.iloc[1:].itertuples()):
            if prev.value:
                rows.append({"company": co, "period": cur.period, "end": cur.period_end, "pct": (cur.value / prev.value - 1) * 100,
                             "src": "%s, %s" % (prev.source_id, cur.source_id)})
    if not rows:
        st.info("Need at least two quarters per company.")
        return
    fig = go.Figure()
    for co in COMPANY_COLORS:
        r = [x for x in rows if x["company"] == co]
        if r:
            fig.add_trace(go.Bar(name=co, x=[x["period"] for x in r], y=[x["pct"] for x in r], marker_color=COMPANY_COLORS[co],
                                 customdata=[x["src"] for x in r], hovertemplate=co + "<br>%{y:+.1f}% QoQ<br>%{customdata}<extra></extra>"))
    fig.update_layout(barmode="group", yaxis_title="% change vs previous quarter", height=470)
    chart(fig, key="fin_seq")
    st.markdown("<span style='color:%s'>Sequential (quarter-over-quarter), not year-over-year, and not seasonally adjusted: "
                "Apple's December quarter is always much larger than March, so its swings are seasonal.</span>" % MUTED,
                unsafe_allow_html=True)
