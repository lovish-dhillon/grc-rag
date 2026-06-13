"""Tests for the FastAPI boundary over the cite-or-refuse pipeline.

The API is a *thin transport* — it owns no cite-or-refuse logic, so it tests the same way the
rest of the system does: inject stubs via ``create_app`` (a stub retriever returning chosen
chunks, the shared ``StubLLMClient``) and drive the app with ``TestClient`` — **no models, no
key, no network**. The load-bearing assertions mirror the pipeline's invariants at the HTTP
edge: a citation is resolved to its clause + text for click-through; a refusal is a successful
200 (not an error) and never calls the LLM; malformed input fails fast (422).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import StubLLMClient
from grc_rag.api import AskResponse, build_response, create_app
from grc_rag.chunking import Chunk
from grc_rag.enforce import SupportThreshold
from grc_rag.generate import PROMPT_VERSION, REFUSAL, Answer
from grc_rag.retrieve import RetrievedChunk
from grc_rag.tracing import RecordingTracer

_THRESHOLD = SupportThreshold(value=0.5, calibrated_on="test")
_FRONTEND_ORIGIN = "http://localhost:5173"


def _chunk(chunk_id: str, *, text: str, label: str | None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=chunk_id.split("::", 1)[0],
        text=text,
        token_count=len(text.split()),
        start_token=0,
        clause_label=label,
    )


class StubRetriever:
    """Returns a fixed ranking of chunks (highest score first) for any query."""

    def __init__(self, ranking: tuple[RetrievedChunk, ...]) -> None:
        self._ranking = ranking

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        return self._ranking[:k]


_ART5 = _chunk(
    "eu-ai-act::5",
    text="The following AI practices shall be prohibited.",
    label="EU AI Act — Article 5",
)
_ART10 = _chunk(
    "eu-ai-act::10",
    text="High-risk AI systems shall be subject to data governance.",
    label="EU AI Act — Article 10",
)


def _client(*, top_score: float, llm_response: str) -> tuple[TestClient, StubLLMClient]:
    """An app whose stub retriever returns Art.5 (at ``top_score``) then Art.10, and whose stub
    LLM returns ``llm_response``. Returns the test client and the LLM stub (to assert calls)."""
    ranking = (
        RetrievedChunk(chunk=_ART5, score=top_score),
        RetrievedChunk(chunk=_ART10, score=top_score - 0.1),
    )
    llm = StubLLMClient(llm_response)
    app = create_app(
        retriever=StubRetriever(ranking),
        client=llm,
        threshold=_THRESHOLD,
        cors_origins=(_FRONTEND_ORIGIN,),
    )
    return TestClient(app), llm


# --------------------------------------------------------------------------- #
# build_response — the pure response builder
# --------------------------------------------------------------------------- #
def test_build_response_resolves_citation_to_clause_and_text() -> None:
    answer = Answer(
        text="Some practices are prohibited [eu-ai-act::5].",
        citations=("eu-ai-act::5",),
        refused=False,
        prompt_version=PROMPT_VERSION,
    )
    retrieved = (
        RetrievedChunk(chunk=_ART5, score=8.0),
        RetrievedChunk(chunk=_ART10, score=4.0),
    )

    response = build_response("Which practices are prohibited?", answer, retrieved, latency_ms=12.5)

    assert isinstance(response, AskResponse)
    assert response.refused is False
    assert response.prompt_version == PROMPT_VERSION
    assert response.latency_ms == 12.5
    # The citation resolves to its clause label + the exact chunk text (click-through, no extra call).
    assert len(response.citations) == 1
    cite = response.citations[0]
    assert cite.chunk_id == "eu-ai-act::5"
    assert cite.doc_id == "eu-ai-act"
    assert cite.clause_label == "EU AI Act — Article 5"
    assert cite.text == _ART5.text
    assert cite.score == 8.0
    # The full ranking is projected for the "how it answered" panel.
    assert [r.chunk_id for r in response.retrieved] == ["eu-ai-act::5", "eu-ai-act::10"]
    assert [r.clause_label for r in response.retrieved] == [
        "EU AI Act — Article 5",
        "EU AI Act — Article 10",
    ]


def test_build_response_drops_an_unresolvable_citation() -> None:
    # Defensive: a citation to an id not in the retrieved set is dropped, never fabricated.
    answer = Answer(
        text="Claim [eu-ai-act::999].",
        citations=("eu-ai-act::999",),
        refused=False,
        prompt_version=PROMPT_VERSION,
    )
    retrieved = (RetrievedChunk(chunk=_ART5, score=8.0),)
    response = build_response("q?", answer, retrieved, latency_ms=1.0)
    assert response.citations == []


def test_build_response_refusal_has_no_citations() -> None:
    answer = Answer(text=REFUSAL, citations=(), refused=True, prompt_version=PROMPT_VERSION)
    response = build_response("q?", answer, (), latency_ms=2.0)
    assert response.refused is True
    assert response.answer == REFUSAL
    assert response.citations == []
    assert response.retrieved == []


# --------------------------------------------------------------------------- #
# POST /ask — the deployed path at the HTTP edge
# --------------------------------------------------------------------------- #
def test_ask_happy_path_returns_resolved_citation() -> None:
    client, llm = _client(
        top_score=0.9,  # clears the 0.5 threshold → the LLM is consulted
        llm_response="Certain practices are prohibited [eu-ai-act::5].",
    )
    resp = client.post("/ask", json={"question": "Which AI practices are prohibited?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["refused"] is False
    assert body["question"] == "Which AI practices are prohibited?"
    assert body["prompt_version"] == PROMPT_VERSION
    assert body["latency_ms"] >= 0.0
    assert len(body["citations"]) >= 1
    cite = body["citations"][0]
    assert cite["clause_label"] == "EU AI Act — Article 5"
    assert cite["text"]  # non-empty: enables click-through with no extra call
    assert llm.last_prompt is not None  # the model WAS called on the happy path


def test_ask_refusal_is_a_200_and_short_circuits_the_llm() -> None:
    client, llm = _client(
        top_score=0.2,  # below the 0.5 threshold → refuse BEFORE the LLM
        llm_response="this must never be returned",
    )
    resp = client.post("/ask", json={"question": "What does ISO 42001 clause 6 require?"})

    assert resp.status_code == 200  # a refusal is a successful response, not an error
    body = resp.json()
    assert body["refused"] is True
    assert body["answer"] == REFUSAL
    assert body["citations"] == []
    # The gate short-circuits: the LLM is never invoked on weak support.
    assert llm.last_prompt is None


def test_ask_records_a_trace_through_the_tracer_seam() -> None:
    ranking = (RetrievedChunk(chunk=_ART5, score=0.9),)
    tracer = RecordingTracer()
    app = create_app(
        retriever=StubRetriever(ranking),
        client=StubLLMClient("Prohibited practices [eu-ai-act::5]."),
        threshold=_THRESHOLD,
        tracer=tracer,
    )
    TestClient(app).post("/ask", json={"question": "Which practices are prohibited?"})

    assert len(tracer.traces) == 1
    trace = tracer.traces[0]
    assert trace.retrieved_ids == ("eu-ai-act::5",)
    assert trace.refused is False
    assert trace.citations == ("eu-ai-act::5",)


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
def test_ask_rejects_blank_question_422(question: str) -> None:
    client, _ = _client(top_score=0.9, llm_response="unused")
    resp = client.post("/ask", json={"question": question})
    assert resp.status_code == 422


def test_ask_rejects_oversized_question_422() -> None:
    client, _ = _client(top_score=0.9, llm_response="unused")
    resp = client.post("/ask", json={"question": "x" * 2001})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# CORS + health
# --------------------------------------------------------------------------- #
def test_cors_allows_the_configured_frontend_origin() -> None:
    client, _ = _client(top_score=0.9, llm_response="unused")
    resp = client.options(
        "/ask",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == _FRONTEND_ORIGIN


def test_health_is_ok() -> None:
    client, _ = _client(top_score=0.9, llm_response="unused")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
