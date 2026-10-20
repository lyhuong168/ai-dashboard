"""Brief guards and the facts-only fallback. No API, no network."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import brief as B  # noqa: E402
from rag.llm import FakeChat  # noqa: E402

EV = {"NVD-F1": {"text": "Nvidia guided FY2027Q3 revenue to $108.0B plus or minus 2% (issued 2026-08-26).", "tier": "1", "source_id": "A-021"},
      "R-9#1": {"text": "2026-10-16 Reuters: Chipmaker shares fell 1.43% on Friday.", "tier": "2", "source_id": "R-9"}}


def test_numbers_must_appear_in_the_cited_evidence():
    assert B.check_bullet("Nvidia guided revenue to $108.0B, plus or minus 2%.", ["NVD-F1"], EV) == (True, "")
    ok, why = B.check_bullet("Nvidia guided revenue to $110B.", ["NVD-F1"], EV)
    assert not ok and "110" in why                                       # an invented number is rejected
    ok, why = B.check_bullet("Shares fell 1.43%.", ["NVD-F1"], EV)       # right number, wrong evidence
    assert not ok
    assert B.check_bullet("Shares fell 1.43% (Reuters).", ["R-9#1"], EV)[0]
    assert B.check_bullet("Revenue is up.", [], EV) == (False, "no citation")
    assert B.check_bullet("Revenue is up.", ["nope"], EV)[1].startswith("unknown citation")


def test_number_normalisation_is_format_tolerant():
    assert B._norm_nums("$1,234.50 and 0.5% and 3 quarters") == {"1234.5", "0.5"}   # commas/zeros normalised, lone digits ignored
    assert "108" in B._norm_nums("$108.0 billion") and "2026" in B._norm_nums("on 2026-10-28")


def test_facts_only_brief_on_sample_data_has_cited_bullets():
    b = B.build_brief(sample=True, chat=None, today=date(2025, 2, 20))
    assert b["llm"] is False and b["dropped"] == []
    assert any("earnings call" in x["text"] for c in b["companies"].values() for x in c["bullets"])
    assert b["week_ahead"][0]["bucket"] == "in window"                    # the sample event is 6 days away
    for c in b["companies"].values():
        for x in c["bullets"]:
            assert all(i in b["evidence"] for i in x["cites"])


def test_llm_bullets_with_invented_numbers_are_dropped_and_reported():
    good_id = next(iter(B.build_facts(True, date(2025, 2, 20))["Nvidia"]))["id"]

    def reply(_):
        return json.dumps({"overall": [{"text": "Nvidia has an earnings call coming up.", "cites": [good_id]}],
                           "companies": {"Nvidia": {"headline": "h", "bullets": [{"text": "Nvidia will grow 45% next year.", "cites": [good_id]}]}}})
    b = B.build_brief(sample=True, chat=FakeChat(fn=reply), today=date(2025, 2, 20))
    assert len(b["overall"]) == 1 and b["companies"]["Nvidia"]["bullets"] == []
    assert any("45" in d["why"] or "number" in d["why"] for d in b["dropped"])
