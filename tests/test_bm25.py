"""Tests for the BM25 lexical index — the keyword half of hybrid retrieval.

These are fully offline: BM25 is pure arithmetic over token counts, so a handful of
tiny hand-built chunks make the ranking predictable. The point this module must prove
is the *complement to dense*: an exact token match the embedder would miss is found
first by BM25.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from grc_rag.bm25 import BM25Index, tokenize
from grc_rag.chunking import Chunk
from grc_rag.retrieve import RetrievedChunk


def _chunk(idx: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"doc::{idx}",
        doc_id="doc",
        text=text,
        token_count=len(text.split()),
        start_token=idx,
    )


# --------------------------------------------------------------------------- #
# tokenize
# --------------------------------------------------------------------------- #
def test_tokenize_lowercases_splits_keeps_digits() -> None:
    # Punctuation splits; digits survive; the clause label "Article 5(1)" → 3 tokens.
    assert tokenize("Article 5(1)") == ["article", "5", "1"]


def test_tokenize_drops_empties_and_collapses_whitespace() -> None:
    assert tokenize("  the   PROVIDER, shall... ") == ["the", "provider", "shall"]


def test_tokenize_is_pure() -> None:
    text = "Prohibited AI practices"
    _ = tokenize(text)
    assert text == "Prohibited AI practices"  # unchanged


# --------------------------------------------------------------------------- #
# search — the exact-token win (the complement-to-dense argument)
# --------------------------------------------------------------------------- #
_CHUNKS = (
    _chunk(0, "AI systems shall be transparent to users."),
    _chunk(1, "The following AI practices are prohibited under this Regulation."),
    _chunk(2, "Providers must keep technical documentation up to date."),
    _chunk(3, "High-risk AI systems require a conformity assessment."),
)


def test_search_ranks_exact_token_match_first() -> None:
    index = BM25Index(_CHUNKS)
    results = index.search("prohibited practices", k=4)
    # Only chunk 1 carries the literal tokens "prohibited" + "practices".
    assert results[0].chunk.chunk_id == "doc::1"


def test_search_returns_retrieved_chunks_ordered_by_score_desc() -> None:
    index = BM25Index(_CHUNKS)
    results = index.search("high-risk conformity assessment", k=4)
    assert all(isinstance(r, RetrievedChunk) for r in results)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].chunk.chunk_id == "doc::3"


def test_search_caps_at_k() -> None:
    index = BM25Index(_CHUNKS)
    assert len(index.search("AI", k=2)) == 2


def test_search_k_larger_than_corpus_returns_all() -> None:
    index = BM25Index(_CHUNKS)
    assert len(index.search("AI", k=99)) == len(_CHUNKS)


# --------------------------------------------------------------------------- #
# Fail-fast
# --------------------------------------------------------------------------- #
def test_search_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        BM25Index(_CHUNKS).search("   ")


def test_search_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        BM25Index(_CHUNKS).search("AI", k=0)


def test_constructor_rejects_empty_corpus() -> None:
    with pytest.raises(ValueError, match="empty"):
        BM25Index(())


# --------------------------------------------------------------------------- #
# from_chunks_jsonl round-trip
# --------------------------------------------------------------------------- #
def test_from_chunks_jsonl_roundtrip(tmp_path) -> None:
    path = tmp_path / "chunks.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for chunk in _CHUNKS:
            handle.write(json.dumps(asdict(chunk)) + "\n")

    index = BM25Index.from_chunks_jsonl(path)
    assert len(index) == len(_CHUNKS)
    assert index.search("prohibited practices", k=1)[0].chunk.chunk_id == "doc::1"
