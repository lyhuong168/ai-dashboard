"""Command line:  python -m rag build [--sample] [--offline]   |   python -m rag ask "question" [--sample]"""
import argparse

from rag import config
from rag.answer import answer
from rag.ingest import build_chunks
from rag.llm import TRACKER, get_chat, get_embedder
from rag.retrieve import load_retriever
from rag.store import VectorStore


def build_index(sample=False, offline=None):
    """Chunk + embed + save. Unchanged chunks reuse their vectors, so refreshes only pay for new text.
    Returns (store, skipped_source_ids)."""
    out = config.store_dir(sample)
    chunks, skipped = build_chunks(config.data_dir(sample))
    store = VectorStore.build(chunks, get_embedder(offline=True if offline else None), previous=VectorStore.load(out))
    store.save(out)
    return store, skipped


def cmd_build(args):
    store, skipped = build_index(args.sample, args.offline)
    print("index: %s  embedder: %s" % (config.store_dir(args.sample), store.embedder_name))
    print("stats:", store.stats)
    if skipped:
        print("sources without a local file (not indexed): %s" % ", ".join(skipped))
    print("cost:", TRACKER.summary())


def cmd_ask(args):
    result = answer(args.question, load_retriever(args.sample), chat=get_chat(), k=args.k)
    print(result["answer"])
    for c in result["citations"]:
        print("  [%s] %s (%s, tier %s) %s" % (c["tag"], c["title"], c["source_id"], c["tier"], c["url"]))
    for w in result["warnings"]:
        print("  WARNING:", w)
    print("cost:", TRACKER.summary()["total_usd"], "USD")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="chunk, embed and save the index")
    b.add_argument("--sample", action="store_true", help="use data/sample")
    b.add_argument("--offline", action="store_true", help="force the free hashing embedder")
    b.set_defaults(fn=cmd_build)
    a = sub.add_parser("ask", help="ask a question with citations")
    a.add_argument("question")
    a.add_argument("--sample", action="store_true")
    a.add_argument("-k", type=int, default=6)
    a.set_defaults(fn=cmd_ask)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
