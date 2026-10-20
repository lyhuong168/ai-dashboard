"""Load the contract CSVs into pandas DataFrames for the Streamlit app."""
from pathlib import Path

import pandas as pd

import contract as C

ROOT = Path(__file__).resolve().parent.parent
DATE_COLS = {
    "financials": ["period_end", "as_of"],
    "stock_prices": ["date"],
    "token_pricing": ["captured_date"],
    "partnerships": ["date"],
    "sources": ["published_date", "retrieved_date"],
    "events": ["event_date"],
    "guidance": ["issued_date"],
    "private_revenue": ["as_of"],
}


def _read(path, columns, date_cols):
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"source_id": str})
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


_CACHE = {}


def _stamp(base):
    """Names + modification times of every CSV we read: changes whenever a file is edited or refreshed."""
    files = list(base.glob("*.csv")) + list((base / "sources").glob("*.csv"))
    return tuple(sorted((f.name, f.stat().st_mtime_ns) for f in files))


def load_data(use_sample=False):
    """Return {"financials", "stock_prices", "token_pricing", "partnerships", "sources"} DataFrames.
    Parsed CSVs are cached until a file changes; callers get copies, so they can modify them freely."""
    base = ROOT / "data" / ("sample" if use_sample else "")
    stamp = _stamp(base)
    hit = _CACHE.get(use_sample)
    if not hit or hit[0] != stamp:
        hit = _CACHE[use_sample] = (stamp, _load(base))
    return {k: v.copy() for k, v in hit[1].items()}


def _load(base):
    data = {}
    for fname, schema in C.SCHEMAS.items():
        key = fname.replace(".csv", "")
        data[key] = _read(base / fname, [c for c, _, _ in schema], DATE_COLS[key])
    src_cols = [c for c, _, _ in C.SOURCES_SCHEMA]
    parts = [_read(f, src_cols, DATE_COLS["sources"]) for f in sorted((base / "sources").glob("*.csv"))]
    parts = [p for p in parts if not p.empty]
    data["sources"] = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=src_cols)
    return data


def has_real_data():
    """True once any real (non-sample) table has rows."""
    d = load_data(use_sample=False)
    return any(not df.empty for k, df in d.items() if k != "sources")
