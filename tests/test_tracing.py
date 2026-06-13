"""Tests for the tracing seam — no Docker, no live server, no SDK.

The pipeline is driven with stubs and a ``RecordingTracer``; the load-bearing assertions are
that tracing is *additive* (the returned Answer is unchanged) and that the trace faithfully
captures the retrieval + answer. ``LangfuseTracer`` is only checked for its fail-fast behaviour.
"""

from __future__ import annotations

import dataclasses

import pytest

from conftest import StubLLMClient
from grc_rag.chunking import Chunk
from grc_rag.enforce import SupportThreshold
from grc_rag.generate import REFUSAL
from grc_rag.pipeline import answer_question
from grc_rag.retrieve import RetrievedChunk
from grc_rag.tracing import (
    NullTracer,
    QueryTrace,
    RecordingTracer,
    traced_answer,
    traced_answer_with_enforcement,
)

_CHUNK_ID = "eu-ai-act::5"


class StubRetriever:
    def __init__(self, *, score: float = 5.0, empty: bool = False) -> None:
        self._score = score
        self._empty = empty

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        if self._empty:
            return ()
        chunk = Chunk(
            chunk_id=_CHUNK_ID,
            doc_id="eu-ai-act",
            text="The following AI practices shall be prohibited ...",
            token_count=9,
            start_token=0,
            clause_label="EU AI Act — Article 5",
        )
        return (RetrievedChunk(chunk=chunk, score=self._score),)


def test_query_trace_is_frozen() -> None:
    trace = QueryTrace("q", (), (), "a", (), False, "v", 1.0, 0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        trace.latency_ms = 2.0  # type: ignore[misc]


def test_null_tracer_is_noop() -> None:
    assert NullTracer().record(QueryTrace("q", (), (), "a", (), False, "v", 1.0, 0.0)) is None


def test_traced_answer_records_one_trace_and_is_additive() -> None:
    retriever = StubRetriever()
    client = StubLLMClient(f"Prohibited practices are listed [{_CHUNK_ID}].")
    tracer = RecordingTracer()

    answer = traced_answer(
        "Which practices are prohibited?", retriever=retriever, client=client, tracer=tracer
    )

    # Additivity: identical to the un-traced pipeline result.
    expected = answer_question(
        "Which practices are prohibited?",
        retriever=StubRetriever(),
        client=StubLLMClient(client.response),
    )
    assert answer == expected

    assert len(tracer.traces) == 1
    trace = tracer.traces[0]
    assert trace.retrieved_ids == (_CHUNK_ID,)
    assert trace.retrieved_scores == (5.0,)
    assert trace.citations == (_CHUNK_ID,)
    assert trace.refused is False
    assert trace.prompt_version == answer.prompt_version
    assert trace.latency_ms > 0
    assert trace.cost_usd == 0.0


def test_traced_answer_records_refusal() -> None:
    tracer = RecordingTracer()
    answer = traced_answer(
        "Which practices are prohibited?",
        retriever=StubRetriever(),
        client=StubLLMClient(REFUSAL),
        tracer=tracer,
    )
    assert answer.refused is True
    assert tracer.traces[0].refused is True
    assert tracer.traces[0].citations == ()
    # Even on refusal, the retrieval that led there is captured.
    assert tracer.traces[0].retrieved_ids == (_CHUNK_ID,)


def test_traced_enforcement_refuses_below_threshold_and_traces() -> None:
    tracer = RecordingTracer()
    client = StubLLMClient("should never be called")
    threshold = SupportThreshold(value=10.0, calibrated_on="test")  # above the stub's score
    answer = traced_answer_with_enforcement(
        "q?", retriever=StubRetriever(score=1.0), client=client, threshold=threshold, tracer=tracer
    )
    assert answer.refused is True
    assert client.last_prompt is None  # gate refused before the LLM
    assert tracer.traces[0].refused is True
    assert tracer.traces[0].retrieved_ids == (_CHUNK_ID,)  # retrieval still traced


def test_langfuse_tracer_fails_fast_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from grc_rag.tracing import LangfuseTracer

    for name in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="LANGFUSE"):
        LangfuseTracer()  # must not import or reach the SDK
