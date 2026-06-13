"""Tests for the cross-encoder re-rank stage.

A cross-encoder is heavy (~80 MB) and slow, so every unit test injects a deterministic
**stub** ``CrossEncoder`` that scores by a text→score map we control. That lets us prove the
re-ordering, the top_k truncation, the (query, chunk) pair construction, and the drop-in
wiring — all offline. The real-model precision lift is a single integration test, gated.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Sequence

import pytest

from conftest import StubLLMClient
from grc_rag.chunking import Chunk
from grc_rag.pipeline import answer_question
from grc_rag.rerank import CrossEncoderReranker, RerankedChunk, RerankingRetriever
from grc_rag.retrieve import RetrievedChunk


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id=chunk_id.split("::")[0], text=text, token_count=1, start_token=0
    )


def _candidate(chunk_id: str, text: str, score: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(chunk=_chunk(chunk_id, text), score=score)


class StubCrossEncoder:
    """A canned cross-encoder: scores each (query, text) pair from a text→score map.

    Records the exact pairs it was asked to score, so tests can assert pair construction.
    """

    def __init__(self, scores_by_text: dict[str, float]) -> None:
        self._scores = scores_by_text
        self.received_pairs: list[tuple[str, str]] | None = None

    def predict(self, pairs: list[tuple[str, str]]) -> Sequence[float]:
        self.received_pairs = list(pairs)
        return [self._scores.get(text, 0.0) for _query, text in pairs]


# --------------------------------------------------------------------------- #
# rerank — re-ordering and provenance
# --------------------------------------------------------------------------- #
def test_rerank_reorders_by_cross_encoder_score() -> None:
    # Input order A, B, C; the stub scores the LAST candidate highest → it must move to front.
    candidates = (
        _candidate("d::0", "alpha"),
        _candidate("d::1", "beta"),
        _candidate("d::2", "gamma"),
    )
    model = StubCrossEncoder({"alpha": 0.1, "beta": 0.2, "gamma": 0.9})
    reranked = CrossEncoderReranker(model=model).rerank("q", candidates, top_k=3)

    assert [r.chunk.chunk_id for r in reranked] == ["d::2", "d::1", "d::0"]
    assert [r.score for r in reranked] == [0.9, 0.2, 0.1]
    # prior_rank records where each chunk sat BEFORE re-ranking (1-based).
    assert {r.chunk.chunk_id: r.prior_rank for r in reranked} == {"d::0": 1, "d::1": 2, "d::2": 3}


def test_rerank_truncates_to_top_k() -> None:
    candidates = tuple(_candidate(f"d::{i}", f"text {i}") for i in range(5))
    model = StubCrossEncoder({f"text {i}": float(i) for i in range(5)})  # text 4 highest
    reranked = CrossEncoderReranker(model=model).rerank("q", candidates, top_k=2)

    assert len(reranked) == 2
    assert [r.chunk.chunk_id for r in reranked] == ["d::4", "d::3"]


def test_rerank_builds_one_pair_per_candidate() -> None:
    candidates = (_candidate("d::0", "alpha text"), _candidate("d::1", "beta text"))
    model = StubCrossEncoder({})
    CrossEncoderReranker(model=model).rerank("my query", candidates, top_k=2)

    assert model.received_pairs == [("my query", "alpha text"), ("my query", "beta text")]


def test_reranked_chunk_is_frozen() -> None:
    result = RerankedChunk(chunk=_chunk("d::0", "x"), score=0.5, prior_rank=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 0.9  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Fail-fast
# --------------------------------------------------------------------------- #
def test_rerank_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        CrossEncoderReranker(model=StubCrossEncoder({})).rerank("  ", (_candidate("d::0", "x"),))


def test_rerank_rejects_non_positive_top_k() -> None:
    with pytest.raises(ValueError, match="top_k must be"):
        CrossEncoderReranker(model=StubCrossEncoder({})).rerank(
            "q", (_candidate("d::0", "x"),), top_k=0
        )


def test_rerank_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="empty"):
        CrossEncoderReranker(model=StubCrossEncoder({})).rerank("q", ())


# --------------------------------------------------------------------------- #
# RerankingRetriever — drop-in for the Retriever Protocol
# --------------------------------------------------------------------------- #
class _StubBase:
    """A base retriever (stands in for the hybrid) returning fixed candidates."""

    def __init__(self, candidates: tuple[RetrievedChunk, ...]) -> None:
        self._candidates = candidates
        self.last_k: int | None = None

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        self.last_k = k
        return self._candidates[:k]


def test_reranking_retriever_pulls_candidate_k_and_reranks() -> None:
    base = _StubBase(tuple(_candidate(f"d::{i}", f"text {i}") for i in range(10)))
    model = StubCrossEncoder({"text 7": 9.0})  # an otherwise-mid candidate scored highest
    retriever = RerankingRetriever(base, CrossEncoderReranker(model=model), candidate_k=8, top_k=3)

    results = retriever.retrieve("q", k=3)
    assert base.last_k == 8  # pulled candidate_k from the base, not k
    assert isinstance(results[0], RetrievedChunk)
    assert results[0].chunk.chunk_id == "d::7"  # cross-encoder winner first
    assert len(results) == 3


def test_reranking_retriever_is_drop_in_for_answer_question() -> None:
    base = _StubBase((_candidate("eu-ai-act::4", "Providers shall ensure compliance."),))
    model = StubCrossEncoder({"Providers shall ensure compliance.": 5.0})
    retriever = RerankingRetriever(base, CrossEncoderReranker(model=model))
    client = StubLLMClient("Providers shall ensure compliance [eu-ai-act::4].")

    answer = answer_question("What must providers do?", retriever=retriever, client=client, k=6)
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::4",)


def test_reranking_retriever_empty_base_returns_empty() -> None:
    retriever = RerankingRetriever(_StubBase(()), CrossEncoderReranker(model=StubCrossEncoder({})))
    assert retriever.retrieve("q", k=5) == ()


def test_reranking_retriever_fail_fast() -> None:
    base = _StubBase((_candidate("d::0", "x"),))
    reranker = CrossEncoderReranker(model=StubCrossEncoder({}))
    with pytest.raises(ValueError, match="non-empty"):
        RerankingRetriever(base, reranker).retrieve("  ")
    with pytest.raises(ValueError, match="k must be"):
        RerankingRetriever(base, reranker).retrieve("q", k=0)
    with pytest.raises(ValueError, match="candidate_k"):
        RerankingRetriever(base, reranker, candidate_k=0)
    with pytest.raises(ValueError, match="top_k"):
        RerankingRetriever(base, reranker, top_k=0)


# --------------------------------------------------------------------------- #
# Integration: real cross-encoder lifts precision on the probe set. Off by default.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the real cross-encoder + a built index; set RUN_INTEGRATION=1 to run",
)
def test_rerank_lifts_expected_chunk_rank_on_probe_set() -> None:
    from pathlib import Path

    from grc_rag.bm25 import BM25Index
    from grc_rag.embeddings import _INDEX_FILE
    from grc_rag.hybrid import HybridRetriever
    from grc_rag.retrieve import DenseRetriever

    index_dir = Path("data/processed")
    hybrid = HybridRetriever(
        DenseRetriever.from_index(index_dir),
        BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE),
    )
    reranking = RerankingRetriever(hybrid, CrossEncoderReranker(), candidate_k=50, top_k=6)

    q = "Which AI practices are prohibited?"

    def rank_of(results: tuple[RetrievedChunk, ...]) -> int | None:
        for i, r in enumerate(results, 1):
            if r.chunk.doc_id == "eu-ai-act" and "prohibited" in r.chunk.text.lower():
                return i
        return None

    before = rank_of(hybrid.retrieve(q, k=6))
    after = rank_of(reranking.retrieve(q, k=6))
    print(f"\nArt.5 'prohibited' rank — hybrid={before}  reranked={after}")
    assert after is not None and (before is None or after <= before)
