"""Guard rails of the LLM financial extractor. No API calls: the model reply is scripted."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.financials_from_releases import fiscal_label, parse_reply, to_row  # noqa: E402

DOC = ("Consolidated Alphabet revenues increased 24% to $119.8 billion. Net income was $34,500 million. "
       "Diluted earnings per share was $2.81. Google Cloud revenues increased 82% to $24.8 billion.")


def test_fiscal_labels_follow_each_company_calendar():
    assert fiscal_label("Google", date(2026, 6, 30)) == "FY2026Q2"
    assert fiscal_label("Apple", date(2026, 6, 27)) == "FY2026Q3"      # June quarter is Q3
    assert fiscal_label("Apple", date(2025, 12, 27)) == "FY2026Q1"     # December quarter opens the next fiscal year
    assert fiscal_label("Nvidia", date(2026, 7, 26)) == "FY2027Q2"     # matches "second quarter of fiscal year 2027"
    assert fiscal_label("Nvidia", date(2026, 1, 25)) == "FY2026Q4"


def test_unit_conversion_to_millions():
    assert to_row("Google", "A-007", date(2026, 6, 30), "revenue", {"value": 119.8, "scale": "billion"})[4:6] == ["119800", "USD_millions"]
    assert to_row("Google", "A-007", date(2026, 6, 30), "net_income", {"value": 34500, "scale": "million"})[4] == "34500"
    assert to_row("Google", "A-007", date(2026, 6, 30), "eps_diluted", {"value": 2.81, "scale": "per_share"})[4:6] == ["2.81", "USD_per_share"]
    assert to_row("Google", "A-007", date(2026, 6, 30), "revenue", {"value": -5, "scale": "million"}) is None
    assert to_row("Google", "A-007", date(2026, 6, 30), "revenue", {"value": 5, "scale": "parsecs"}) is None
    # the real failure the SEC cross-check caught: 40.77 labelled "million" when the figure was in billions
    assert to_row("Google", "A-007", date(2026, 6, 30), "operating_income", {"value": 40.77, "scale": "million"}) is None
    # and the second one: 112,107 (a table figure in millions) labelled "thousand" became 112.107
    assert to_row("Google", "A-007", date(2026, 6, 30), "net_income", {"value": 112107, "scale": "thousand"}) is None


def reply(**metrics):
    return json.dumps({"period_end": "2026-06-30", "metrics": metrics})


def test_good_extraction_becomes_rows():
    rows, problems = parse_reply("Google", "A-007", reply(
        revenue={"value": 119.8, "scale": "billion", "quote": "revenues increased 24% to $119.8 billion"},
        cloud_revenue={"value": 24.8, "scale": "billion", "quote": "Google Cloud revenues increased 82% to $24.8 billion"}), DOC)
    assert problems == [] and {r[3] for r in rows} == {"revenue", "cloud_revenue"}
    assert all(r[0] == "Google" and r[1] == "FY2026Q2" and r[6] == "A-007" for r in rows)


def test_fabricated_number_is_dropped():
    rows, problems = parse_reply("Google", "A-007", reply(
        revenue={"value": 130.0, "scale": "billion", "quote": "revenues increased 30% to $130.0 billion"}), DOC)
    assert rows == [] and "neither the quote nor the number" in problems[0]


def test_paraphrased_quote_with_a_real_number_is_kept():
    rows, problems = parse_reply("Google", "A-007", reply(
        net_income={"value": 34.5, "scale": "billion", "quote": "Net income came in at 34.5 billion dollars"}), DOC)
    assert problems == [] and rows[0][3:6] == ["net_income", "34500", "USD_millions"]


def test_quarter_must_end_shortly_before_the_filing_date():
    ok = reply(revenue={"value": 119.8, "scale": "billion", "quote": "revenues increased 24% to $119.8 billion"})
    rows, _ = parse_reply("Google", "A-007", ok, DOC, filed=date(2026, 7, 25))   # 25 days after 2026-06-30
    assert len(rows) == 1
    rows, problems = parse_reply("Google", "A-007", ok, DOC, filed=date(2026, 12, 1))  # 154 days: wrong column?
    assert rows == [] and "120 days" in problems[0]
    rows, problems = parse_reply("Google", "A-007", ok, DOC, filed=date(2026, 5, 1))   # filed BEFORE quarter end
    assert rows == []


def test_wrong_segment_metric_and_garbage_are_ignored():
    rows, _ = parse_reply("Google", "A-007", reply(
        data_center_revenue={"value": 1, "scale": "billion", "quote": "Google Cloud revenues increased 82%"}), DOC)
    assert rows == []  # data_center_revenue belongs to Nvidia, not Google
    rows, problems = parse_reply("Google", "A-007", "not json at all", DOC)
    assert rows == [] and "unusable reply" in problems[0]
