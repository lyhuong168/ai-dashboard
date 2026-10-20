"""Tiny on-disk vector store: a numpy matrix + chunk metadata.

The corpus is a few hundred chunks, so exact cosine search in numpy is instant and needs
no native dependencies. build() reuses vectors for unchanged text so a refresh only pays
to embed NEW chunks.
"""
import json
import time
from pathlib import Path

import numpy as np


class VectorStore:
    def __init__(self, vectors, chunks, embedder_name, stats=None, built_at=None):
        self.vectors, self.chunks, self.embedder_name = vectors, chunks, embedder_name
        self.stats = stats or {}
        self.built_at = built_at

    @classmethod
    def build(cls, chunks, embedder, previous=None):
        reuse = {}
        if previous is not None and previous.embedder_name == embedder.name:
            reuse = {c["text_hash"]: v for c, v in zip(previous.chunks, previous.vectors)}
        todo = [i for i, c in enumerate(chunks) if c["text_hash"] not in reuse]
        fresh = embedder.embed([chunks[i]["text"] for i in todo]) if todo else None
        dim = fresh.shape[1] if fresh is not None else (next(iter(reuse.values())).shape[0] if reuse else 1)
        vectors = np.zeros((len(chunks), dim), dtype=np.float32)
        fresh_at = {i: row for i, row in zip(todo, fresh)} if fresh is not None else {}
        for i, c in enumerate(chunks):
            vectors[i] = fresh_at[i] if i in fresh_at else reuse[c["text_hash"]]
        old = {c["text_hash"] for c in previous.chunks} if previous is not None else set()
        new = {c["text_hash"] for c in chunks}
        stats = {"chunks": len(chunks), "embedded": len(todo), "reused": len(chunks) - len(todo),
                 "added": len(new - old), "removed": len(old - new)}
        return cls(vectors, chunks, embedder.name, stats, time.strftime("%Y-%m-%d %H:%M:%S"))

    def save(self, directory):
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        np.save(d / "vectors.npy", self.vectors)
        with open(d / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        (d / "meta.json").write_text(json.dumps(
            {"embedder": self.embedder_name, "n_chunks": len(self.chunks),
             "built_at": self.built_at, "stats": self.stats}, indent=2))

    @classmethod
    def load(cls, directory):
        d = Path(directory)
        if not (d / "meta.json").exists():
            return None
        meta = json.loads((d / "meta.json").read_text())
        chunks = [json.loads(line) for line in (d / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
        return cls(np.load(d / "vectors.npy"), chunks, meta["embedder"], meta.get("stats"), meta.get("built_at"))
