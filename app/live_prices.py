"""Near-real-time quotes for the header ticker: Yahoo Finance 1-minute bars via yfinance (tier 2 market data).

Display only. Nothing here is written to data/stock_prices.csv, so the Stock tab, the brief and the verifier keep
using the collected, sourced daily closes. One fetch is shared by every visitor for REFRESH_SECONDS; if Yahoo fails
or rate-limits, quotes() returns None and the header falls back to the last daily closes.
"""
import pandas as pd
import streamlit as st

import contract as C

ET = "America/New_York"
REFRESH_SECONDS = 30
LIVE_WITHIN_MINUTES = 20  # a bar older than this during market hours (holiday, outage) is not called live


@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def quotes():
    """{"rows": [{sym, price, chg}], "as_of": Timestamp (ET)} with chg vs the previous session's close, or None."""
    try:
        import yfinance as yf

        bars = yf.download(C.TICKERS, period="5d", interval="1m", progress=False, prepost=False, threads=False)["Close"]
    except Exception:  # network, rate limit, Yahoo format change: the caller falls back to daily closes
        return None
    rows, as_of = [], None
    for t in C.TICKERS:
        if t not in bars:
            continue
        s = bars[t].dropna()
        if s.empty:
            continue
        stamps = s.index.tz_convert(ET)
        before = s[stamps.date < stamps[-1].date()]  # earlier sessions; their last bar is the previous close
        if before.empty:
            continue
        price, prev = float(s.iloc[-1]), float(before.iloc[-1])
        rows.append({"sym": t, "price": price, "chg": (price / prev - 1) * 100})
        as_of = stamps[-1] if as_of is None else max(as_of, stamps[-1])
    return {"rows": rows, "as_of": as_of} if rows else None


def market_open(now):
    """Regular US session, 9:30 to 16:00 ET on weekdays (exchange holidays show as stale, see status)."""
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60


def status(as_of, now=None):
    """(kind, label) for the ticker badge: kind "live" while the market is open and the last bar is fresh."""
    now = now or pd.Timestamp.now(tz=ET)
    clock = as_of.strftime("%I:%M %p").lstrip("0")
    day = as_of.strftime("%b %d").replace(" 0", " ")
    if not market_open(now):
        return "closed", "MARKET CLOSED · last trade %s, %s ET" % (day, clock)
    if now - as_of < pd.Timedelta(minutes=LIVE_WITHIN_MINUTES):
        return "live", "LIVE · %s ET" % clock
    return "closed", "LAST TRADE %s, %s ET" % (day, clock)  # session hours but no fresh bar: holiday or feed delay
