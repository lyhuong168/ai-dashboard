"""Agent graph tests: offline rules path and a scripted-LLM path. Free and deterministic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.graph import ask, rules_route  # noqa: E402
from rag import config  # noqa: E402
from rag.ingest import build_chunks  # noqa: E402
from rag.llm import FakeChat, HashingEmbedder  # noqa: E402
from rag.retrieve import Retriever  # noqa: E402
from rag.store import VectorStore  # noqa: E402


@pytest.fixture(scope="module")
def factory():
    chunks, _ = build_chunks(config.data_dir(sample=True))
    emb = HashingEmbedder()
    r = Retriever(VectorStore.build(chunks, emb), emb)
    return lambda sample: r


def test_rules_route():
    assert rules_route("What does Anthropic say about safety?") == ["rag"]
    assert rules_route("Which model is cheapest for a standard workload?") == ["rag", "analyst"]
    assert rules_route("Can I trust these revenue numbers? verify them") == ["rag", "analyst", "verify"]


def test_offline_pricing_question_uses_analyst_numbers(factory):
    s = ask("Which model is cheapest for a standard workload?", sample=True, chat=None, retriever_factory=factory)
    assert s["route"] == ["rag", "analyst"]
    assert "sample-model-c" in s["answer"] and "workload_cost" in s["answer"]
    assert [t.split(":")[0] for t in s["trace"]] == ["supervisor", "researcher", "analyst", "writer"]


def test_offline_verify_question_runs_the_verifier(factory):
    s = ask("Can you verify the revenue figures?", sample=True, chat=None, retriever_factory=factory)
    assert "verifier" in [t.split(":")[0] for t in s["trace"]]
    assert s["verification"]["summary"]["not_found"] == 0 and "rows confirmed" in s["answer"]


def test_verified_figures_become_citable_passages(factory):
    s = ask("Can you verify the revenue figures?", sample=True, chat=None, retriever_factory=factory)
    quotes = [x for x in s["rag"]["sources"] if "(verified figure:" in x["text"]]
    assert quotes, "confirmed figures should be quoted from their documents"
    tags = [x["tag"] for x in s["rag"]["sources"]]
    assert len(tags) == len(set(tags)) and tags == ["S%d" % i for i in range(1, len(tags) + 1)]
    for q in quotes:  # the quote really contains the figure it vouches for
        figure = q["text"].split("(verified figure:")[1].split("=")[1].split()[0]
        digits = figure.replace(".0", "")
        assert any(v in q["text"].split("(verified figure:")[0].replace(",", "") for v in {digits, "%g" % (float(figure) / 1000)})


def test_simple_question_skips_the_analyst(factory):
    s = ask("What did management say about customer demand?", sample=True, chat=None, retriever_factory=factory)
    assert s["route"] == ["rag"]
    assert [t.split(":")[0] for t in s["trace"]] == ["supervisor", "researcher", "writer"]
    assert "analysis" not in s or not s["analysis"]


def test_llm_path_cites_and_flags_bad_citations(factory):
    def script(messages):
        sys_prompt = messages[0]["content"]
        if "supervisor" in sys_prompt:
            return '["rag", "analyst"]'
        return "Cheapest is sample-model-c (SAMPLE-007) [S1] and also [S42]."

    s = ask("Which model is cheapest for a standard workload?", sample=True, chat=FakeChat(fn=script), retriever_factory=factory)
    assert s["route"] == ["rag", "analyst"]
    assert any("S42" in w for w in s["warnings"])
    assert s["citations"] and all(c["tag"] == "S1" for c in s["citations"])


def test_llm_router_garbage_falls_back_to_rules(factory):
    s = ask("Which model is cheapest?", sample=True, chat=FakeChat("no idea"), retriever_factory=factory)
    assert s["route"] == rules_route("Which model is cheapest?")


def test_stream_yields_steps_then_tokens_then_final(factory):
    from agents.graph import ask_stream

    ev = list(ask_stream("Which model is cheapest for a standard workload?", sample=True, chat=None, retriever_factory=factory))
    kinds = [e["type"] for e in ev]
    assert kinds[-1] == "final" and "write_start" in kinds and kinds.index("write_start") < kinds.index("token")
    assert [e["node"] for e in ev if e["type"] == "step"] == ["supervisor", "rag", "analyst"]
    final = ev[-1]["state"]
    assert "".join(e["text"] for e in ev if e["type"] == "token") == final["answer"]
    blocking = ask("Which model is cheapest for a standard workload?", sample=True, chat=None, retriever_factory=factory)
    assert final["answer"] == blocking["answer"]  # streaming and blocking paths agree


def test_stream_with_llm_tokens_and_citation_check(factory):
    from agents.graph import ask_stream

    chat = FakeChat(fn=lambda m: '["rag"]' if "supervisor" in m[0]["content"] else "Short answer [S1] and [S77].")
    ev = list(ask_stream("What did management say about customer demand?", sample=True, chat=chat, retriever_factory=factory))
    toks = [e["text"] for e in ev if e["type"] == "token"]
    assert len(toks) > 3 and "".join(toks).strip() == "Short answer [S1] and [S77]."
    assert any("S77" in w for w in ev[-1]["state"]["warnings"])


def test_missing_index_degrades_gracefully():
    def boom(sample):
        raise FileNotFoundError("no index yet")

    s = ask("Which model is cheapest for a standard workload?", sample=True, chat=None, retriever_factory=boom)
    assert any("no index" in w for w in s["warnings"]) and "workload_cost" in s["answer"]
