"""Cross-encoder re-rank — a precise second pass over the cheap first stage.

The dense retriever is a **bi-encoder**: it embeds the query and each chunk *separately* into
fixed vectors and compares them. That separation is what makes it fast (every chunk vector is
precomputed once), but it also means the model never sees a query and a chunk *together* — it
can't judge fine-grained relevance, only topical proximity. A **cross-encoder** feeds the
``(query, chunk)`` pair through the model jointly and outputs a single relevance score. Much
more precise, but with nothing to precompute — it's a full forward pass per pair, far too slow
to run over the whole corpus.

So the production shape is two stages: a cheap, recall-oriented first stage (the hybrid
retriever) proposes a ``candidate_k`` shortlist, and the expensive, precision-oriented
cross-encoder re-scores just those candidates. The result is a tighter, better-ordered top-k —
which is exactly the lever on cite-or-refuse quality, because it's what the generator sees.

The model sits behind a one-method :class:`CrossEncoder` seam (mirroring :class:`grc_rag.
embeddings.Encoder` and :class:`grc_rag.generate.LLMClient`): the real ~80 MB model loads
lazily, and tests inject a deterministic stub so nothing heavy runs offline.
:class:`CrossEncoderReranker` returns rich :class:`RerankedChunk`s (carrying the score *and*
the prior rank, so the re-ordering is inspectable); :class:`RerankingRetriever` projects them
back to ``RetrievedChunk`` and is a drop-in for the ``Retriever`` Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, Sequence

from grc_rag.chunking import Chunk
from grc_rag.retrieve import RetrievedChunk

# The standard small re-ranking cross-encoder: trained on MS MARCO passage ranking, ~80 MB,
# CPU-fast enough to score ~50 candidates in well under a second, no key, no cost. The
# precision upgrade the bi-encoder defers to (see embeddings.py). A logged, defensible default.
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoder(Protocol):
    """The single seam to the cross-encoder. The real ``sentence_transformers.CrossEncoder``
    satisfies this shape; tests inject a tiny fake so unit tests never load the model."""

    def predict(self, pairs: list[tuple[str, str]]) -> Sequence[float]: ...


class _BaseRetriever(Protocol):
    """The first-stage retriever this one wraps — anything with ``retrieve(query, *, k)``."""

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


@dataclass(frozen=True)
class RerankedChunk:
    """A candidate after cross-encoder scoring, with the provenance of its move.

    ``score`` is the cross-encoder relevance score — an unbounded value on its own scale
    (higher = more relevant; not a probability, not comparable to a cosine). ``prior_rank`` is
    the chunk's 1-based position in the candidate list, so you can see how far it moved.
    """

    chunk: Chunk
    score: float
    prior_rank: int


@lru_cache(maxsize=1)
def _get_model() -> CrossEncoder:
    """Load (and cache) the real cross-encoder. Imported lazily so merely importing this
    module doesn't pull in torch; tests inject a stub and never reach here."""
    from sentence_transformers import CrossEncoder as SentenceTransformersCrossEncoder

    return SentenceTransformersCrossEncoder(_MODEL_NAME)


class CrossEncoderReranker:
    """Re-scores ``(query, chunk)`` pairs jointly and returns the top-k, highest score first."""

    def __init__(self, *, model: CrossEncoder | None = None) -> None:
        self._model = model

    def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk], *, top_k: int = 6
    ) -> tuple[RerankedChunk, ...]:
        """Score every ``(query, candidate.text)`` pair, sort by score desc, return the top_k.

        Pure given the model. Raises ``ValueError`` on a blank query, ``top_k <= 0``, or an
        empty candidate set (nothing to re-rank is a caller error, not a silent empty result).
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {top_k}")
        if not candidates:
            raise ValueError("cannot rerank an empty candidate set")

        model = self._model or _get_model()
        scores = model.predict([(query, rc.chunk.text) for rc in candidates])
        reranked = [
            RerankedChunk(chunk=rc.chunk, score=float(score), prior_rank=position)
            for position, (rc, score) in enumerate(zip(candidates, scores), start=1)
        ]
        # Stable sort by score desc: ties keep candidate (recall) order — a sensible tiebreak.
        reranked.sort(key=lambda r: -r.score)
        return tuple(reranked[:top_k])


class RerankingRetriever:
    """base (hybrid) → pull ``candidate_k`` → cross-encoder rerank → top-k.

    A drop-in for the ``Retriever`` Protocol: returns ``RetrievedChunk`` whose ``.score`` is the
    cross-encoder score (the same score-scale broadening noted in :mod:`grc_rag.hybrid`), so
    :func:`grc_rag.pipeline.answer_question` composes it unchanged.
    """

    def __init__(
        self,
        base: _BaseRetriever,
        reranker: CrossEncoderReranker,
        *,
        candidate_k: int = 50,
        top_k: int = 6,
    ) -> None:
        if candidate_k <= 0:
            raise ValueError(f"candidate_k must be > 0, got {candidate_k}")
        if top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {top_k}")
        self._base = base
        self._reranker = reranker
        self._candidate_k = candidate_k
        self._top_k = top_k

    def retrieve(self, query: str, *, k: int | None = None) -> tuple[RetrievedChunk, ...]:
        """Return the top-``k`` chunks after re-ranking the base's ``candidate_k`` shortlist.

        ``k`` defaults to the constructor's ``top_k`` and overrides it when given. Raises
        ``ValueError`` on a blank query or ``k <= 0``.
        """
        k = self._top_k if k is None else k
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if k <= 0:
            raise ValueError(f"k must be > 0, got {k}")

        candidates = self._base.retrieve(query, k=self._candidate_k)
        if not candidates:
            return ()
        reranked = self._reranker.rerank(query, candidates, top_k=k)
        return tuple(RetrievedChunk(chunk=r.chunk, score=r.score) for r in reranked)
