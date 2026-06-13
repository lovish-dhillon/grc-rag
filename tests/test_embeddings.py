"""Tests for embedding + vector-store building.

Offline unit tests use a fake encoder (see ``conftest.py``) to assert our own
guarantees — normalisation, shape, immutability, row-aligned persistence,
idempotency. The *meaningful* properties that only a real semantic model can
provide — 384 dimensions, unit norm, and "meaning beats keyword" ordering — are
exercised by integration tests behind ``RUN_INTEGRATION``.
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
from conftest import FakeEncoder


def _write_chunks_jsonl(path, chunks) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk)) + "\n")


def _chunk(idx: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"doc::{idx}",
        doc_id="doc",
        text=text,
        token_count=len(text.split()),
        start_token=0,
    )


# --------------------------------------------------------------------------- #
# Normalisation is OUR guarantee — testable without the real model
# --------------------------------------------------------------------------- #
def test_embed_matrix_normalises_rows() -> None:
    fake = FakeEncoder({"a": [3.0, 4.0], "b": [0.0, 5.0]}, dim=2)
    matrix = embeddings.embed_matrix(["a", "b"], encoder=fake)
    norms = np.linalg.norm(matrix, axis=1)
    assert np.allclose(norms, 1.0)
    assert np.allclose(matrix[0], [0.6, 0.8])  # 3-4-5 triangle → unit


def test_embed_matrix_handles_zero_vector() -> None:
    fake = FakeEncoder({"a": [0.0, 0.0]}, dim=2)
    matrix = embeddings.embed_matrix(["a"], encoder=fake)
    assert np.allclose(matrix[0], [0.0, 0.0])  # no NaN from div-by-zero


def test_embed_matrix_empty_input() -> None:
    matrix = embeddings.embed_matrix([], encoder=FakeEncoder())
    assert matrix.shape == (0, embeddings.EMBEDDING_DIM)


def test_embed_matrix_rejects_non_2d_encoder() -> None:
    class BadEncoder:
        def encode(self, texts, convert_to_numpy=True, **kwargs):
            return np.array([1.0, 2.0, 3.0])  # 1-D — wrong

    with pytest.raises(ValueError, match="2-D"):
        embeddings.embed_matrix(["x"], encoder=BadEncoder())


def test_embed_texts_returns_immutable_vectors() -> None:
    vectors = embeddings.embed_texts(["a", "b"], encoder=FakeEncoder(dim=4))
    assert isinstance(vectors, tuple)
    assert all(isinstance(v, tuple) for v in vectors)
    assert len(vectors) == 2


def test_embed_texts_is_deterministic() -> None:
    fake = FakeEncoder(dim=4)
    assert embeddings.embed_texts(["clause"], encoder=fake) == embeddings.embed_texts(
        ["clause"], encoder=fake
    )


def test_embed_chunks_pairs_vector_with_chunk() -> None:
    chunks = (_chunk(0, "alpha"), _chunk(1, "beta"))
    embedded = embeddings.embed_chunks(chunks, encoder=FakeEncoder(dim=4))
    assert len(embedded) == 2
    assert embedded[0].chunk is chunks[0]
    assert len(embedded[0].vector) == 4


def test_embedded_chunk_is_frozen() -> None:
    embedded = embeddings.EmbeddedChunk(chunk=_chunk(0, "x"), vector=(1.0, 0.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        embedded.vector = (0.0, 1.0)  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# build_index — row-aligned, idempotent persistence
# --------------------------------------------------------------------------- #
def test_build_index_writes_aligned_artifacts(tmp_path) -> None:
    chunks = (_chunk(0, "first chunk"), _chunk(1, "second chunk"), _chunk(2, "third"))
    chunks_path = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(chunks_path, chunks)

    out_dir = tmp_path / "index"
    embeddings.build_index(chunks_path, out_dir=out_dir, encoder=FakeEncoder(dim=4))

    matrix = np.load(out_dir / embeddings._EMBEDDINGS_FILE)[embeddings._MATRIX_KEY]
    index_lines = (out_dir / embeddings._INDEX_FILE).read_text(encoding="utf-8").splitlines()
    assert matrix.shape == (3, 4)
    assert len(index_lines) == 3
    # Row i ↔ chunk i.
    assert json.loads(index_lines[0])["chunk_id"] == "doc::0"


def test_build_index_is_idempotent(tmp_path) -> None:
    chunks = (_chunk(0, "alpha text"), _chunk(1, "beta text"))
    chunks_path = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(chunks_path, chunks)
    out_dir = tmp_path / "index"

    embeddings.build_index(chunks_path, out_dir=out_dir, encoder=FakeEncoder(dim=4))
    first = np.load(out_dir / embeddings._EMBEDDINGS_FILE)[embeddings._MATRIX_KEY]
    embeddings.build_index(chunks_path, out_dir=out_dir, encoder=FakeEncoder(dim=4))
    second = np.load(out_dir / embeddings._EMBEDDINGS_FILE)[embeddings._MATRIX_KEY]
    assert np.allclose(first, second)


def test_build_index_rejects_empty_corpus(tmp_path) -> None:
    chunks_path = tmp_path / "empty.jsonl"
    chunks_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no chunks"):
        embeddings.build_index(chunks_path, out_dir=tmp_path / "i", encoder=FakeEncoder())


# --------------------------------------------------------------------------- #
# Integration: the real model. Off by default.
# --------------------------------------------------------------------------- #
_integration = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="loads the real ~90 MB model; set RUN_INTEGRATION=1 to run",
)


@_integration
def test_real_model_shape_and_norm() -> None:
    matrix = embeddings.embed_matrix(["a short clause", "another clause"])
    assert matrix.shape == (2, embeddings.EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-4)


@_integration
def test_real_model_meaning_beats_keyword() -> None:
    [protection, privacy, steel] = embeddings.embed_matrix(
        ["data protection", "personal data privacy", "thermal expansion of steel"]
    )
    assert float(protection @ privacy) > float(protection @ steel)


@_integration
def test_real_model_is_deterministic() -> None:
    a = embeddings.embed_matrix(["accountability"])
    b = embeddings.embed_matrix(["accountability"])
    assert np.allclose(a, b)
