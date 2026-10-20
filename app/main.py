"""Dashboard shell. Run from the repo root:  streamlit run app/main.py

Owner: Reid. Teammates only edit their own files in tabs/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import components, keys, theme  # noqa: E402
from app.data_loader import has_real_data, load_data  # noqa: E402
from rag import config  # noqa: E402
from tabs import ask, brief, financials, overview, partnerships, pricing, sources, stock  # noqa: E402

st.set_page_config(page_title="AI Corporations Dashboard", page_icon="◈", layout="wide")
theme.apply()
keys.apply()  # this session's OpenAI key (visitor's own, team key, or none) before anything calls the API


@st.cache_data(ttl=300)
def get_data(use_sample):
    return load_data(use_sample)


def last_run(sample):
    f = config.ROOT / "runs" / ("sample" if sample else "real") / "latest.json"
    return json.loads(f.read_text()) if f.exists() else None


def status_line(sample, run):
    if sample:
        return "DEMO MODE · SAMPLE DATA · NOT REAL NUMBERS"
    if not run:
        return "LIVE · no refresh recorded yet"
    v = run["verification"]
    return "LIVE · REFRESHED %s · %d/%d FIGURES VERIFIED" % (run["timestamp"][:16], v["confirmed"], v["checked"])


def ticker_rows(data):
    df = data["stock_prices"]
    rows = []
    for t, g in df.sort_values("date").groupby("ticker"):
        if len(g) >= 2:
            last, prev = g.iloc[-1]["close"], g.iloc[-2]["close"]
            rows.append({"sym": t, "price": float(last), "chg": float((last / prev - 1) * 100)})
    return rows


def flip_mode():
    st.session_state.use_sample = not st.session_state.use_sample


real_ok = has_real_data()
if "use_sample" not in st.session_state:
    st.session_state.use_sample = not real_ok
use_sample = st.session_state.use_sample
data = get_data(use_sample)
run = last_run(use_sample)

components.hero(
    "AI Corporations Intelligence",
    status_line(use_sample, run),
    ["Google · OpenAI · Anthropic · Nvidia · Apple, tracked from primary sources.",
     "Every figure cites a source. Every source gets a trust tier.",
     "RAG retrieves the evidence. Agents compute, verify and explain it.",
     "Cross-checked against the SEC's own structured data."],
    height=250)
c_tick, c_ai, c_mode = st.columns([4, 1, 1], vertical_alignment="center")
c_tick.markdown(components.ticker_html(ticker_rows(data)), unsafe_allow_html=True)
with c_ai:
    keys.control()
c_mode.button("Switch to live data" if use_sample else "Switch to demo data", on_click=flip_mode,
              icon=":material/sync_alt:", width="stretch", disabled=use_sample and not real_ok,
              help="No real data yet. Run refresh.py --collect first." if use_sample and not real_ok else None)
if use_sample:
    st.warning("Showing SAMPLE data. These are placeholder numbers, not real figures.")

tab_names = ["Overview", "Brief", "Financials", "Stock", "Pricing", "Partnerships", "Ask the Analyst", "Sources & Freshness"]
t_over, t_brief, t_fin, t_stock, t_price, t_part, t_ask, t_src = st.tabs(tab_names)

with t_over:
    overview.render(data, use_sample)
with t_brief:
    brief.render(data, use_sample)
with t_fin:
    financials.render(data)
with t_stock:
    stock.render(data)
with t_price:
    pricing.render(data, use_sample)
with t_part:
    partnerships.render(data)
with t_ask:
    ask.render(data, use_sample)
with t_src:
    sources.render(data, use_sample)
