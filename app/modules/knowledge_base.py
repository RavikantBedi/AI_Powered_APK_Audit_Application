"""Stage 8: Knowledge grounding (RAG).

Each client can upload documents (txt/pdf/csv) in addition to (or instead
of) the flat FAQ config. Documents are chunked and indexed with TF-IDF
cosine similarity — no external embedding API required, so retrieval works
even with zero LLM keys configured. Each client's index lives in its own
file under kb_store/client_<id>.json; nothing is ever loaded across clients.

This is intentionally not a vector DB — at the scale of one small business's
docs (a few PDFs, a price sheet), an in-process TF-IDF index is simpler to
run, ship, and reason about than adding Postgres+pgvector or a hosted store.
"""
import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger("agency.kb")

_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "kb_store"
CHUNK_SIZE = 800       # characters per chunk
CHUNK_OVERLAP = 150    # characters shared between consecutive chunks
TOP_K = 4
MIN_SCORE = 0.08       # below this, retrieval counts as "nothing relevant"


def _kb_dir() -> Path:
    return Path(os.getenv("KB_DIR", str(_DEFAULT_DIR)))


def _store_path(client_id: int) -> Path:
    return _kb_dir() / f"client_{client_id}.json"


# Common English stopwords excluded so a query like "what is the weather"
# can't score a false-positive match on a doc purely via "the"/"in"/"is" —
# especially likely to happen with small per-client corpora (a few chunks).
_STOPWORDS = frozenset("""
a an the this that these those is are was were be been being to of in on
for with as by at from up down out over under again further then once here
there when where why how all any both each few more most other some such
no nor not only own same so than too very can will just don should now it
its it's i you he she we they them his her their our your my me and or but
if do does did doing have has had having what which who whom
""".split())


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def chunk_text(text: str, source: str) -> list[dict]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        # Prefer breaking on a sentence/space boundary near the end.
        if end < len(text):
            boundary = text.rfind(". ", start, end)
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"text": chunk, "source": source})
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".csv"):
        return data.decode("utf-8-sig", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    raise ValueError(f"Unsupported document type: {filename} (use .txt, .md, .csv, or .pdf)")


@dataclass
class KBIndex:
    client_id: int
    chunks: list[dict] = field(default_factory=list)   # [{text, source}]
    vocab: dict[str, int] = field(default_factory=dict)  # term -> index
    idf: list[float] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)  # sparse-as-dense, small corpora only

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id, "chunks": self.chunks,
            "vocab": self.vocab, "idf": self.idf, "vectors": self.vectors,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KBIndex":
        return cls(client_id=d["client_id"], chunks=d["chunks"], vocab=d["vocab"],
                   idf=d["idf"], vectors=d["vectors"])


def load_index(client_id: int) -> KBIndex | None:
    path = _store_path(client_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return KBIndex.from_dict(json.load(f))


def _save_index(index: KBIndex) -> None:
    _kb_dir().mkdir(parents=True, exist_ok=True)
    with open(_store_path(index.client_id), "w", encoding="utf-8") as f:
        json.dump(index.to_dict(), f, ensure_ascii=False)


def _build_tfidf(chunks: list[dict]) -> tuple[dict[str, int], list[float], list[list[float]]]:
    docs_tokens = [_tokenize(c["text"]) for c in chunks]
    vocab: dict[str, int] = {}
    for tokens in docs_tokens:
        for t in set(tokens):
            vocab.setdefault(t, len(vocab))

    n_docs = len(docs_tokens)
    df = [0] * len(vocab)
    for tokens in docs_tokens:
        for t in set(tokens):
            df[vocab[t]] += 1
    idf = [math.log((n_docs + 1) / (d + 1)) + 1 for d in df]

    vectors = []
    for tokens in docs_tokens:
        counts = Counter(tokens)
        vec = [0.0] * len(vocab)
        for t, c in counts.items():
            vec[vocab[t]] = (c / max(len(tokens), 1)) * idf[vocab[t]]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vocab, idf, vectors


def add_documents(client_id: int, filename: str, data: bytes, replace_source: bool = True) -> int:
    """Chunk+index a new document for this client. Returns chunk count added.

    replace_source=True re-indexes (drops old chunks from the same filename)
    so re-uploading an updated price sheet doesn't duplicate stale facts.
    """
    text = extract_text(filename, data)
    new_chunks = chunk_text(text, source=filename)
    if not new_chunks:
        raise ValueError(f"No extractable text in {filename}")

    existing = load_index(client_id)
    prior_chunks = existing.chunks if existing else []
    if replace_source:
        prior_chunks = [c for c in prior_chunks if c["source"] != filename]
    all_chunks = prior_chunks + new_chunks

    vocab, idf, vectors = _build_tfidf(all_chunks)
    index = KBIndex(client_id=client_id, chunks=all_chunks, vocab=vocab, idf=idf, vectors=vectors)
    _save_index(index)
    logger.info("client=%s indexed %s -> %d chunks (total %d)",
               client_id, filename, len(new_chunks), len(all_chunks))
    return len(new_chunks)


def list_sources(client_id: int) -> list[dict]:
    index = load_index(client_id)
    if not index:
        return []
    counts = Counter(c["source"] for c in index.chunks)
    return [{"source": src, "chunks": n} for src, n in counts.items()]


def delete_source(client_id: int, source: str) -> int:
    index = load_index(client_id)
    if not index:
        return 0
    remaining = [c for c in index.chunks if c["source"] != source]
    removed = len(index.chunks) - len(remaining)
    if removed:
        vocab, idf, vectors = _build_tfidf(remaining) if remaining else ({}, [], [])
        _save_index(KBIndex(client_id=client_id, chunks=remaining, vocab=vocab, idf=idf, vectors=vectors))
    return removed


def _vectorize_query(query: str, vocab: dict[str, int], idf: list[float]) -> list[float]:
    tokens = _tokenize(query)
    counts = Counter(tokens)
    vec = [0.0] * len(vocab)
    for t, c in counts.items():
        if t in vocab:
            vec[vocab[t]] = (c / max(len(tokens), 1)) * idf[vocab[t]]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@dataclass
class RetrievedChunk:
    text: str
    source: str
    score: float


def retrieve(client_id: int, query: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
    """Top-k relevant chunks for this client only. Empty list = nothing indexed
    or nothing relevant enough (caller should treat this as low confidence)."""
    index = load_index(client_id)
    if not index or not index.chunks:
        return []
    qvec = np.array(_vectorize_query(query, index.vocab, index.idf))
    if not qvec.any():
        return []
    mat = np.array(index.vectors)
    scores = mat @ qvec
    order = np.argsort(-scores)[:top_k]
    results = [
        RetrievedChunk(text=index.chunks[i]["text"], source=index.chunks[i]["source"], score=float(scores[i]))
        for i in order if scores[i] >= MIN_SCORE
    ]
    return results
