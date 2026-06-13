"""Observability — record what each query did, behind a seam, without coupling to the backend.

A trust claim needs operational evidence, not just quality scores: *what did this query
retrieve, what did it answer, did it refuse, how long did it take, what did it cost?* When an
answer is wrong or a refusal surprises you, that trace is what lets you debug it instead of
guessing — and the headline ops numbers (latency P50/P95, cost/req) in ``04-results.md`` are
read off these traces.

Two commitments keep this explainable rather than magic:

* **A one-method :class:`Tracer` seam — never an import of the backend.** The pipeline records
  through ``tracer.record(QueryTrace(...))`` and nothing here imports ``langfuse``; only
  :class:`LangfuseTracer` does, lazily. The default :class:`NullTracer` records nothing, so
  answering a query never depends on a backend being up, and unit tests use
  :class:`RecordingTracer` — no Docker, no live server. (This mirrors the ``LLMClient`` /
  ``Encoder`` / ``CrossEncoder`` seams the rest of the system uses.)

* **Instrument by wrapping, not by editing.** :func:`traced_answer` and
  :func:`traced_answer_with_enforcement` time the *existing* pipeline functions and record a
  trace around them; ``answer_question`` / ``answer_with_enforcement`` are untouched. To capture
  the retrieved ids/scores without reproducing pipeline logic, the wrapper passes the real
  function a small recording proxy over the retriever — so the pipeline stays authoritative and
  the trace just observes what it actually returned.

Langfuse is the chosen backend, **self-hosted and free** (Docker). It is an *observability*
backend — a place to send and view spans — not a RAG framework: it orchestrates nothing and
makes no retrieval/generation decisions, so it does not violate the no-LangChain/LlamaIndex
rule. The percentile/cost aggregation lives in our own pure :mod:`grc_rag.percentiles`, so the
numbers we report are ones we can derive and defend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from grc_rag.enforce import SupportThreshold, answer_with_enforcement
from grc_rag.generate import Answer, LLMClient
from grc_rag.pipeline import Retriever, answer_question
from grc_rag.retrieve import RetrievedChunk

_LANGFUSE_ENV = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


@dataclass(frozen=True)
class QueryTrace:
    """One query's operational record — the unit Langfuse stores and percentiles aggregate.

    Captures exactly what you need to debug a wrong answer or a surprising refusal: the
    question, the retrieved chunk ids *and* their scores in rank order, the answer and its
    citations, whether it refused, the prompt version, wall-clock latency, and cost (``0.0``
    for the local Ollama generator; an API cost when a cloud model was used). Immutable.
    """

    question: str
    retrieved_ids: tuple[str, ...]
    retrieved_scores: tuple[float, ...]
    answer_text: str
    citations: tuple[str, ...]
    refused: bool
    prompt_version: str
    latency_ms: float
    cost_usd: float


class Tracer(Protocol):
    """The single seam to the observability backend. One method — easy to stub or swap."""

    def record(self, trace: QueryTrace) -> None: ...


class NullTracer:
    """The default: records nothing. The pipeline runs identically with no backend attached."""

    def record(self, trace: QueryTrace) -> None:
        return None


class RecordingTracer:
    """Test double: keeps every trace in a list so tests can assert on what was recorded."""

    def __init__(self) -> None:
        self.traces: list[QueryTrace] = []

    def record(self, trace: QueryTrace) -> None:
        self.traces.append(trace)


class LangfuseTracer:
    """Ships each :class:`QueryTrace` to a self-hosted Langfuse as one trace.

    Reads ``LANGFUSE_HOST`` / ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` from the
    environment and **fails fast** in ``__init__`` if any is missing — a half-configured
    backend is a silent data-loss hazard. The ``langfuse`` SDK is imported lazily so merely
    importing this module never requires the package.
    """

    def __init__(self) -> None:
        missing = [name for name in _LANGFUSE_ENV if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                f"LangfuseTracer needs {', '.join(_LANGFUSE_ENV)} in the environment; "
                f"missing: {', '.join(missing)}. Start self-hosted Langfuse (see 05-demo.md) "
                f"and export the keys, or use NullTracer."
            )
        self._host = os.environ["LANGFUSE_HOST"]
        self._public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
        self._secret_key = os.environ["LANGFUSE_SECRET_KEY"]
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from langfuse import Langfuse

            self._client = Langfuse(
                host=self._host, public_key=self._public_key, secret_key=self._secret_key
            )
        return self._client

    def record(self, trace: QueryTrace) -> None:
        client = self._get_client()
        # One event per query (Langfuse v3+ `create_event`), with the retrieval + answer detail
        # as metadata so the observation in the UI carries everything QueryTrace holds.
        client.create_event(  # type: ignore[attr-defined]
            name="grc-rag-query",
            input=trace.question,
            output=trace.answer_text,
            metadata={
                "retrieved_ids": list(trace.retrieved_ids),
                "retrieved_scores": list(trace.retrieved_scores),
                "citations": list(trace.citations),
                "refused": trace.refused,
                "prompt_version": trace.prompt_version,
                "latency_ms": trace.latency_ms,
                "cost_usd": trace.cost_usd,
            },
        )


class _RecordingRetriever:
    """Wraps the real retriever, delegates ``retrieve``, and remembers what it last returned —
    so a traced wrapper can read the retrieved chunks without reproducing pipeline logic."""

    def __init__(self, inner: Retriever) -> None:
        self._inner = inner
        self.last: tuple[RetrievedChunk, ...] = ()

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        self.last = self._inner.retrieve(query, k=k)
        return self.last


def _build_trace(
    question: str, proxy: _RecordingRetriever, answer: Answer, latency_ms: float, cost_usd: float
) -> QueryTrace:
    return QueryTrace(
        question=question,
        retrieved_ids=tuple(rc.chunk.chunk_id for rc in proxy.last),
        retrieved_scores=tuple(rc.score for rc in proxy.last),
        answer_text=answer.text,
        citations=answer.citations,
        refused=answer.refused,
        prompt_version=answer.prompt_version,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


def traced_answer(
    question: str,
    *,
    retriever: Retriever,
    client: LLMClient,
    tracer: Tracer = NullTracer(),
    k: int = 10,
    cost_usd: float = 0.0,
) -> Answer:
    """Run :func:`~grc_rag.pipeline.answer_question`, record a :class:`QueryTrace`, return the
    **unchanged** :class:`Answer`. Additive — the underlying pipeline logic is untouched."""
    proxy = _RecordingRetriever(retriever)
    start = perf_counter()
    answer = answer_question(question, retriever=proxy, client=client, k=k)
    latency_ms = (perf_counter() - start) * 1000.0
    tracer.record(_build_trace(question, proxy, answer, latency_ms, cost_usd))
    return answer


def traced_answer_with_enforcement(
    question: str,
    *,
    retriever: Retriever,
    client: LLMClient,
    threshold: SupportThreshold,
    tracer: Tracer = NullTracer(),
    k: int = 6,
    cost_usd: float = 0.0,
) -> Answer:
    """Like :func:`traced_answer` but for the enforced (threshold-gated) pipeline. Records the
    retrieval even when the gate refuses before the LLM. Additive — ``answer_with_enforcement``
    is untouched."""
    proxy = _RecordingRetriever(retriever)
    start = perf_counter()
    answer = answer_with_enforcement(
        question, retriever=proxy, client=client, threshold=threshold, k=k
    )
    latency_ms = (perf_counter() - start) * 1000.0
    tracer.record(_build_trace(question, proxy, answer, latency_ms, cost_usd))
    return answer
