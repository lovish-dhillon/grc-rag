"""Information-retrieval metrics — did retrieval find the right clauses?

These answer the *first* of the two questions a real eval asks (the second — is the generated
answer faithful? — is the LLM-judge in :mod:`grc_rag.judge`). They are deliberately
**deterministic and model-free**: given a ranked list of retrieved chunks and a golden item's
verified relevant clauses, the score is fixed arithmetic — no cost, no API key, no run-to-run
flap. That is exactly why they, not the judge, run on every CI push.

Every metric joins a ranked :class:`~grc_rag.retrieve.RetrievedChunk` to a
:class:`~grc_rag.golden.GoldenItem` through :func:`~grc_rag.golden.is_relevant` (clause-label
match, doc-guarded). A position is a "hit" iff its chunk is relevant.

The three are built from the textbook formulae by hand — no ``sklearn``, no ``pytrec_eval`` —
so the metric definitions stay explicit and inspectable:

* **recall@k** — did *any* relevant clause make the top-k? (binary per item: 1.0 / 0.0). The
  headline gate is recall@10: for a single-relevant-clause question this is "was the answer
  retrievable at all", which is what cite-or-refuse needs.
* **MRR** — reciprocal of the rank of the *first* relevant chunk (1/1, 1/2, …); rewards
  putting a relevant clause high, which is what the generator's small k actually sees.
* **nDCG@k** — discounted cumulative gain (binary relevance) normalised by the ideal ordering;
  rewards relevant chunks appearing earlier, on a 0–1 scale comparable across questions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from grc_rag.golden import GoldenItem, is_relevant
from grc_rag.retrieve import RetrievedChunk


def _relevances(ranked: Sequence[RetrievedChunk], item: GoldenItem) -> list[bool]:
    """The hit/miss vector for a ranking, in rank order. Pure."""
    return [is_relevant(rc.chunk, item) for rc in ranked]


def recall_at_k(ranked: Sequence[RetrievedChunk], item: GoldenItem, *, k: int) -> float:
    """1.0 if any of the top-``k`` retrieved chunks is relevant to ``item``, else 0.0.

    Binary per item (the suite recall@k is the mean over items). Raises ``ValueError`` on
    ``k <= 0``. Pure.
    """
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")
    return 1.0 if any(_relevances(ranked, item)[:k]) else 0.0


def reciprocal_rank(ranked: Sequence[RetrievedChunk], item: GoldenItem) -> float:
    """``1 / rank`` of the first relevant chunk (rank is 1-based); 0.0 if none is relevant. Pure."""
    for position, hit in enumerate(_relevances(ranked, item), start=1):
        if hit:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: Sequence[RetrievedChunk], item: GoldenItem, *, k: int) -> float:
    """Binary-relevance nDCG over the top-``k``.

    ``DCG = Σ rel_i / log2(i + 1)`` (i 1-based), normalised by the ideal DCG — the same gains
    sorted to the front. 0.0 when no relevant chunk is in the top-k (IDCG would be 0 too, so we
    return 0.0 by definition rather than dividing). Raises ``ValueError`` on ``k <= 0``. Pure.
    """
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")
    gains = [1.0 if hit else 0.0 for hit in _relevances(ranked, item)[:k]]
    dcg = sum(gain / math.log2(position + 1) for position, gain in enumerate(gains, start=1))
    ideal_gains = sorted(gains, reverse=True)
    idcg = sum(gain / math.log2(position + 1) for position, gain in enumerate(ideal_gains, start=1))
    return dcg / idcg if idcg > 0 else 0.0


@dataclass(frozen=True)
class IRReport:
    """Aggregate IR metrics over the in-corpus golden items. Immutable."""

    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    k: int
    n_items: int


class _Retriever:  # documentation alias only; structural typing is what matters
    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


def evaluate_retrieval(
    items: Sequence[GoldenItem],
    retriever: _Retriever,
    *,
    k: int = 10,
) -> IRReport:
    """Mean recall@k, MRR, and nDCG@k over the **in-corpus** items.

    Out-of-corpus items have no relevant clause and are excluded (they are scored by refusal
    correctness in the harness, not by IR). Retrieves ``k`` chunks per question. Raises
    ``ValueError`` if there are no in-corpus items to score. Pure given the retriever.
    """
    in_corpus = [item for item in items if item.kind == "in_corpus"]
    if not in_corpus:
        raise ValueError("no in_corpus golden items to evaluate retrieval over")

    recalls: list[float] = []
    rrs: list[float] = []
    ndcgs: list[float] = []
    for item in in_corpus:
        ranked = retriever.retrieve(item.question, k=k)
        recalls.append(recall_at_k(ranked, item, k=k))
        rrs.append(reciprocal_rank(ranked, item))
        ndcgs.append(ndcg_at_k(ranked, item, k=k))

    n = len(in_corpus)
    return IRReport(
        recall_at_k=sum(recalls) / n,
        mrr=sum(rrs) / n,
        ndcg_at_k=sum(ndcgs) / n,
        k=k,
        n_items=n,
    )
