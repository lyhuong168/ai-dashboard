"""RAG tests. All offline and free: they use the hashing embedder and FakeChat."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import config  # noqa: E402
from rag.answer import answer, cited_tags  # noqa: E402
from rag.ingest import build_chunks, chunk_text  # noqa: E402
from rag.llm import BudgetExceeded, CostTracker, FakeChat, HashingEmbedder  # noqa: E402
from rag.retrieve import Retriever, detect_companies  # noqa: E402
from rag.store import VectorStore  # noqa: E402

SAMPLE = config.data_dir(sample=True)


@pytest.fixture(scope="module")
def retriever():
    chunks, skipped = build_chunks(SAMPLE)
    assert skipped == ["SAMPLE-006"]  # market data has no document
    emb = HashingEmbedder()
    return Retriever(VectorStore.build(chunks, emb), emb)


def test_chunks_carry_source_metadata():
    chunks, _ = build_chunks(SAMPLE)
    assert chunks and all(c["source_id"].startswith("SAMPLE-") and c["tier"] in ("1", "2") for c in chunks)
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


def test_chunk_text_overlap_and_size():
    text = "\n\n".join("Sentence number %d is here. " % i * 12 for i in range(30))
    chunks = chunk_text(text, size=600, overlap=100)
    assert len(chunks) > 3 and all(len(c) <= 600 + 100 + 5 for c in chunks)


def test_retrieves_the_right_document(retriever):
    top = retriever.search_balanced("What was Nvidia revenue in the second quarter?", k=3)[0].chunk
    assert top["source_id"] == "SAMPLE-001"
    top = retriever.search("input token price per million for sample-model-b", k=3)[0].chunk
    assert top["source_id"] == "SAMPLE-004"


def test_exact_number_found_by_keywords(retriever):
    hit = retriever.search("net income 666.6", k=1, mode="bm25")[0]
    assert hit.chunk["source_id"] == "SAMPLE-002"


def test_filters(retriever):
    assert {h.chunk["company"] for h in retriever.search("pricing", k=6, companies=["Anthropic"])} == {"Anthropic"}
    assert all(h.chunk["tier"] == "1" for h in retriever.search("partnership investment", k=6, max_tier=1))
    assert retriever.search("anything", companies=["Apple"]) == []  # no Apple documents indexed


def test_balanced_retrieval_covers_each_named_company(retriever):
    hits = retriever.search_balanced("Compare OpenAI and Anthropic input token pricing", k=4)
    assert {"OpenAI", "Anthropic"} <= {h.chunk["company"] for h in hits}
    assert detect_companies("what does Claude cost vs Gemini") == ["Google", "Anthropic"]


def test_embedder_mismatch_is_rejected(retriever):
    class Other(HashingEmbedder):
        name = "other"

    with pytest.raises(ValueError):
        Retriever(retriever.store, Other())


def test_rebuild_reuses_vectors(retriever):
    chunks, _ = build_chunks(SAMPLE)
    again = VectorStore.build(chunks, HashingEmbedder(), previous=retriever.store)
    assert again.stats["embedded"] == 0 and again.stats["reused"] == len(chunks) and again.stats["removed"] == 0
    fewer = VectorStore.build(chunks[:-1], HashingEmbedder(), previous=retriever.store)
    assert fewer.stats["removed"] == 1


def test_store_roundtrip(retriever, tmp_path):
    retriever.store.save(tmp_path)
    loaded = VectorStore.load(tmp_path)
    assert loaded.embedder_name == retriever.store.embedder_name and loaded.vectors.shape == retriever.store.vectors.shape
    assert VectorStore.load(tmp_path / "missing") is None


def test_answer_with_valid_citation(retriever):
    chat = FakeChat("Nvidia reported $2,222.2 million in the second quarter [S1].")
    res = answer("What was Nvidia revenue in the second quarter?", retriever, chat=chat)
    assert res["warnings"] == [] and res["citations"][0]["source_id"] == "SAMPLE-001"


def test_answer_flags_missing_and_bogus_citations(retriever):
    uncited = answer("Nvidia revenue?", retriever, chat=FakeChat("Revenue was big."))
    assert "answer has no citations" in uncited["warnings"]
    bogus = answer("Nvidia revenue?", retriever, chat=FakeChat("Revenue was big [S99]."))
    assert any("not retrieved" in w for w in bogus["warnings"])
    assert cited_tags("see [S2, S10] and [S2][S1]") == ["1", "2", "10"]


def test_offline_answer_is_extractive(retriever):
    res = answer("Nvidia revenue?", retriever, chat=None)
    assert res["offline"] and res["warnings"] == []
    assert len(res["citations"]) == 3  # the three passages it quotes, each tagged [S#]


def test_cost_cap_stops_spending():
    t = CostTracker(cap_usd=0.01)
    t.add("x", "gpt-4o", 100, 100)  # ~$0.00125
    with pytest.raises(BudgetExceeded):
        t.add("x", "gpt-4o", 1_000_000, 0)
    with pytest.raises(BudgetExceeded):
        t.check()
