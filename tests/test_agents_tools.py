"""Verifier + Analyst tests on the synthetic sample data (no network, no cost)."""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import analyst  # noqa: E402
from agents.verifier import _variants, verify  # noqa: E402
from rag import config  # noqa: E402

SAMPLE = config.data_dir(sample=True)


def by_row(report, text):
    return next(f for f in report["findings"] if text in f["row"])


def test_variants_cover_common_formats():
    v = _variants("1111.1", "USD_millions")
    assert {"1111.1", "1,111.1"} <= v
    assert "1.30" in _variants("1.3", "USD_per_share")  # real case: Nvidia EPS stored 1.3, printed $1.30
    assert "$4.00" in _variants("4", "usd") and "$0.50" in _variants("0.5", "usd")
    assert "44.1" in _variants("44100", "USD_millions")  # billions


def test_sample_data_is_all_confirmed():
    rep = verify(SAMPLE)
    s = rep["summary"]
    assert s["not_found"] == 0 and s["confirmed"] >= 8
    # financials fully confirmed against the synthetic filings
    assert all(f["status"] == "confirmed" for f in rep["findings"] if f["table"] == "financials")


def test_verifier_catches_a_planted_mismatch(tmp_path):
    """Copy the sample set, change one number, and make sure the Verifier flags exactly that row."""
    dst = tmp_path / "data"
    shutil.copytree(SAMPLE, dst)
    fin = dst / "financials.csv"
    fin.write_text(fin.read_text().replace("1111.1", "9999.9"))
    rep = verify(dst)
    bad = [f for f in rep["findings"] if f["status"] == "not_found"]
    assert len(bad) == 1 and "9999.9" in bad[0]["row"] and bad[0]["source_id"] == "SAMPLE-001"


def test_no_document_is_reported_not_hidden(tmp_path):
    dst = tmp_path / "data"
    shutil.copytree(SAMPLE, dst)
    (dst / "raw" / "Nvidia" / "SAMPLE-001.txt").unlink()
    rep = verify(dst)
    assert by_row(rep, "Nvidia FY2026Q1")["status"] == "no_document"


def test_analyst_latest_and_growth():
    latest = {r["company"]: r for r in analyst.latest_metric(True, "revenue")}
    assert latest["Google"]["value"] == 4444.4 and latest["Nvidia"]["period"] == "FY2026Q2"
    g = analyst.growth(True, "Google", "revenue")[0]
    assert g["qoq_growth_pct"] == round((4444.4 / 3333.3 - 1) * 100, 2) and "SAMPLE-002" in g["source_ids"]
    assert "quarter-over-quarter" in g["basis"]  # never let sequential change be mistaken for year-over-year


def test_workload_cost_orders_cheapest_first():
    costs = analyst.workload_cost(True)
    assert [c["usd"] for c in costs] == sorted(c["usd"] for c in costs)
    a = next(c for c in costs if c["model"] == "sample-model-a")
    assert a["usd"] == round(1.00 + 0.2 * 4.00, 4)


def test_stock_return_and_partnerships():
    ret = {r["ticker"]: r for r in analyst.stock_return(True, days=30)}
    assert set(ret) == {"GOOGL", "NVDA", "AAPL"} and ret["AAPL"]["return_pct"] > 0
    assert len(analyst.partnerships_of(True, "OpenAI")) == 2


def test_upcoming_events_windows_and_the_explicit_nothing_scheduled_note():
    from datetime import date
    inside = analyst.upcoming_events(True, days=7, today=date(2025, 2, 24))      # sample event is 2025-02-26
    assert inside[0]["bucket"] == "in window" and inside[0]["days_until"] == 2 and inside[0]["source_id"] == "SAMPLE-001"
    empty = analyst.upcoming_events(True, days=7, today=date(2025, 1, 1))        # event is 56 days away
    assert "No events" in empty[0]["note"] and empty[1]["bucket"] == "after window"


def test_guidance_is_scored_against_what_was_reported():
    import pandas as pd
    fin = pd.DataFrame({"company": ["Nvidia"] * 2, "period": ["FY2027Q2", "FY2027Q3"], "metric": ["revenue"] * 2,
                        "value": [96221.0, 110500.0], "source_id": ["A-021", "A-099"]})
    guide = pd.DataFrame({"company": ["Nvidia"] * 3, "metric": ["revenue"] * 3, "target_period": ["FY2027Q2", "FY2027Q3", "FY2027Q4"],
                          "value": [91000.0, 108000.0, 120000.0], "tolerance_pct": [2.0, 2.0, 2.0], "unit": ["USD_millions"] * 3,
                          "source_id": ["A-022", "A-021", "A-099"], "issued_date": pd.to_datetime(["2026-05-20", "2026-08-26", "2026-11-20"])})
    r = analyst.evaluate_guidance(fin, guide)
    assert r[0]["result"] == "above the guided range" and r[0]["vs_midpoint_pct"] == round((96221 / 91000 - 1) * 100, 2)
    assert r[1]["result"] == "above the guided range" or r[1]["result"] == "within the guided range"
    assert r[2]["result"].startswith("pending")


def test_stock_moves_use_trading_day_windows():
    m = {x["ticker"]: x for x in analyst.stock_moves(True)}
    assert m["AAPL"]["chg_1d_pct"] > 0 and m["AAPL"]["chg_1m_pct"] is None and m["AAPL"]["range_52w"][0] < m["AAPL"]["range_52w"][1]
