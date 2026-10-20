"""Hybrid retrieval: dense vectors + BM25 keywords, fused with Reciprocal Rank Fusion,
with metadata filters (company, trust tier, doc type) and per-company balancing."""
import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from rag import config
from rag.llm import HashingEmbedder, OpenAIEmbedder, _tokens
from rag.store import VectorStore

COMPANY_ALIASES = {
    "Google": ["google", "alphabet", "gemini", "deepmind", "googl"],
    "OpenAI": ["openai", "chatgpt", "gpt"],
    "Anthropic": ["anthropic", "claude"],
    "Nvidia": ["nvidia", "nvda", "cuda", "blackwell", "hopper"],
    "Apple": ["apple", "aapl", "iphone", "siri"],
}


def detect_companies(query):
    toks = set(_tokens(query))
    return [c for c, aliases in COMPANY_ALIASES.items() if toks & set(aliases)]


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.len.mean()) if len(docs) else 0.0
        df = Counter(t for d in self.tf for t in d)
        n = len(docs)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

    def scores(self, query_tokens):
        out = np.zeros(len(self.tf), dtype=np.float32)
        for t in set(query_tokens):
            if t not in self.idf:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    out[i] += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avgdl or 1)))
        return out


COMPANY_BOOST = 0.01  # about one rank-position's worth of RRF score


@dataclass
class Hit:
    chunk: dict
    score: float
    vec_rank: int = None
    bm25_rank: int = None


def _ranked(scores, mask, pool, positive_only=False):
    idx = [i for i in np.argsort(-scores) if mask[i] and (scores[i] > 0 or not positive_only)]
    return idx[:pool]


class Retriever:
    def __init__(self, store, embedder):
        if store.embedder_name != embedder.name:  # the lecture point: same model for chunks and query
            raise ValueError("store was built with %s but the query embedder is %s" % (store.embedder_name, embedder.name))
        self.store, self.embedder = store, embedder
        self.bm25 = BM25([_tokens(c["text"]) for c in store.chunks])

    def _mask(self, companies, max_tier, doc_types):
        ok = np.ones(len(self.store.chunks), dtype=bool)
        for i, c in enumerate(self.store.chunks):
            if companies and c["company"] not in companies:
                ok[i] = False
            if max_tier and int(c["tier"]) > max_tier:
                ok[i] = False
            if doc_types and c["doc_type"] not in doc_types:
                ok[i] = False
        return ok

    def search(self, query, k=6, companies=None, max_tier=None, doc_types=None, mode="hybrid", pool=30,
               prefer=None):
        """prefer: companies named in the question. A soft boost (not a filter), so partner
        documents that merely mention the company can still surface."""
        if not self.store.chunks:
            return []
        mask = self._mask(companies, max_tier, doc_types)
        if not mask.any():
            return []
        vrank = brank = []
        if mode in ("hybrid", "vector"):
            vrank = _ranked(self.store.vectors @ self.embedder.embed([query])[0], mask, pool)
        if mode in ("hybrid", "bm25"):
            brank = _ranked(self.bm25.scores(_tokens(query)), mask, pool, positive_only=True)
        fused, vpos, bpos = Counter(), {}, {}
        for r, i in enumerate(vrank):
            fused[i] += 1.0 / (60 + r + 1); vpos[i] = r + 1
        for r, i in enumerate(brank):
            fused[i] += 1.0 / (60 + r + 1); bpos[i] = r + 1
        if prefer:
            for i in fused:
                if self.store.chunks[i]["company"] in prefer:
                    fused[i] += COMPANY_BOOST
        return [Hit(self.store.chunks[i], s, vpos.get(i), bpos.get(i)) for i, s in fused.most_common(k)]

    def search_balanced(self, query, k=6, companies=None, **kw):
        """If the question names several companies, retrieve for each so none is crowded out."""
        names = companies or detect_companies(query)
        if len(names) < 2:
            return self.search(query, k=k, companies=companies, prefer=None if companies else names, **kw)
        per = max(2, math.ceil(k / len(names)))
        hits = [h for n in names for h in self.search(query, k=per, companies=[n], **kw)]
        return sorted(hits, key=lambda h: -h.score)[: max(k, per * len(names))]


def load_retriever(sample=False):
    """Load the saved store and pair it with the SAME embedder that built it."""
    store = VectorStore.load(config.store_dir(sample))
    if store is None:
        raise FileNotFoundError("no index yet: run  python -m rag build%s" % (" --sample" if sample else ""))
    emb = HashingEmbedder() if store.embedder_name == HashingEmbedder.name else OpenAIEmbedder(store.embedder_name)
    return Retriever(store, emb)
