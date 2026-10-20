"""Analyst tools: deterministic pandas computations over the contract CSVs.

Numbers shown to users come from these functions, never from an LLM's arithmetic.
Each function returns plain dicts/lists plus the source_ids behind the numbers.
"""
from datetime import date, timedelta

import pandas as pd

from app.data_loader import load_data


def _data(sample):
    return load_data(use_sample=sample)


def latest_metric(sample, metric):
    """Most recent value of a metric per company, with period and source."""
    df = _data(sample)["financials"]
    df = df[df["metric"] == metric]
    if df.empty:
        return []
    last = df.sort_values("period_end").groupby("company").tail(1)
    return [{"company": r.company, "period": r.period, "value": float(r.value), "unit": r.unit,
             "source_id": r.source_id} for r in last.itertuples()]


def growth(sample, company, metric):
    """Sequential (quarter-over-quarter) change in %, oldest to newest. NOT year-over-year and NOT
    seasonally adjusted: Apple's December quarter, for example, is always far larger than March's."""
    df = _data(sample)["financials"]
    df = df[(df["company"] == company) & (df["metric"] == metric)].sort_values("period_end")
    out = []
    for prev, cur in zip(df.itertuples(), df.iloc[1:].itertuples()):
        if prev.value:
            out.append({"period": cur.period, "qoq_growth_pct": round((cur.value / prev.value - 1) * 100, 2),
                        "basis": "quarter-over-quarter (sequential, not seasonally adjusted)",
                        "source_ids": [prev.source_id, cur.source_id]})
    return out


def private_revenue(sample, company=None):
    """Revenue figures private companies stated themselves (run-rate = annualized, not quarterly), oldest first."""
    df = _data(sample)["private_revenue"]
    if company:
        df = df[df["company"] == company]
    return [{"company": r.company, "metric": r.metric, "as_of": str(r.as_of.date()), "value": float(r.value), "unit": r.unit,
             "bound": r.bound, "source_id": r.source_id} for r in df.sort_values("as_of").itertuples()]


def workload_cost(sample, input_tokens=1_000_000, output_tokens=200_000):
    """Cost of a standard workload on every model in token_pricing, cheapest first."""
    df = _data(sample)["token_pricing"]
    if df.empty:
        return []
    latest = df.sort_values("captured_date").groupby(["company", "model"]).tail(1)
    rows = [{"company": r.company, "model": r.model,
             "usd": round(input_tokens / 1e6 * r.input_usd_per_1m + output_tokens / 1e6 * r.output_usd_per_1m, 4),
             "source_id": r.source_id, "captured_date": str(r.captured_date.date())} for r in latest.itertuples()]
    return sorted(rows, key=lambda x: x["usd"])


def price_changes(sample):
    """Models with more than one captured_date: how list prices moved."""
    df = _data(sample)["token_pricing"].sort_values("captured_date")
    out = []
    for (co, model), g in df.groupby(["company", "model"]):
        if len(g) > 1:
            a, b = g.iloc[0], g.iloc[-1]
            out.append({"company": co, "model": model,
                        "input_change_pct": round((b.input_usd_per_1m / a.input_usd_per_1m - 1) * 100, 1),
                        "output_change_pct": round((b.output_usd_per_1m / a.output_usd_per_1m - 1) * 100, 1),
                        "from": str(a.captured_date.date()), "to": str(b.captured_date.date())})
    return out


def stock_return(sample, days=30):
    """Percent change in close over the last `days` calendar days, per ticker."""
    df = _data(sample)["stock_prices"]
    if df.empty:
        return []
    out = []
    for t, g in df.sort_values("date").groupby("ticker"):
        end = g.iloc[-1]
        past = g[g["date"] <= end["date"] - pd.Timedelta(days=days)]
        start = past.iloc[-1] if len(past) else g.iloc[0]
        out.append({"ticker": t, "from": str(start["date"].date()), "to": str(end["date"].date()),
                    "return_pct": round((end["close"] / start["close"] - 1) * 100, 2)})
    return out


def partnerships_of(sample, company):
    """Every edge touching a company."""
    df = _data(sample)["partnerships"]
    sub = df[(df["from_company"] == company) | (df["to_company"] == company)]
    return sub.drop(columns=[c for c in ("amount_usd",) if sub[c].isna().all()]).to_dict("records")


def upcoming_events(sample, days=7, today=None):
    """Scheduled events inside the window, plus the next few after it. Never a prediction: only dated, sourced rows.
    If nothing is scheduled in the window, a note row says so explicitly."""
    df = _data(sample)["events"]
    today = today or date.today()
    end = today + timedelta(days=days)
    rows = []
    for r in df.sort_values("event_date").itertuples():
        d = r.event_date.date()
        rows.append({"company": r.company, "type": r.event_type, "date": d.isoformat(), "days_until": (d - today).days,
                     "what": r.description, "status": r.status, "source_id": r.source_id})
    inside = [dict(r, bucket="in window") for r in rows if 0 <= r["days_until"] <= days]
    later = [dict(r, bucket="after window") for r in rows if r["days_until"] > days][:5]
    note = [] if inside else [{"note": "No events for the five companies are scheduled between %s and %s." % (today.isoformat(), end.isoformat())}]
    return note + inside + later


def evaluate_guidance(fin, guide):
    """Company guidance vs what the company then reported (revenue). fin/guide are the contract DataFrames."""
    out = []
    actual = {(r.company, r.period): (r.value, r.source_id) for r in fin[fin["metric"] == "revenue"].itertuples()}
    for g in guide[guide["metric"] == "revenue"].sort_values("issued_date").itertuples():
        tol = float(g.tolerance_pct) if pd.notna(g.tolerance_pct) else 0.0
        lo, hi = g.value * (1 - tol / 100), g.value * (1 + tol / 100)
        row = {"company": g.company, "period": g.target_period, "guided_mid_musd": float(g.value), "range_musd": [round(lo, 1), round(hi, 1)],
               "issued": str(g.issued_date.date()), "guidance_source": g.source_id}
        a = actual.get((g.company, g.target_period))
        if a is None:
            row["result"] = "pending (not reported yet)"
        else:
            val = float(a[0])
            row.update({"actual_musd": val, "actual_source": a[1], "vs_midpoint_pct": round((val / g.value - 1) * 100, 2),
                        "result": "above the guided range" if val > hi else "below the guided range" if val < lo else "within the guided range"})
        out.append(row)
    return out


def guidance_track_record(sample):
    d = _data(sample)
    return evaluate_guidance(d["financials"], d["guidance"])


def stock_moves(sample):
    """Price changes over 1, 5 and 21 trading days plus the 52-week range, per ticker (Yahoo Finance data, tier 2)."""
    df = _data(sample)["stock_prices"]
    out = []
    for t, g in df.sort_values("date").groupby("ticker"):
        c = g["close"].reset_index(drop=True)
        last = float(c.iloc[-1])
        pct = lambda n: round((last / float(c.iloc[-1 - n]) - 1) * 100, 2) if len(c) > n else None
        year = g[g["date"] >= g["date"].max() - timedelta(days=365)]["close"]
        out.append({"ticker": t, "as_of": str(g["date"].iloc[-1].date()), "close": round(last, 2), "chg_1d_pct": pct(1), "chg_5d_pct": pct(5),
                    "chg_1m_pct": pct(21), "range_52w": [round(float(year.min()), 2), round(float(year.max()), 2)]})
    return out
