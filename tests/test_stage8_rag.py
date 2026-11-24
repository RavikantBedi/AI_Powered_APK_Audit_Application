"""Stage 8 tests: RAG retrieval accuracy and strict per-client isolation.

No LLM key needed — retrieval is pure TF-IDF cosine similarity in Python.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_stage1.db")
os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="agency-test-configs-"))
os.environ["KB_DIR"] = tempfile.mkdtemp(prefix="agency-test-kb-")

import pytest

from app.modules import knowledge_base as kb

DOC_A = b"""
Sharma Dental Clinic Price List

Root canal treatment costs Rs. 4500 to Rs. 8000 depending on the tooth.
Braces (metal) cost Rs. 35000 for the full treatment, including monthly
adjustments for 18 months. Ceramic braces cost Rs. 55000.

Refund policy: consultation fees are non-refundable. Treatment fees paid
in advance are refundable within 7 days if treatment has not started.
"""

DOC_B = b"""
Verma Realty Site Visit Policy

Site visits are free and can be scheduled any day except Sunday.
Booking amount for any flat is Rs. 1,00,000 and is adjusted against
the final price. Cancellation within 15 days gets a full refund of
the booking amount.
"""


@pytest.fixture(autouse=True)
def isolate_kb_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DIR", str(tmp_path))
    yield


def test_retrieval_finds_relevant_chunk():
    kb.add_documents(1, "pricelist.txt", DOC_A)
    results = kb.retrieve(1, "How much do ceramic braces cost?")
    assert results, "expected at least one relevant chunk"
    assert any("55000" in r.text for r in results)
    assert all(r.source == "pricelist.txt" for r in results)


def test_retrieval_respects_min_score_for_unrelated_query():
    kb.add_documents(1, "pricelist.txt", DOC_A)
    results = kb.retrieve(1, "what is the weather like in Antarctica penguins snow")
    assert results == []  # nothing relevant enough -> treated as low confidence


def test_client_data_isolation():
    """Client A's documents must never be retrievable for client B, even
    when both are indexed and B's query shares vocabulary with A's docs."""
    kb.add_documents(1, "pricelist.txt", DOC_A)
    kb.add_documents(2, "site_visit.txt", DOC_B)

    a_results = kb.retrieve(1, "what is the refund policy")
    b_results = kb.retrieve(2, "what is the refund policy")

    assert a_results and all(r.source == "pricelist.txt" for r in a_results)
    assert b_results and all(r.source == "site_visit.txt" for r in b_results)
    # cross-check: neither result set contains text unique to the other doc
    assert not any("booking amount" in r.text.lower() for r in a_results)
    assert not any("braces" in r.text.lower() for r in b_results)


def test_reupload_replaces_prior_chunks_for_same_source():
    kb.add_documents(1, "pricelist.txt", DOC_A)
    updated = b"Root canal treatment now costs Rs. 9999 flat rate for all teeth."
    kb.add_documents(1, "pricelist.txt", updated)

    results = kb.retrieve(1, "root canal cost")
    texts = " ".join(r.text for r in results)
    assert "9999" in texts
    assert "4500" not in texts  # stale chunk from the old version is gone


def test_list_and_delete_sources():
    kb.add_documents(1, "a.txt", DOC_A)
    kb.add_documents(1, "b.txt", DOC_B)
    sources = {s["source"] for s in kb.list_sources(1)}
    assert sources == {"a.txt", "b.txt"}

    removed = kb.delete_source(1, "a.txt")
    assert removed > 0
    sources = {s["source"] for s in kb.list_sources(1)}
    assert sources == {"b.txt"}


def test_unsupported_file_type_rejected():
    with pytest.raises(ValueError):
        kb.add_documents(1, "notes.docx", b"whatever")


def test_no_index_returns_empty_not_error():
    assert kb.retrieve(999, "anything") == []
    assert kb.list_sources(999) == []
