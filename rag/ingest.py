"""Turn data/raw documents + sources metadata into chunks ready for embedding."""
import csv
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

from rag import config


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html):
    """Readable text from an HTML page; table cells are separated with ' | '."""
    p = _TextExtractor()
    p.feed(html)
    text = re.sub(r"[ \t\xa0]+", " ", "".join(p.parts))
    return re.sub(r"\n\s*\n+", "\n\n", text)


def read_pages(path):
    """Return [(page_number_or_None, text)] for .txt/.md/.html/.htm/.pdf files."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return [(None, path.read_text(encoding="utf-8", errors="ignore"))]
    if ext in (".htm", ".html"):
        return [(None, html_to_text(path.read_text(encoding="utf-8", errors="ignore")))]
    if ext == ".pdf":
        from pypdf import PdfReader

        return [(i + 1, pg.extract_text() or "") for i, pg in enumerate(PdfReader(str(path)).pages)]
    raise ValueError("unsupported file type: %s" % path.name)


def chunk_text(text, size=None, overlap=None):
    """Paragraph-aware chunking with character overlap between neighbouring chunks."""
    size, overlap = size or config.CHUNK_CHARS, config.CHUNK_OVERLAP if overlap is None else overlap
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    pieces = []
    for p in filter(None, paras):
        while len(p) > size:  # very long paragraph: split at a sentence end if we can
            cut = max(p.rfind(". ", 0, size), p.rfind("; ", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 1 > size:
            chunks.append(cur)
            cur = (cur[-overlap:] + " " + piece) if overlap else piece
        else:
            cur = (cur + " " + piece).strip()
    if cur:
        chunks.append(cur)
    return chunks


def load_sources(base):
    """Read every data/sources/*.csv under base into {source_id: row}."""
    out = {}
    for f in sorted((Path(base) / "sources").glob("*.csv")):
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row.get("source_id"):
                    out[row["source_id"].strip()] = {k: (v or "").strip() for k, v in row.items()}
    return out


def build_chunks(base):
    """Chunk every source that has a local file. Returns (chunks, skipped_source_ids)."""
    base = Path(base)
    chunks, skipped = [], []
    for sid, src in load_sources(base).items():
        lp = src.get("local_path")
        if not lp or not (base / lp).exists():
            skipped.append(sid)
            continue
        n = 0
        for page, text in read_pages(base / lp):
            for piece in chunk_text(text):
                chunks.append({
                    "chunk_id": "%s#%03d" % (sid, n),
                    "text": piece,
                    "text_hash": hashlib.sha256(piece.encode()).hexdigest()[:16],
                    "page": page,
                    **{k: src[k] for k in ("source_id", "company", "title", "url", "publisher",
                                           "doc_type", "tier", "published_date")},
                })
                n += 1
    return chunks, skipped
