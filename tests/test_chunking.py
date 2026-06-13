"""Tests for token-based chunking.

These pin the behaviour that downstream retrieval relies on: chunks are sized in
tokens, neighbours overlap, ids are unique and traceable, and bad inputs fail
loudly. If a future "improvement" breaks one of these, the test goes red before
the regression reaches retrieval.
"""

from __future__ import annotations

import pytest

from grc_rag.chunking import Chunk, chunk_document, count_tokens


def test_empty_document_yields_no_chunks() -> None:
    assert chunk_document("doc", "") == ()
    assert chunk_document("doc", "   \n  ") == ()


def test_short_document_is_a_single_chunk() -> None:
    chunks = chunk_document("nist", "AI systems should be valid and reliable.")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "nist::0"
    assert chunks[0].doc_id == "nist"
    assert chunks[0].start_token == 0


def test_long_document_splits_with_overlap() -> None:
    # ~1500 tokens of filler -> must produce multiple chunks.
    text = " ".join(f"clause{i}" for i in range(1500))
    chunks = chunk_document("eu-ai-act", text, target_tokens=500, overlap_tokens=100)

    assert len(chunks) > 1
    # ids are sequential and unique
    assert [c.chunk_id for c in chunks] == [f"eu-ai-act::{i}" for i in range(len(chunks))]
    # neighbours advance by exactly stride = target - overlap
    assert chunks[1].start_token - chunks[0].start_token == 400
    # every chunk respects the size budget
    assert all(c.token_count <= 500 for c in chunks)


def test_returns_immutable_frozen_chunks() -> None:
    chunk = chunk_document("doc", "some text here")[0]
    assert isinstance(chunk, Chunk)
    with pytest.raises(Exception):
        chunk.text = "mutated"  # type: ignore[misc]  # frozen dataclass


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_tokens": 0},
        {"target_tokens": -5},
        {"overlap_tokens": 700},  # overlap >= target
        {"overlap_tokens": -1},
    ],
)
def test_invalid_parameters_fail_fast(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        chunk_document("doc", "text", **kwargs)


def test_empty_doc_id_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_document("  ", "text")


def test_count_tokens_is_positive_for_real_text() -> None:
    assert count_tokens("The EU AI Act defines high-risk systems.") > 0
