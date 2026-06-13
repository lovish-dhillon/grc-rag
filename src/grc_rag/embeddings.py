"""Embeddings — turn chunk text into vectors where *meaning* is proximity.

Keyword search can only find text that shares words with the query. Ask "who is
accountable when a model harms someone?" and a lexical index misses the Article
that says "providers shall ensure…" — same meaning, no shared words. An
**embedding** maps a piece of text to a point in a high-dimensional space (here,
384 dimensions) such that texts with similar *meaning* land near each other, even
with no vocabulary overlap. Retrieval then becomes "find the nearest points to the
query's point."

This module also avoids a common shortcut: faking embeddings with a **hashing trick**
(which captures spelling, not meaning). Here the vectors come from a real
sentence-transformer, so nearness reflects semantics rather than surface form.

Two design choices worth noting:

* **Unit-normalise every vector ourselves** (not via a model flag). Once every
  vector has length 1, cosine similarity — the angle between two meanings — is just
  their dot product. That makes retrieval a single matrix-vector multiply and keeps
  the normalisation explicit and testable in *our* code, not hidden in a library.
* **The model loads lazily.** Importing this module must stay cheap (it should not
  drag in torch); the ~90 MB model is fetched and cached only on first real use, and
  tests inject a tiny fake encoder instead.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from grc_rag.chunking import Chunk
from grc_rag.ingest import load_chunks_jsonl

# all-MiniLM-L6-v2: 384-dim, ~90 MB, runs locally on CPU, no API key, no cost.
# A strong, widely-used baseline — accuracy is "good enough to learn on"; the
# precision upgrade is the Phase-2 cross-encoder re-rank, not a bigger bi-encoder.
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_EMBEDDINGS_FILE = "embeddings.npz"
_INDEX_FILE = "index.jsonl"
_MATRIX_KEY = "embeddings"


class Encoder(Protocol):
    """The single seam to the embedding model.

    Anything with this ``encode`` shape works — the real
    :class:`sentence_transformers.SentenceTransformer`, or a tiny fake in tests.
    """

    def encode(self, texts: list[str], **kwargs: object) -> np.ndarray: ...


@dataclass(frozen=True)
class EmbeddedChunk:
    """A chunk paired with its dense representation. Immutable."""

    chunk: Chunk
    vector: tuple[float, ...]


@lru_cache(maxsize=1)
def _get_model() -> Encoder:
    """Load (and cache) the real sentence-transformer. Imported lazily so that
    merely importing this module doesn't pull in torch."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length. A zero row is left as zero (no div-by-zero)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def embed_matrix(texts: Sequence[str], *, encoder: Encoder | None = None) -> np.ndarray:
    """Encode ``texts`` into a unit-normalised float32 matrix of shape (n, dim).

    The matrix form is what the vector store and retrieval use directly. An empty
    input yields an empty (0, dim) matrix.
    """
    if len(texts) == 0:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    encoder = encoder or _get_model()
    raw = np.asarray(encoder.encode(list(texts), convert_to_numpy=True), dtype=np.float32)
    if raw.ndim != 2:
        raise ValueError(f"encoder must return a 2-D matrix, got shape {raw.shape}")
    return _normalise_rows(raw)


def embed_texts(
    texts: Sequence[str], *, encoder: Encoder | None = None
) -> tuple[tuple[float, ...], ...]:
    """Encode ``texts`` into immutable unit-normalised vectors."""
    matrix = embed_matrix(texts, encoder=encoder)
    return tuple(tuple(float(x) for x in row) for row in matrix)


def embed_chunks(
    chunks: Sequence[Chunk], *, encoder: Encoder | None = None
) -> tuple[EmbeddedChunk, ...]:
    """Embed each chunk's text, pairing the vector with its source chunk."""
    vectors = embed_texts([c.text for c in chunks], encoder=encoder)
    return tuple(
        EmbeddedChunk(chunk=chunk, vector=vector) for chunk, vector in zip(chunks, vectors)
    )


def build_index(chunks_path: Path, *, out_dir: Path, encoder: Encoder | None = None) -> None:
    """Embed every chunk in ``chunks_path`` and persist the vector store.

    Writes two row-aligned artifacts to ``out_dir``: ``embeddings.npz`` (the float32
    matrix, row ``i`` = chunk ``i``) and ``index.jsonl`` (the chunks, same order, so
    a matrix row maps straight back to a citable chunk). Idempotent: the model is
    deterministic, so re-running reproduces the same matrix.
    """
    chunks = load_chunks_jsonl(chunks_path)
    if len(chunks) == 0:
        raise ValueError(f"no chunks to index in {chunks_path}")

    matrix = embed_matrix([c.text for c in chunks], encoder=encoder)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(out_dir / _EMBEDDINGS_FILE, **{_MATRIX_KEY: matrix})
    with (out_dir / _INDEX_FILE).open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
