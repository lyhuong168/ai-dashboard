"""Outlook parsers: dates, scheduled price changes, guidance. Pure text, no network."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.outlook import guidance_rows, next_period, parse_event_date, price_change_events, promo_events  # noqa: E402


def test_earnings_date_needs_a_matching_weekday():
    txt = "will hold its quarterly conference call on Wednesday, October 28, at 1:30pm Pacific Time (4:30pm Eastern Time)."
    d, when = parse_event_date(txt, default_year=2026)
    assert d == date(2026, 10, 28) and when.startswith("1:30pm")
    assert parse_event_date("on Thursday, October 28 at 1:30pm", default_year=2026) is None  # Oct 28, 2026 is a Wednesday
    d, _ = parse_event_date("on Monday, November 2, 2026 at 2:00 p.m. PT", default_year=2020)
    assert d == date(2026, 11, 2)
    assert parse_event_date("no dates here", default_year=2026) is None


def test_scheduled_price_changes_are_read_from_the_page():
    page = ("\ngemini-4-argon\n\nInput price\tNot available\t$2.00 through November 30, 2026.\n$4.00 starting December 1, 2026.\n"
            "Output price (including thinking tokens)\tNot available\t$10.00 through November 30, 2026.\n$20.00 starting December 1, 2026.\n")
    ev = price_change_events(page)
    assert [(e[1], e[2]) for e in ev] == [("price_change", date(2026, 12, 1))] * 2
    assert "gemini-4-argon: input price rises from $2.00 to $4.00" in ev[0][3] and "output price rises from $10.00 to $20.00" in ev[1][3]


def test_promotion_end_dates():
    ev = promo_events("GPT-5.6 Sol’s promotional pricing is available at least through November 21, 2026.")
    assert ev[0][1:3] == ("promo_end", date(2026, 11, 21)) and "GPT-5.6 Sol" in ev[0][3]


def test_guidance_midpoint_tolerance_and_target_quarter():
    txt = ("Revenue is expected to be $108.0 billion, plus or minus 2%. NVIDIA is not assuming any China revenue. "
           "GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points.")
    rows = guidance_rows(txt, "Nvidia", "FY2027Q2", "A-021", "2026-08-26")
    assert rows[0] == ["Nvidia", "revenue", "FY2027Q3", "108000", "2", "USD_millions", "A-021", "2026-08-26"]
    assert rows[1][1:6] == ["gross_margin_pct", "FY2027Q3", "74.0", "0.5", "percent"]
    assert guidance_rows("Revenue grew a lot.", "Apple", "FY2026Q3", "A-017", "2026-07-30") == []   # nothing stated, nothing invented
    assert next_period("FY2027Q4") == "FY2028Q1" and next_period("nonsense") is None


def test_real_snapshot_layout_has_each_table_cell_on_its_own_line():
    page = ("\ngemini-4-argon\n\nStandard\n\n Input price | \n Not available | \n $2.00 through November 30, 2026.\n$4.00 starting December 1, 2026. | \n\n"
            " Output price (including thinking tokens) | \n Not available | \n $10.00 through November 30, 2026.\n$20.00 starting December 1, 2026. | \n")
    ev = price_change_events(page)
    assert len(ev) == 2 and ev[0][2] == date(2026, 12, 1) and "gemini-4-argon" in ev[0][3]
    promo = "Priority processing was renamed Fast mode on July 30,\n2026. GPT-5.6 Sol’s promotional pricing is available at least through\nNovember 21, 2026."
    p = promo_events(promo)
    assert len(p) == 1 and p[0][2] == date(2026, 11, 21) and p[0][3].startswith("GPT-5.6 Sol")


def test_only_tracked_models_and_only_the_first_tier_are_kept():
    page = ("\ngemini-4-argon\n\nInput price | \n $2.00 through November 30, 2026.\n$4.00 starting December 1, 2026. |\n"
            "Batch\n\nInput price | \n $1.00 through November 30, 2026.\n$2.00 starting December 1, 2026. |\n"
            "\ngemini-3.8-flash-tts\n\nInput price | \n $0.50 through December 31, 2026.\n$1.00 starting January 1, 2027. |\n")
    ev = price_change_events(page, only_models={"gemini-4-argon"})
    assert len(ev) == 1 and "from $2.00 to $4.00" in ev[0][3]          # Standard tier, not the Batch $1 -> $2
