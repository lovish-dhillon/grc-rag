"""Hybrid retrieval — fuse dense (meaning) and BM25 (words) into one ranking.

Dense and lexical retrieval fail in different places: the embedder misses exact tokens
(clause numbers, rare terms), BM25 misses paraphrase (same meaning, no shared words). Running
both and combining them recalls a clause by *either* route. The combining step is the
interesting choice.

We fuse by **reciprocal-rank fusion (RRF)**, not by averaging scores. The two retrievers score
on incomparable scales — dense cosine ∈ [-1, 1], BM25 an unbounded TF-IDF sum — so averaging
them would need a normalisation we'd have to calibrate and defend, and that silently re-weights
whenever the score distribution shifts. RRF throws the magnitudes away and keeps only *rank
position*: a chunk's fused score is ``Σ 1 / (k_rrf + rank)`` over the lists it appears in. Rank
1 is worth the same in either retriever, no calibration, nothing to tune but the single
constant ``k_rrf`` (literature default 60; larger ``k_rrf`` flattens the contribution of the
very top ranks). Distribution-free and fully explainable.

The fusion core (:func:`reciprocal_rank_fusion`) operates on ranked ``chunk_id`` lists, so it
is pure and testable without any model. :class:`HybridRetriever` wires the two real retrievers
into it and is a **drop-in** for the ``Retriever`` Protocol — note that the ``RetrievedChunk``
it returns carries the *RRF score* in ``.score``, not a cosine (see :class:`FusedResult` for
the per-retriever provenance behind that score).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from grc_rag.bm25 import BM25Index
from grc_rag.chunking import Chunk
from grc_rag.embeddings import _INDEX_FILE, Encoder
from grc_rag.retrieve import DenseRetriever, RetrievedChunk

# The RRF damping constant. 60 is the value from the original RRF paper (Cormack et al., 2009);
# it keeps any single rank-1 hit from dominating the fused score. A logged, defensible default.
_DEFAULT_K_RRF = 60


@dataclass(frozen=True)
class FusedResult:
    """One fused result, with the provenance that explains *why* it surfaced.

    ``dense_rank`` / ``bm25_rank`` are the chunk's 1-based positions in each retriever's
    candidate list, or ``None`` if that retriever didn't return it. Reading them tells you
    whether a chunk rose on meaning, on words, or on both.
    """

    chunk_id: str
    rrf_score: float
    dense_rank: int | None
    bm25_rank: int | None


def reciprocal_rank_fusion(
    ranked_id_lists: Sequence[Sequence[str]], *, k_rrf: int = _DEFAULT_K_RRF
) -> tuple[FusedResult, ...]:
    """Fuse ranked ``chunk_id`` lists by RRF, highest fused score first.

    ``score(id) = Σ_lists 1 / (k_rrf + rank)`` with ``rank`` 1-based over each list the id
    appears in. The input is ``[dense_ids, bm25_ids]`` — index 0 fills ``dense_rank``, index 1
    ``bm25_rank`` on each :class:`FusedResult` (the RRF sum itself generalises to any number of
    lists; only the two-retriever provenance is recorded). Ties break deterministically by
    ``chunk_id``. Pure. Raises ``ValueError`` on ``k_rrf <= 0``.
    """
    if k_rrf <= 0:
        raise ValueError(f"k_rrf must be > 0, got {k_rrf}")

    # id -> 1-based rank, per list.
    rank_maps = [{cid: pos + 1 for pos, cid in enumerate(ids)} for ids in ranked_id_lists]
    dense_ranks = rank_maps[0] if len(rank_maps) >= 1 else {}
    bm25_ranks = rank_maps[1] if len(rank_maps) >= 2 else {}

    # Union of ids in first-seen order (only affects pre-sort traversal, not the final order).
    seen: set[str] = set()
    union: list[str] = []
    for ids in ranked_id_lists:
        for cid in ids:
            if cid not in seen:
                seen.add(cid)
                union.append(cid)

    results = [
        FusedResult(
            chunk_id=cid,
            rrf_score=sum(1.0 / (k_rrf + rmap[cid]) for rmap in rank_maps if cid in rmap),
            dense_rank=dense_ranks.get(cid),
            bm25_rank=bm25_ranks.get(cid),
        )
        for cid in union
    ]
    results.sort(key=lambda f: (-f.rrf_score, f.chunk_id))
    return tuple(results)


class _DenseLike:
    """Structural type for the dense arm: anything with ``retrieve(query, *, k)``."""

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


class HybridRetriever:
    """Dense + BM25, fused by RRF — a drop-in for the ``Retriever`` Protocol.

    Fetches ``candidate_k`` from each arm, fuses by RRF, and returns the top-k as
    ``RetrievedChunk`` whose ``.score`` is the RRF score, so :func:`grc_rag.pipeline.
    answer_question` composes it unchanged.
    """

    def __init__(
        self,
        dense: _DenseLike,
        bm25: BM25Index,
        *,
        candidate_k: int = 50,
        k_rrf: int = _DEFAULT_K_RRF,
    ) -> None:
        if candidate_k <= 0:
            raise ValueError(f"candidate_k must be > 0, got {candidate_k}")
        if k_rrf <= 0:
            raise ValueError(f"k_rrf must be > 0, got {k_rrf}")
        self._dense = dense
        self._bm25 = bm25
        self._candidate_k = candidate_k
        self._k_rrf = k_rrf

    @classmethod
    def from_index(
        cls,
        index_dir: Path,
        *,
        candidate_k: int = 50,
        k_rrf: int = _DEFAULT_K_RRF,
        encoder: Encoder | None = None,
    ) -> HybridRetriever:
        """Wire both arms from a built index dir. BM25 indexes the dense index's own
        ``index.jsonl`` so the two halves see the identical chunk set. The dense query
        ``encoder`` is injectable so tests can avoid loading the real model."""
        dense = DenseRetriever.from_index(index_dir, encoder=encoder)
        bm25 = BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE)
        return cls(dense, bm25, candidate_k=candidate_k, k_rrf=k_rrf)

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        """Return the top-``k`` chunks by fused RRF score. Raises on blank query / ``k <= 0``."""
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if k <= 0:
            raise ValueError(f"k must be > 0, got {k}")

        dense_hits = self._dense.retrieve(query, k=self._candidate_k)
        bm25_hits = self._bm25.search(query, k=self._candidate_k)

        # Either arm carries the full Chunk for an id (same corpus), so a union map resolves
        # every fused id back to a citable chunk.
        id_to_chunk: dict[str, Chunk] = {}
        for hit in (*dense_hits, *bm25_hits):
            id_to_chunk.setdefault(hit.chunk.chunk_id, hit.chunk)

        dense_ids = [hit.chunk.chunk_id for hit in dense_hits]
        bm25_ids = [hit.chunk.chunk_id for hit in bm25_hits]
        fused = reciprocal_rank_fusion([dense_ids, bm25_ids], k_rrf=self._k_rrf)

        return tuple(
            RetrievedChunk(chunk=id_to_chunk[result.chunk_id], score=result.rrf_score)
            for result in fused[:k]
        )
