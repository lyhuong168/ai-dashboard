"""Cross-check logic with scripted SEC facts (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.crosscheck import compare, quarter_value  # noqa: E402


def facts(entries, concept="Revenues", unit="USD"):
    return {"facts": {"us-gaap": {concept: {"units": {unit: entries}}}}}


Q2 = {"start": "2026-04-01", "end": "2026-06-30", "val": 119_800_000_000, "filed": "2026-07-23", "accn": "0001-26-000001"}
H1 = {"start": "2026-01-01", "end": "2026-06-30", "val": 230_000_000_000, "filed": "2026-07-23", "accn": "0001-26-000001"}  # 6 months: must be ignored


def row(value, metric="revenue", end="2026-06-30"):
    return {"company": "Google", "period": "FY2026Q2", "period_end": end, "metric": metric, "value": value, "source_id": "A-007"}


def test_picks_the_three_month_value_not_year_to_date():
    assert quarter_value(facts([H1, Q2]), "revenue", "2026-06-30")[0] == 119_800.0


def test_agree_differ_and_missing():
    f = {"Google": facts([H1, Q2])}
    out = compare([row("119800"), row("119700"), row("5", metric="cloud_revenue"), row("119800", end="2026-03-31")], f)
    assert [x["status"] for x in out["findings"]] == ["agrees", "agrees", "no_independent_source", "no_independent_source"]
    out = compare([row("100000")], f)  # 16% off
    assert out["findings"][0]["status"] == "differs" and out["summary"]["differs"] == 1


def test_eps_uses_per_share_units():
    f = {"Google": facts([{"start": "2026-04-01", "end": "2026-06-30", "val": 2.81, "filed": "2026-07-23"}],
                         concept="EarningsPerShareDiluted", unit="USD/shares")}
    assert compare([row("2.81", metric="eps_diluted")], f)["findings"][0]["status"] == "agrees"


def test_company_without_facts_is_reported_not_crashed():
    assert compare([row("1")], {})["findings"][0]["status"] == "no_independent_source"
