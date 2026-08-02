"""Tests for the MCP boundary over the cite-or-refuse pipeline.

The MCP server is a *thin transport*, exactly like the FastAPI boundary, so it is tested the same
way: inject a stub retriever and the shared ``StubLLMClient`` into the pure payload builder — **no
models, no key, no network, and no ``mcp`` SDK required**. The load-bearing assertions are the ones
that protect the system's central promise at a new edge: a citation resolves to its clause and text,
a refusal is a successful result rather than an exception, and a blank question fails fast.

``serve()`` itself is deliberately untested here — it is SDK plumbing over
:func:`~grc_rag.mcp_server.build_answer_payload`, which is where all the behaviour lives.
"""

from __future__ import annotations

import pytest

from conftest import StubLLMClient
from grc_rag.chunking import Chunk
from grc_rag.enforce import SupportThreshold
from grc_rag.generate import PROMPT_VERSION, REFUSAL
from grc_rag.mcp_server import build_answer_payload
from grc_rag.retrieve import RetrievedChunk

_THRESHOLD = SupportThreshold(value=0.5, calibrated_on="test")


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


def _payload(*, top_score: float, llm_response: str) -> tuple[dict, StubLLMClient]:
    """Build a payload against a stub retriever returning Art.5 at ``top_score``."""
    llm = StubLLMClient(llm_response)
    payload = build_answer_payload(
        "What does the EU AI Act prohibit?",
        retriever=StubRetriever((RetrievedChunk(chunk=_ART5, score=top_score),)),
        client=llm,
        threshold=_THRESHOLD,
    )
    return payload, llm


def test_grounded_answer_resolves_citation_to_clause_and_text() -> None:
    """A cited chunk_id is joined to its clause label and source text, so the calling model can
    quote the clause without a second round-trip."""
    payload, _ = _payload(
        top_score=0.9,
        llm_response="Certain practices are prohibited. [eu-ai-act::5]",
    )

    assert payload["refused"] is False
    assert payload["prompt_version"] == PROMPT_VERSION
    assert len(payload["citations"]) == 1
    citation = payload["citations"][0]
    assert citation["chunk_id"] == "eu-ai-act::5"
    assert citation["doc_id"] == "eu-ai-act"
    assert citation["clause_label"] == "EU AI Act — Article 5"
    assert citation["text"] == _ART5.text
    assert citation["score"] == pytest.approx(0.9)


def test_weak_support_refuses_without_calling_the_model() -> None:
    """A refusal is a successful result, not an exception — and the enforcement gate must refuse
    *before* the LLM is reached, so a weak-support question costs nothing."""
    payload, llm = _payload(top_score=0.1, llm_response="should never be used")

    assert payload["refused"] is True
    assert payload["answer"] == REFUSAL
    assert payload["citations"] == []
    assert llm.last_prompt is None, "the generator must not be called below the support threshold"


def test_uncited_answer_returns_no_citations() -> None:
    """An answer the generator failed to cite yields an empty citation list — the boundary never
    invents provenance to fill the gap."""
    payload, _ = _payload(top_score=0.9, llm_response="Certain practices are prohibited.")

    assert payload["citations"] == []


def test_citation_to_an_unretrieved_chunk_is_dropped_not_fabricated() -> None:
    """A citation that doesn't join to a retrieved chunk is dropped rather than emitted with
    placeholder text — the same defensive rule the HTTP boundary applies."""
    payload, _ = _payload(
        top_score=0.9,
        llm_response="Prohibited practices. [eu-ai-act::5] [nist-ai-rmf::99]",
    )

    ids = [c["chunk_id"] for c in payload["citations"]]
    assert ids == ["eu-ai-act::5"]


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_blank_question_fails_fast(question: str) -> None:
    """Boundary validation raises loudly rather than passing garbage into the pipeline."""
    with pytest.raises(ValueError, match="must not be blank"):
        build_answer_payload(
            question,
            retriever=StubRetriever((RetrievedChunk(chunk=_ART5, score=0.9),)),
            client=StubLLMClient("unused"),
            threshold=_THRESHOLD,
        )
