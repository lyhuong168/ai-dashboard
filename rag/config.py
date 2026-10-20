"""Shared settings for the RAG + agent code. Reads .env if python-dotenv is installed."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # tests and offline runs work without it
    pass

EMBED_MODEL = os.getenv("OPENAI_MODEL_EMBED", "text-embedding-3-small")
QA_MODEL = os.getenv("OPENAI_MODEL_QA", "gpt-4o")
EXTRACT_MODEL = os.getenv("OPENAI_MODEL_EXTRACT", "gpt-4o-mini")
MAX_USD_PER_RUN = float(os.getenv("MAX_USD_PER_RUN", "2.00"))

CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150


def data_dir(sample=False):
    return ROOT / "data" / ("sample" if sample else "")


def store_dir(sample=False):
    return ROOT / "vectorstore" / ("sample" if sample else "real")
