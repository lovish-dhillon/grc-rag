"""Dense retrieval — find the chunks whose *meaning* is nearest the query.

Given the persisted vector store (a unit-normalised matrix from
:mod:`grc_rag.embeddings`), retrieval is a single, exact computation: embed the
query into the same space, take the dot product against every chunk vector — which,
because everything is unit length, *is* the cosine similarity — and return the
top-k highest-scoring chunks.

For a corpus of a few thousand chunks this brute-force scan is exact and effectively
instant, with nothing to tune or trust. That's a deliberate Phase-1 choice over a
vector database (ChromaDB et al.): a real ANN index trades exactness for speed we
don't need yet, and adds approximate-nearest-neighbour behaviour we'd have to learn
and defend. We add it only if corpus size ever makes the scan slow. See
``03-decisions.md``.

Every chunk carries its provenance (``chunk_id``, ``doc_id``, ``start_token``), so a
:class:`RetrievedChunk` is directly citable — which is exactly what the cite-or-refuse
generation stage needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from grc_rag.chunking import Chunk
from grc_rag.embeddings import (
    _EMBEDDINGS_FILE,
    _INDEX_FILE,
    _MATRIX_KEY,
    Encoder,
    embed_matrix,
)
from grc_rag.ingest import load_chunks_jsonl


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by retrieval, paired with its relevance ``score``.

    ``score`` is the retriever's own relevance signal — higher is more relevant — but its
    *scale depends on the retriever*: cosine ∈ ``[-1, 1]`` for dense retrieval, a raw BM25
    score for lexical, an RRF score for the hybrid fusion (see :mod:`grc_rag.hybrid`). Compare
    scores only within one retriever's results, never across retrievers.
    """

    chunk: Chunk
    score: float


class DenseRetriever:
    """Holds the vector store in memory and answers top-k similarity queries.

    Construct from a persisted index with :meth:`from_index`, or directly with a
    matrix + chunks (useful in tests). The query encoder is injectable so tests can
    avoid loading the real model.
    """

    def __init__(
        self,
        matrix: np.ndarray,
        chunks: tuple[Chunk, ...],
        *,
        encoder: Encoder | None = None,
    ) -> None:
        # Fail fast on a corrupt store: an empty index can't answer anything, and a
        # row/chunk mismatch means a citation could point at the wrong clause.
        if matrix.shape[0] == 0 or len(chunks) == 0:
            raise ValueError("cannot build a retriever over an empty index")
        if matrix.shape[0] != len(chunks):
            raise ValueError(
                f"matrix/chunks misalignment: {matrix.shape[0]} vectors but "
                f"{len(chunks)} chunks — row i must map to chunk i"
            )
        self._matrix = matrix.astype(np.float32)
        self._chunks = chunks
        self._encoder = encoder

    @classmethod
    def from_index(cls, index_dir: Path, *, encoder: Encoder | None = None) -> DenseRetriever:
        """Load the persisted matrix + chunk index written by ``build_index``."""
        matrix = np.load(index_dir / _EMBEDDINGS_FILE)[_MATRIX_KEY]
        chunks = load_chunks_jsonl(index_dir / _INDEX_FILE)
        return cls(matrix, chunks, encoder=encoder)

    def __len__(self) -> int:
        return len(self._chunks)

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        """Return the ``k`` chunks most similar to ``query``, highest score first."""
        if k <= 0:
            raise ValueError(f"k must be > 0, got {k}")
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        query_vector = embed_matrix([query], encoder=self._encoder)[0]
        # Unit-normalised rows · unit query ⇒ each dot product is a cosine similarity.
        scores = self._matrix @ query_vector

        # Highest scores first; cap at the number of chunks we actually have.
        top_k = min(k, scores.shape[0])
        ranked = np.argsort(-scores)[:top_k]
        return tuple(
            RetrievedChunk(chunk=self._chunks[int(i)], score=float(scores[int(i)])) for i in ranked
        )
