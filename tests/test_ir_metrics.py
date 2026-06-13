"""Tests for the pure IR metrics. Deterministic, model-free — hand-computed expected values."""

from __future__ import annotations

import math

import pytest

from grc_rag.chunking import Chunk
from grc_rag.golden import GoldenItem
from grc_rag.ir_metrics import (
    evaluate_retrieval,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from grc_rag.retrieve import RetrievedChunk

_ITEM = GoldenItem(
    id="g1",
    question="Which AI practices are prohibited?",
    kind="in_corpus",
    expected_doc="eu-ai-act",
    expected_clause_labels=("EU AI Act — Article 5",),
)


def _ranked(labels: list[str | None]) -> tuple[RetrievedChunk, ...]:
    """A ranking where position i carries clause_label labels[i] (None = irrelevant chunk)."""
    out = []
    for i, label in enumerate(labels):
        chunk = Chunk(
            chunk_id=f"eu-ai-act::{i}",
            doc_id="eu-ai-act",
            text="...",
            token_count=1,
            start_token=0,
            clause_label=label,
        )
        out.append(RetrievedChunk(chunk=chunk, score=float(len(labels) - i)))
    return tuple(out)


# --------------------------------------------------------------------------- #
# recall@k
# --------------------------------------------------------------------------- #
def test_recall_hit_in_top_k() -> None:
    ranked = _ranked([None, "EU AI Act — Article 5", None])
    assert recall_at_k(ranked, _ITEM, k=3) == 1.0


def test_recall_miss() -> None:
    ranked = _ranked([None, None, "EU AI Act — Article 99"])
    assert recall_at_k(ranked, _ITEM, k=3) == 0.0


def test_recall_boundary_exactly_k() -> None:
    # relevant is at rank 2; k=2 includes it, k=1 does not.
    ranked = _ranked([None, "EU AI Act — Article 5", None])
    assert recall_at_k(ranked, _ITEM, k=2) == 1.0
    assert recall_at_k(ranked, _ITEM, k=1) == 0.0


def test_recall_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        recall_at_k(_ranked(["EU AI Act — Article 5"]), _ITEM, k=0)


# --------------------------------------------------------------------------- #
# reciprocal rank
# --------------------------------------------------------------------------- #
def test_rr_rank_one() -> None:
    assert reciprocal_rank(_ranked(["EU AI Act — Article 5"]), _ITEM) == 1.0


def test_rr_rank_three() -> None:
    ranked = _ranked([None, None, "EU AI Act — Article 5"])
    assert reciprocal_rank(ranked, _ITEM) == pytest.approx(1 / 3)


def test_rr_none() -> None:
    assert reciprocal_rank(_ranked([None, None]), _ITEM) == 0.0


# --------------------------------------------------------------------------- #
# nDCG@k
# --------------------------------------------------------------------------- #
def test_ndcg_ideal_ordering() -> None:
    assert ndcg_at_k(_ranked(["EU AI Act — Article 5", None, None]), _ITEM, k=3) == 1.0


def test_ndcg_relevant_at_rank_two() -> None:
    # one relevant chunk at rank 2: DCG = 1/log2(3); IDCG = 1/log2(2) = 1 → ndcg = 1/log2(3).
    ranked = _ranked([None, "EU AI Act — Article 5", None])
    assert ndcg_at_k(ranked, _ITEM, k=3) == pytest.approx(1 / math.log2(3))


def test_ndcg_no_relevant_is_zero() -> None:
    assert ndcg_at_k(_ranked([None, None]), _ITEM, k=2) == 0.0


def test_ndcg_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        ndcg_at_k(_ranked(["EU AI Act — Article 5"]), _ITEM, k=-1)


# --------------------------------------------------------------------------- #
# evaluate_retrieval
# --------------------------------------------------------------------------- #
class _StubRetriever:
    """Returns, for any query, a ranking with the relevant clause at a chosen rank."""

    def __init__(self, labels: list[str | None]) -> None:
        self._labels = labels

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        return _ranked(self._labels)[:k]


def test_evaluate_retrieval_means() -> None:
    items = (
        _ITEM,
        GoldenItem(
            id="g2",
            question="another?",
            kind="in_corpus",
            expected_doc="eu-ai-act",
            expected_clause_labels=("EU AI Act — Article 5",),
        ),
        GoldenItem(
            id="g-out",
            question="off corpus?",
            kind="out_of_corpus",
            expected_doc=None,
            expected_clause_labels=(),
        ),
    )
    # relevant at rank 1 for every in-corpus query → all metrics 1.0; out-of-corpus excluded.
    report = evaluate_retrieval(items, _StubRetriever(["EU AI Act — Article 5", None]), k=10)
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0
    assert report.ndcg_at_k == 1.0
    assert report.n_items == 2  # the out-of-corpus item was excluded
    assert report.k == 10


def test_evaluate_retrieval_requires_in_corpus_items() -> None:
    out_only = (
        GoldenItem(
            id="g-out",
            question="off?",
            kind="out_of_corpus",
            expected_doc=None,
            expected_clause_labels=(),
        ),
    )
    with pytest.raises(ValueError, match="no in_corpus"):
        evaluate_retrieval(out_only, _StubRetriever([None]), k=10)
