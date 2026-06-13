"""Tests for dense retrieval.

Offline tests construct a tiny, hand-built vector store so the cosine ranking is
predictable, and inject a fake query encoder. The end-to-end check on the real
persisted index lives behind ``RUN_INTEGRATION``.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import asdict

import numpy as np
import pytest

from grc_rag import embeddings
from grc_rag.chunking import Chunk
from grc_rag.retrieve import DenseRetriever, RetrievedChunk
from conftest import FakeEncoder


def _chunk(idx: int, text: str) -> Chunk:
    return Chunk(chunk_id=f"doc::{idx}", doc_id="doc", text=text, token_count=1, start_token=idx)


# A 2-D, already unit-normalised store so we can predict cosine ordering by hand.
_CHUNKS = (_chunk(0, "A"), _chunk(1, "B"), _chunk(2, "C"))
_MATRIX = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], dtype=np.float32)


def _retriever_pointing_at_b() -> DenseRetriever:
    # The query maps to B's direction [0, 1]; scores become [0.0, 1.0, 0.8] → B, C, A.
    fake = FakeEncoder({"who is B?": [0.0, 1.0]}, dim=2)
    return DenseRetriever(_MATRIX, _CHUNKS, encoder=fake)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_retrieve_orders_by_cosine_desc() -> None:
    results = _retriever_pointing_at_b().retrieve("who is B?", k=3)
    assert [r.chunk.chunk_id for r in results] == ["doc::1", "doc::2", "doc::0"]
    assert results[0].score >= results[1].score >= results[2].score


def test_retrieve_caps_at_k() -> None:
    results = _retriever_pointing_at_b().retrieve("who is B?", k=2)
    assert len(results) == 2
    assert results[0].chunk.chunk_id == "doc::1"


def test_retrieve_k_larger_than_corpus_returns_all() -> None:
    results = _retriever_pointing_at_b().retrieve("who is B?", k=99)
    assert len(results) == len(_CHUNKS)


def test_retrieved_chunk_is_frozen() -> None:
    result = RetrievedChunk(chunk=_chunk(0, "A"), score=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 0.9  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Fail-fast
# --------------------------------------------------------------------------- #
def test_retrieve_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        _retriever_pointing_at_b().retrieve("who is B?", k=0)


def test_retrieve_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _retriever_pointing_at_b().retrieve("   ")


def test_constructor_rejects_empty_index() -> None:
    with pytest.raises(ValueError, match="empty index"):
        DenseRetriever(np.zeros((0, 2), dtype=np.float32), ())


def test_constructor_rejects_misalignment() -> None:
    with pytest.raises(ValueError, match="misalignment"):
        DenseRetriever(_MATRIX, _CHUNKS[:2])  # 3 vectors, 2 chunks


# --------------------------------------------------------------------------- #
# from_index round-trip (offline, fake encoder)
# --------------------------------------------------------------------------- #
def test_from_index_roundtrip(tmp_path) -> None:
    chunks = (_chunk(0, "alpha"), _chunk(1, "target clause"), _chunk(2, "gamma"))
    chunks_path = tmp_path / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk)) + "\n")

    # Query is mapped to the SAME pseudo-vector as chunk 1's text → chunk 1 ranks top.
    from conftest import _deterministic_vector

    fake = FakeEncoder({"find target": _deterministic_vector("target clause", 4)}, dim=4)
    out_dir = tmp_path / "index"
    embeddings.build_index(chunks_path, out_dir=out_dir, encoder=fake)

    retriever = DenseRetriever.from_index(out_dir, encoder=fake)
    assert len(retriever) == 3
    results = retriever.retrieve("find target", k=1)
    assert results[0].chunk.chunk_id == "doc::1"


# --------------------------------------------------------------------------- #
# Integration: retrieve over the real persisted corpus index. Off by default.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the real model + a built index; set RUN_INTEGRATION=1 to run",
)
def test_real_index_retrieves_relevant_chunk() -> None:
    from pathlib import Path

    retriever = DenseRetriever.from_index(Path("data/processed"))
    results = retriever.retrieve("What are the obligations for high-risk AI systems?", k=10)
    assert len(results) == 10
    assert any(r.chunk.doc_id == "eu-ai-act" for r in results)
