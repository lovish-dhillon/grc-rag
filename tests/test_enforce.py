"""Tests for threshold-based refusal enforcement.

The gate is pure arithmetic over a retriever's top-1 score, so it tests with stubs only: a
stub retriever that returns a chosen top score, and the shared ``StubLLMClient`` whose
``last_prompt`` stays ``None`` if it was never called — which is how we prove the gate refuses
*without* paying for a generation.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from conftest import StubLLMClient
from grc_rag.chunking import Chunk
from grc_rag.enforce import (
    SupportThreshold,
    answer_with_enforcement,
    calibrate_threshold,
    passes_support,
)
from grc_rag.generate import PROMPT_VERSION, REFUSAL
from grc_rag.retrieve import RetrievedChunk


class StubRetriever:
    """Returns one chunk at a chosen top-1 ``score`` for any query."""

    def __init__(self, top_score: float, *, empty: bool = False) -> None:
        self._top_score = top_score
        self._empty = empty

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        if self._empty:
            return ()
        chunk = Chunk(
            chunk_id="eu-ai-act::4",
            doc_id="eu-ai-act",
            text="Providers shall ensure compliance.",
            token_count=1,
            start_token=0,
        )
        return (RetrievedChunk(chunk=chunk, score=self._top_score),)


_THRESHOLD = SupportThreshold(value=0.5, calibrated_on="test")


# --------------------------------------------------------------------------- #
# passes_support / calibrate_threshold — the pure core
# --------------------------------------------------------------------------- #
def test_passes_support_inclusive_boundary() -> None:
    assert passes_support(0.6, _THRESHOLD) is True
    assert passes_support(0.4, _THRESHOLD) is False
    assert passes_support(0.5, _THRESHOLD) is True  # boundary is inclusive (>=)


def test_calibrate_threshold_separates_populations() -> None:
    threshold = calibrate_threshold([0.8, 0.9, 0.85], [-2.0, -1.0], label="probe-set/2026-06-12")
    # Strictly between the two populations: max-out (-1.0) < value < min-in (0.8).
    assert -1.0 < threshold.value < 0.8
    assert threshold.value == pytest.approx((0.8 + -1.0) / 2)
    assert threshold.calibrated_on == "probe-set/2026-06-12"


def test_calibrate_threshold_fails_fast_on_overlap() -> None:
    # in-corpus min (0.5) <= out-of-corpus max (0.7) → not separable → refuse to guess.
    with pytest.raises(ValueError, match="overlap"):
        calibrate_threshold([0.5, 0.9], [0.3, 0.7], label="bad")


def test_calibrate_threshold_requires_both_populations() -> None:
    with pytest.raises(ValueError, match="both"):
        calibrate_threshold([0.8], [], label="x")


def test_support_threshold_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _THRESHOLD.value = 0.9  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# answer_with_enforcement — the gate
# --------------------------------------------------------------------------- #
def test_gate_refuses_below_threshold_without_calling_llm() -> None:
    retriever = StubRetriever(top_score=0.2)  # below 0.5
    client = StubLLMClient("this should never be returned")

    answer = answer_with_enforcement("q?", retriever=retriever, client=client, threshold=_THRESHOLD)
    assert answer.refused is True
    assert answer.text == REFUSAL
    assert answer.citations == ()
    assert answer.prompt_version == PROMPT_VERSION
    # The load-bearing assertion: the model was never invoked.
    assert client.last_prompt is None


def test_gate_refuses_on_empty_retrieval_without_calling_llm() -> None:
    client = StubLLMClient("unused")
    answer = answer_with_enforcement(
        "q?", retriever=StubRetriever(0.0, empty=True), client=client, threshold=_THRESHOLD
    )
    assert answer.refused is True
    assert client.last_prompt is None


def test_gate_delegates_above_threshold() -> None:
    retriever = StubRetriever(top_score=0.9)  # above 0.5
    client = StubLLMClient("Providers shall ensure compliance [eu-ai-act::4].")

    answer = answer_with_enforcement(
        "What must providers do?", retriever=retriever, client=client, threshold=_THRESHOLD
    )
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::4",)
    assert client.last_prompt is not None  # the model WAS called this time


def test_gate_never_upgrades_a_refusal() -> None:
    # Support clears the threshold, but the model still refuses → the Phase-1 check governs.
    retriever = StubRetriever(top_score=0.9)
    client = StubLLMClient(REFUSAL)
    answer = answer_with_enforcement("q?", retriever=retriever, client=client, threshold=_THRESHOLD)
    assert answer.refused is True


def test_gate_rejects_empty_question() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        answer_with_enforcement(
            "  ", retriever=StubRetriever(0.9), client=StubLLMClient("x"), threshold=_THRESHOLD
        )


# --------------------------------------------------------------------------- #
# Integration: calibrate on the real probe set, then enforce. Off by default.
# --------------------------------------------------------------------------- #
_OUT_OF_CORPUS = (
    "What does ISO/IEC 42001 clause 6.1.2 require?",
    "What is the audit period for a SOC 2 Type II report?",
    "How much does the GPT-4 API cost per 1,000 tokens?",
    "What are the HIPAA breach-notification timelines?",
    "Who won the 2026 Australian Open?",
)
_IN_CORPUS = (
    "What are the obligations for providers of high-risk AI systems?",
    "Which AI practices are prohibited?",
    "What transparency obligations apply to AI systems that interact with natural persons?",
    "What are the core functions of the NIST AI Risk Management Framework?",
    "What is confabulation in the context of generative AI?",
)


@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the real models + a built index; set RUN_INTEGRATION=1 to run",
)
def test_calibrated_gate_refuses_all_out_of_corpus() -> None:
    from pathlib import Path

    from grc_rag.bm25 import BM25Index
    from grc_rag.embeddings import _INDEX_FILE
    from grc_rag.hybrid import HybridRetriever
    from grc_rag.rerank import CrossEncoderReranker, RerankingRetriever
    from grc_rag.retrieve import DenseRetriever

    index_dir = Path("data/processed")
    hybrid = HybridRetriever(
        DenseRetriever.from_index(index_dir),
        BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE),
    )
    retriever = RerankingRetriever(hybrid, CrossEncoderReranker(), candidate_k=50, top_k=6)

    def top1(q: str) -> float:
        return retriever.retrieve(q, k=6)[0].score

    in_scores = [top1(q) for q in _IN_CORPUS]
    out_scores = [top1(q) for q in _OUT_OF_CORPUS]
    print(f"\nin-corpus top1 : {[round(s, 3) for s in in_scores]}")
    print(f"out-corpus top1: {[round(s, 3) for s in out_scores]}")

    threshold = calibrate_threshold(
        in_scores, out_scores, label="probe-set/cross-encoder/2026-06-12"
    )
    print(f"threshold = {threshold.value:.4f}")

    # Every out-of-corpus probe must fall below the gate; every in-corpus probe must clear it.
    assert all(not passes_support(s, threshold) for s in out_scores)
    assert all(passes_support(s, threshold) for s in in_scores)
