"""Cited question answering over retrieved chunks, with a citation check on the output."""
import re

from rag import config

SYSTEM = (
    "You are a careful research analyst for an enterprise AI buyer/investor. Answer ONLY from the numbered "
    "context passages. Cite every factual claim with its tag like [S1] or [S2][S3]. Quote numbers exactly as "
    "written, with their units and period. If the context does not contain the answer, say so plainly; never "
    "fill gaps from memory. Note when a source is tier 2 (press) rather than tier 1 (primary)."
)


def format_context(hits):
    blocks = []
    for i, h in enumerate(hits, 1):
        c = h.chunk
        blocks.append("[S%d] %s | %s | tier %s | published %s | %s\n%s" % (
            i, c["company"], c["title"], c["tier"], c["published_date"], c["source_id"], c["text"]))
    return "\n\n".join(blocks)


def cited_tags(text):
    tags = []
    for group in re.findall(r"\[([^\]]+)\]", text):
        tags += re.findall(r"S(\d+)", group)
    return sorted(set(tags), key=int)


def answer(question, retriever, chat=None, k=6, **filters):
    """Returns {answer, citations, sources, warnings, offline}. chat=None gives an extractive answer."""
    hits = retriever.search_balanced(question, k=k, **filters)
    if not hits:
        return {"answer": "No relevant sources were found in the index.", "citations": [], "sources": [],
                "warnings": ["empty retrieval"], "offline": chat is None}
    sources = [{"tag": "S%d" % i, "chunk_id": h.chunk["chunk_id"], "source_id": h.chunk["source_id"],
                "company": h.chunk["company"], "title": h.chunk["title"], "url": h.chunk["url"],
                "tier": h.chunk["tier"], "published_date": h.chunk["published_date"],
                "score": round(h.score, 4), "text": h.chunk["text"]} for i, h in enumerate(hits, 1)]
    warnings = []
    if chat is None:
        text = "(offline mode, no LLM key) Most relevant passages:\n" + "\n".join(
            "- [%s] %s" % (s["tag"], s["text"][:300]) for s in sources[:3])
    else:
        text = chat.complete(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": "Context:\n%s\n\nQuestion: %s" % (format_context(hits), question)}],
            model=config.QA_MODEL, label="qa")
    tags = cited_tags(text)
    known = {s["tag"][1:] for s in sources}
    if chat is not None and not tags:
        warnings.append("answer has no citations")
    if [t for t in tags if t not in known]:
        warnings.append("answer cites sources that were not retrieved: S" + ", S".join(t for t in tags if t not in known))
    citations = [s for s in sources if s["tag"][1:] in tags]
    return {"answer": text, "citations": citations, "sources": sources, "warnings": warnings, "offline": chat is None}
