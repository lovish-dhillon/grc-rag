"""Threshold-based refusal enforcement — refuse on weak support *before* trusting the LLM.

Phase 1 enforces cite-or-refuse **reactively**: it refuses only when the model volunteers the
refusal sentinel or cites nothing real. That trusts the model to notice thin grounding. But
hand it marginally-relevant chunks and it will often write a confident, *correctly-cited*
answer anyway — the citation resolves, the Phase-1 check passes, yet the support was weak.
That is exactly how false assurance leaks back into a GRC answer.

This module adds the missing **proactive** gate: read how strongly retrieval grounds the
question — the top-1 relevance score — and refuse on insufficient support regardless of what
the model would say. Cite-or-refuse stops being "the model behaved" and becomes "the system
measured the support and decided." It's a near-zero-cost structural proxy for the Phase-3
LLM-judge: it runs on every query with no extra model call (and, when support is weak, *saves*
the generation call entirely).

The load-bearing part is **calibration**. The top-1 score is an unbounded, retriever-specific
number (a cross-encoder logit when wired behind :class:`grc_rag.rerank.RerankingRetriever`), so
a guessed threshold is meaningless. :func:`calibrate_threshold` fits it from the probe set's
in-corpus vs out-of-corpus score populations, and **fails fast if they overlap** — an honest
"retrieval isn't discriminative enough to gate on yet" instead of a silently arbitrary cut.
The gate sits *around* the pipeline, never inside :mod:`grc_rag.generate`; it can only *add*
refusals, never remove one, so the Phase-1 guarantees still hold underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from grc_rag.generate import PROMPT_VERSION, REFUSAL, Answer, LLMClient, generate_answer
from grc_rag.retrieve import RetrievedChunk


class _Retriever(Protocol):
    """Anything that returns top-k chunks (highest score first) for a query."""

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


@dataclass(frozen=True)
class SupportThreshold:
    """A calibrated refusal threshold — versioned config, immutable.

    ``calibrated_on`` records *what* it was fit against (e.g. an ISO date + the retriever/model
    id) so a stale threshold is visible at a glance. Re-calibrate when the retriever or corpus
    changes — the score scale moves with them.
    """

    value: float
    calibrated_on: str


def passes_support(top_score: float, threshold: SupportThreshold) -> bool:
    """True iff ``top_score >= threshold.value``. The boundary is inclusive. Pure."""
    return top_score >= threshold.value


def calibrate_threshold(
    in_corpus_top_scores: Sequence[float],
    out_corpus_top_scores: Sequence[float],
    *,
    label: str,
) -> SupportThreshold:
    """Fit a separating threshold between the two top-1 score populations.

    Picks the midpoint of ``max(out-of-corpus)`` and ``min(in-corpus)`` — the widest-margin cut
    when the populations separate. Raises ``ValueError`` if either population is empty, or if
    they **overlap** (``min(in) <= max(out)``): an overlap means retrieval can't yet tell
    answerable from unanswerable, so there is no honest threshold to set. Pure.
    """
    if not in_corpus_top_scores or not out_corpus_top_scores:
        raise ValueError("need both in-corpus and out-of-corpus scores to calibrate a threshold")

    min_in = min(in_corpus_top_scores)
    max_out = max(out_corpus_top_scores)
    if min_in <= max_out:
        raise ValueError(
            f"cannot calibrate a clean threshold: in-corpus min ({min_in:.4f}) <= out-of-corpus "
            f"max ({max_out:.4f}) — the score populations overlap, so retrieval isn't "
            f"discriminative enough to gate on. Improve retrieval before enforcing a threshold."
        )
    return SupportThreshold(value=(min_in + max_out) / 2.0, calibrated_on=label)


def answer_with_enforcement(
    question: str,
    *,
    retriever: _Retriever,
    client: LLMClient,
    threshold: SupportThreshold,
    k: int = 6,
) -> Answer:
    """Retrieve top-k; refuse on weak support *before* the LLM, else delegate to the generator.

    If retrieval is empty or its top-1 score is below ``threshold``, return the canonical
    refusal :class:`~grc_rag.generate.Answer` **without** calling the model. Otherwise hand the
    chunks to :func:`~grc_rag.generate.generate_answer`, whose own Phase-1 checks still apply —
    so the gate only ever *adds* refusals. Raises ``ValueError`` on an empty question.
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")

    chunks = retriever.retrieve(question, k=k)
    if not chunks or not passes_support(chunks[0].score, threshold):
        # Weak (or no) support → refuse without paying for a generation. Reuse the canonical
        # sentinel from generate.py; never fork it.
        return Answer(text=REFUSAL, citations=(), refused=True, prompt_version=PROMPT_VERSION)

    return generate_answer(question, chunks, client=client)
