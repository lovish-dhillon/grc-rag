"""HTTP boundary — a thin, stateless FastAPI surface over the cite-or-refuse pipeline.

The pipeline is a library + CLI. A UI needs an HTTP edge so the frontend never reaches into
Python internals — but the edge must add a *transport*, not logic. Everything that makes the
system trustworthy (cite-or-refuse, the calibrated support threshold, verified citations) stays
in :mod:`grc_rag.enforce` / :mod:`grc_rag.generate`; this module only exposes it. Three
commitments keep it honest:

* **Reuse the seams, never fork the pipeline.** ``POST /ask`` calls the *deployed*
  :func:`~grc_rag.enforce.answer_with_enforcement` over the injected retriever. To also surface
  the retrieved chunks (for citation click-through + a retrieval panel) without reproducing
  pipeline logic, it wraps the retriever in the existing :class:`~grc_rag.tracing._RecordingRetriever`
  and reads ``proxy.last`` — the pipeline stays authoritative; the API just observes what it
  returned.

* **A refusal is a successful 200, not an error.** When support is weak the system *should*
  refuse, and that is a valid, healthy outcome — ``{"refused": true}`` with the sentinel and no
  citations, HTTP 200. Only malformed input (422) or a backend fault (5xx) is an error. Making
  the refusal an error would punish the system for its central virtue.

* **Resolve citations at the boundary.** ``Answer.citations`` are bare ``chunk_id``s. The
  response builder joins each to its :class:`~grc_rag.retrieve.RetrievedChunk` and emits the
  ``clause_label`` + chunk ``text`` — exactly what the CLI resolves at print time — so the
  frontend renders a clause card with no second round-trip.

Collaborators (the retriever, the calibrated :class:`~grc_rag.enforce.SupportThreshold`, the
``LLMClient``) are injected via :func:`create_app` and built **once** — so unit tests pass stubs
(no models, no key, no network) and production loads the heavy objects a single time at startup.
``build_default_app`` does the live wiring for ``uvicorn grc_rag.api:app`` and **fails fast** if
the index or threshold is missing.
"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from grc_rag.enforce import SupportThreshold, answer_with_enforcement
from grc_rag.generate import Answer, LLMClient
from grc_rag.tracing import NullTracer, QueryTrace, Tracer, _RecordingRetriever

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from grc_rag.pipeline import Retriever
    from grc_rag.retrieve import RetrievedChunk

# The Vite dev server's default origin. Overridable via ``create_app(cors_origins=...)`` /
# ``GRC_RAG_CORS_ORIGINS`` so dev (localhost) and a deployed build differ by config, not code.
_DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)
_MAX_QUESTION_LEN = 2000

# Which generator the deployed app uses. Ollama is the default because it is keyless and zero
# marginal cost — correct on a laptop, impossible in a container. See ADR-0020.
_LLM_BACKEND_ENV = "GRC_RAG_LLM"
_LLM_MODEL_ENV = "GRC_RAG_LLM_MODEL"
_DEFAULT_LLM_BACKEND = "ollama"
_LLM_BACKENDS = ("ollama", "anthropic")


# --------------------------------------------------------------------------- #
# Wire DTOs — validated at the boundary, immutable by construction (Pydantic).
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    """The request body. Pydantic rejects a blank or oversized question with a 422."""

    question: str = Field(min_length=1, max_length=_MAX_QUESTION_LEN)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # ``min_length`` already rejects ""; this also rejects whitespace-only input — fail fast
        # at the edge so ``answer_with_enforcement`` never has to. The value is not mutated.
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class CitationOut(BaseModel):
    """One resolved citation — the cited chunk, joined to its clause + text for click-through."""

    chunk_id: str
    doc_id: str
    clause_label: str | None  # the human clause this resolves to (None if the chunk is unlabelled)
    text: str  # the cited chunk's exact text — enables click-through with no extra request
    score: float


class RetrievedOut(BaseModel):
    """One ranked retrieved chunk — for the optional 'how it answered' panel."""

    chunk_id: str
    clause_label: str | None
    score: float


class AskResponse(BaseModel):
    """The typed answer the frontend renders: the text, whether it refused, the resolved
    citations, the full ranking, the prompt version, and wall-clock latency. Immutable."""

    question: str
    answer: str
    refused: bool
    citations: list[CitationOut]
    retrieved: list[RetrievedOut]
    prompt_version: str
    latency_ms: float


def build_response(
    question: str,
    answer: Answer,
    retrieved: Sequence[RetrievedChunk],
    latency_ms: float,
) -> AskResponse:
    """Resolve ``answer.citations`` against ``retrieved`` into :class:`CitationOut`, project the
    ranking into :class:`RetrievedOut`, and assemble the DTO. Pure — no I/O.

    A citation that doesn't join to a retrieved chunk is **dropped**, never fabricated (it
    already can't happen — :func:`~grc_rag.generate.generate_answer` validates every citation
    against the retrieved set — but the builder stays defensive).
    """
    by_id = {rc.chunk.chunk_id: rc for rc in retrieved}
    citations = [
        CitationOut(
            chunk_id=cid,
            doc_id=by_id[cid].chunk.doc_id,
            clause_label=by_id[cid].chunk.clause_label,
            text=by_id[cid].chunk.text,
            score=by_id[cid].score,
        )
        for cid in answer.citations
        if cid in by_id
    ]
    ranking = [
        RetrievedOut(
            chunk_id=rc.chunk.chunk_id,
            clause_label=rc.chunk.clause_label,
            score=rc.score,
        )
        for rc in retrieved
    ]
    return AskResponse(
        question=question,
        answer=answer.text,
        refused=answer.refused,
        citations=citations,
        retrieved=ranking,
        prompt_version=answer.prompt_version,
        latency_ms=latency_ms,
    )


def create_app(
    *,
    retriever: Retriever,
    client: LLMClient,
    threshold: SupportThreshold,
    tracer: Tracer = NullTracer(),
    k: int = 6,
    cors_origins: Sequence[str] = _DEFAULT_CORS_ORIGINS,
) -> FastAPI:
    """Build the app with collaborators **injected** (tests pass stubs). Registers ``POST /ask``
    and ``GET /health`` and enables CORS for ``cors_origins``.

    ``/ask`` wraps ``retriever`` in :class:`~grc_rag.tracing._RecordingRetriever`, runs the
    deployed :func:`~grc_rag.enforce.answer_with_enforcement` over it, times the call, builds the
    response from the answer + the recorded chunks, and records a :class:`QueryTrace` through the
    tracer seam. The collaborators are closed over and reused across requests — built once, never
    per request.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="grc-rag", summary="Cite-or-refuse Q&A over AI-governance regulation.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        proxy = _RecordingRetriever(retriever)
        start = perf_counter()
        answer = answer_with_enforcement(
            request.question, retriever=proxy, client=client, threshold=threshold, k=k
        )
        latency_ms = (perf_counter() - start) * 1000.0
        response = build_response(request.question, answer, proxy.last, latency_ms)
        tracer.record(
            QueryTrace(
                question=request.question,
                retrieved_ids=tuple(rc.chunk.chunk_id for rc in proxy.last),
                retrieved_scores=tuple(rc.score for rc in proxy.last),
                answer_text=answer.text,
                citations=answer.citations,
                refused=answer.refused,
                prompt_version=answer.prompt_version,
                latency_ms=latency_ms,
                cost_usd=0.0,  # the local Ollama generator is zero marginal cost
            )
        )
        return response

    return app


def build_llm_client(backend: str | None = None) -> LLMClient:
    """Return the generator named by ``backend`` (default ``$GRC_RAG_LLM``, else Ollama).

    The generator is the one component that cannot follow the code into a container: Ollama is a
    local daemon, and a Container App has no sidecar for it. The :class:`~grc_rag.generate.LLMClient`
    seam already makes generators interchangeable, so the deployment difference is *config, not a
    second code path* — laptop keeps the keyless local model, cloud selects hosted Claude.

    An unknown name raises rather than falling back to a default. A silent fallback would mean a
    deployment generating with a model nobody chose, which would quietly invalidate every measured
    faithfulness number the gate depends on — the exact class of failure this repo exists to prevent.
    Imports stay lazy so the local path never requires the ``anthropic`` SDK, and vice versa.
    """
    import os

    name = (backend or os.environ.get(_LLM_BACKEND_ENV) or _DEFAULT_LLM_BACKEND).strip().lower()
    if name == "ollama":
        from grc_rag.llm import OllamaClient

        return OllamaClient()
    if name == "anthropic":
        from grc_rag.llm import AnthropicClient

        model = os.environ.get(_LLM_MODEL_ENV)
        return AnthropicClient(model=model) if model else AnthropicClient()
    raise ValueError(
        f"unknown {_LLM_BACKEND_ENV}={name!r} — expected one of {', '.join(_LLM_BACKENDS)}"
    )


def build_default_app() -> FastAPI:  # pragma: no cover - live wiring (integration-only)
    """Production wiring for ``uvicorn grc_rag.api:app``: the deployed hybrid+rerank retriever +
    the configured generator + the persisted calibrated threshold. Fails fast if the index or
    the threshold file is absent (``_build_retriever`` raises on a missing index;
    ``load_threshold`` returns ``None`` → we raise). CORS origins come from
    ``GRC_RAG_CORS_ORIGINS`` (comma-separated) or the localhost default; the generator from
    ``GRC_RAG_LLM`` (see :func:`build_llm_client`)."""
    import os
    from pathlib import Path

    from grc_rag.query import build_retriever, load_threshold

    index_dir = Path(os.environ.get("GRC_RAG_INDEX_DIR", "data/processed"))
    threshold = load_threshold(index_dir)
    if threshold is None:
        raise RuntimeError(
            f"no calibrated support threshold at {index_dir}/support-threshold.json — "
            f"the enforced cite-or-refuse path needs it. Build the index + calibrate first."
        )
    origins_env = os.environ.get("GRC_RAG_CORS_ORIGINS")
    cors_origins = (
        tuple(o.strip() for o in origins_env.split(",")) if origins_env else _DEFAULT_CORS_ORIGINS
    )
    return create_app(
        retriever=build_retriever(index_dir),
        client=build_llm_client(),
        threshold=threshold,
        cors_origins=cors_origins,
    )


def __getattr__(name: str) -> object:  # pragma: no cover - lazy live wiring for uvicorn
    """Lazily build the production app only when ``grc_rag.api:app`` is *accessed* (as uvicorn
    does) — so merely importing this module for tests never loads models or the index."""
    if name == "app":
        return build_default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
