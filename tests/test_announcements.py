"""Guard rails of the announcements extractor. No network, no API."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.announcements import canon, doc_type_for, fix_direction, page_date, parse_edges  # noqa: E402

DOC = ("Amazon will invest $5 billion in Anthropic today, with up to an additional $20 billion in the future. "
       "Anthropic commits to AWS as its primary cloud and training partner. Anthropic will secure up to 5 gigawatts of Trainium.")


def reply(*edges):
    return json.dumps({"edges": list(edges)})


def edge(**kw):
    base = {"from": "Amazon", "to": "Anthropic", "type": "investment", "description": "Amazon invests in Anthropic.",
            "amount_usd": 5_000_000_000, "quote": "Amazon will invest $5 billion in Anthropic today"}
    base.update(kw)
    return base


def test_good_edge_is_kept_with_amount_and_high_confidence():
    rows, problems = parse_edges("R-009", "2026-04-20", reply(edge()), DOC)
    assert problems == [] and rows == [["Amazon", "Anthropic", "investment", "Amazon invests in Anthropic.", "5000000000", "2026-04-20", "R-009", "high"]]


def test_fabricated_edge_is_dropped():
    rows, problems = parse_edges("R-009", "2026-04-20", reply(edge(**{"from": "Apple", "quote": "Apple will acquire Anthropic outright", "amount_usd": 9_000_000_000})), DOC)
    assert rows == [] and "dropped" in problems[0]


def test_unsupported_amount_is_removed_but_a_quoted_relationship_survives():
    rows, _ = parse_edges("R-009", "2026-04-20", reply(edge(amount_usd=7_000_000_000)), DOC)
    assert rows and rows[0][4] == ""  # quote is verbatim, but $7 billion is not on the page


def test_rules_reject_bad_types_self_loops_and_edges_without_the_five():
    bad = [edge(type="friendship"), edge(**{"from": "Anthropic"}), edge(**{"from": "Microsoft", "to": "Oracle"})]
    rows, problems = parse_edges("R-009", "2026-04-20", reply(*bad), DOC)
    assert rows == [] and len(problems) == 3


def test_canonical_names_dates_and_doc_types():
    assert canon("NVIDIA") == "Nvidia" and canon("Alphabet") == "Google" and canon("Microsoft") == "Microsoft"
    assert page_date('<meta property="article:published_time" content="2025-10-23T10:00:00Z">', "https://x.com/a") == "2025-10-23"
    assert page_date("<html></html>", "https://blogs.microsoft.com/blog/2025/10/28/the-next-chapter/") == "2025-10-28"
    assert page_date("<p>Oct 23, 2025</p>", "https://x.com/a") == "2025-10-23"
    assert doc_type_for("https://investor.nvidia.com/news/x") == "press_release" and doc_type_for("https://www.anthropic.com/news/x") == "blog"


def test_reversed_directions_are_corrected():
    assert fix_direction("Anthropic", "Microsoft", "cloud") == ("Microsoft", "Anthropic")      # provider -> customer
    assert fix_direction("Apple", "OpenAI", "distribution") == ("OpenAI", "Apple")            # maker -> integrator
    assert fix_direction("Google", "Apple", "distribution") == ("Google", "Apple")            # already right
    assert fix_direction("Anthropic", "Amazon", "investment") == ("Amazon", "Anthropic")      # investor -> investee
    assert fix_direction("Amazon", "Anthropic", "cloud") == ("Amazon", "Anthropic")


def test_billion_shorthand_amounts_are_confirmed():
    doc = "Amazon announces $5B Anthropic investment, up to $20B more. Amazon and Anthropic are partners."
    rows, problems = parse_edges("R-1", "2026-04-20", reply(edge(quote="made-up wording not on the page")), doc)
    assert rows and rows[0][4] == "5000000000" and problems == []


def test_generic_parties_are_rejected_and_financing_is_allowed():
    rows, problems = parse_edges("R-1", "2026-04-20", reply(edge(**{"to": "Google Cloud customers", "from": "Google", "type": "cloud"})), DOC)
    assert rows == [] and problems
    ok = edge(**{"from": "Nvidia", "to": "OpenAI", "type": "financing", "amount_usd": 105_000_000_000,
                 "quote": "guarantees, capped at a total of $105 billion"})
    doc = "Nvidia entered into guarantees, capped at a total of $105 billion, on behalf of OpenAI."
    rows, _ = parse_edges("A-12", "2026-08-26", reply(ok), doc)
    assert rows and rows[0][2] == "financing" and rows[0][4] == "105000000000"


def test_dedupe_keeps_amount_rows_and_earliest_dates():
    from collectors.announcements import dedupe
    a = ["Amazon", "Anthropic", "investment", "d1", "", "2026-05-28", "R-12", "high"]
    b = ["Amazon", "Anthropic", "investment", "d2", "5000000000", "2026-04-20", "R-4", "high"]
    c = ["Google", "Anthropic", "cloud", "d3", "", "2026-04-06", "R-8", "high"]
    d = ["Google", "Anthropic", "cloud", "d4", "", "2025-10-23", "R-6", "high"]
    out = dedupe([a, b, c, d])
    assert [r[3] for r in out] == ["d2", "d4"]  # amount row replaces the vaguer one; earliest of the duplicates survives


def test_normalize_fixes_known_mislabels():
    from collectors.announcements import normalize
    assert normalize("OpenAI", "Nvidia", "cloud") == ("Nvidia", "OpenAI", "supply")          # chips are supply
    assert normalize("OpenAI", "Oracle", "investment") == ("Oracle", "OpenAI", "cloud")      # compute deal, provider -> customer
    assert normalize("Nvidia", "OpenAI", "financing") == ("Nvidia", "OpenAI", "financing")


def test_investment_must_talk_about_investing():
    doc = "OpenAI, Oracle and SoftBank are developing two Stargate sites that can scale to 1.5 gigawatts."
    e = edge(**{"from": "SoftBank", "to": "OpenAI", "quote": "developing two Stargate sites that can scale to 1.5 gigawatts", "amount_usd": None,
                "description": "SoftBank and OpenAI are developing Stargate sites."})
    rows, problems = parse_edges("R-19", "2025-10-22", reply(e), doc)
    assert rows == [] and "does not talk about investing" in problems[0]


def test_paraphrased_quote_accepted_when_parties_share_a_paragraph_but_not_otherwise():
    doc = "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, or TSMC, to produce our wafers.\n\nUnrelated paragraph about Intel."
    e = edge(**{"from": "TSMC", "to": "Nvidia", "type": "supply", "amount_usd": None, "quote": "Nvidia uses TSMC to manufacture chips",
                "description": "TSMC manufactures wafers for Nvidia."})
    doc2 = "Nvidia relies on foundries such as Taiwan Semiconductor Manufacturing Company Limited, or TSMC, to produce its wafers."
    rows, _ = parse_edges("A-11", "2026-02-25", reply(e), doc2)
    assert rows and rows[0][0] == "TSMC" and rows[0][2] == "supply"
    far = edge(**{"from": "Intel", "to": "Nvidia", "type": "supply", "amount_usd": None, "quote": "Intel supplies Nvidia", "description": "Intel supplies Nvidia."})
    assert parse_edges("A-11", "2026-02-25", reply(far), "Nvidia designs chips.\n\nIntel makes CPUs.")[0] == []


def test_synonyms_and_own_products():
    g = edge(**{"from": "Nvidia", "to": "OpenAI", "type": "guarantee", "amount_usd": 105_000_000_000, "quote": "guarantees, capped at a total of $105 billion",
                "description": "Nvidia guarantees leases."})
    rows, _ = parse_edges("A-12", "2026-08-26", reply(g), "Nvidia entered into guarantees, capped at a total of $105 billion, for OpenAI.")
    assert rows and rows[0][2] == "financing"
    own = edge(**{"from": "Google", "to": "Google One", "type": "distribution", "amount_usd": None, "quote": "Google One offers Gemini",
                  "description": "Google One offers Gemini."})
    assert parse_edges("A-4", "2026-02-05", reply(own), "Google One offers Gemini models.")[0] == []


def test_filer_counts_as_present_in_its_own_filing():
    doc = "We utilize foundries, such as Taiwan Semiconductor Manufacturing Company Limited, or TSMC, to produce our wafers."
    e = edge(**{"from": "TSMC", "to": "Nvidia", "type": "supply", "amount_usd": None, "quote": "Nvidia buys wafers from TSMC",
                "description": "TSMC makes Nvidia's wafers."})
    assert parse_edges("A-11", "2026-02-25", reply(e), doc)[0] == []                       # an announcement must name both
    assert len(parse_edges("A-11", "2026-02-25", reply(e), doc, filer="Nvidia")[0]) == 1   # a filing's 'we' is the filer
