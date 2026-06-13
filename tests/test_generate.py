"""Tests for cited generation (cite-or-refuse).

Every test drives a deterministic stub LLM — never a live model — so the
contract-critical logic (citation validation, the three refusal paths,
immutability) is asserted exactly and offline. The real-model end-to-end run is a
manual/integration step, not a unit test.
"""

from __future__ import annotations

import dataclasses

import pytest

from conftest import StubLLMClient
from grc_rag import generate
from grc_rag.chunking import Chunk
from grc_rag.retrieve import RetrievedChunk


def _retrieved(chunk_id: str, text: str) -> RetrievedChunk:
    doc_id = chunk_id.split("::")[0]
    return RetrievedChunk(
        chunk=Chunk(chunk_id=chunk_id, doc_id=doc_id, text=text, token_count=5, start_token=0),
        score=1.0,
    )


# --------------------------------------------------------------------------- #
# build_prompt — pure, labelled, carries the contract
# --------------------------------------------------------------------------- #
def test_build_prompt_includes_question_chunks_and_ids() -> None:
    chunks = (
        _retrieved("eu-ai-act::1", "High-risk systems shall comply."),
        _retrieved("nist-ai-rmf::2", "The GOVERN function."),
    )
    prompt = generate.build_prompt("What about high-risk systems?", chunks)
    assert "What about high-risk systems?" in prompt
    assert "eu-ai-act::1" in prompt
    assert "High-risk systems shall comply." in prompt
    assert "nist-ai-rmf::2" in prompt
    # The refusal sentinel is part of the instruction the model receives.
    assert generate.REFUSAL in prompt


def test_build_prompt_is_pure() -> None:
    chunks = (_retrieved("eu-ai-act::1", "text"),)
    _ = generate.build_prompt("q?", chunks)
    assert chunks[0].chunk.text == "text"  # unchanged


# --------------------------------------------------------------------------- #
# parse_citations — keep valid, drop fabricated, dedup, preserve order
# --------------------------------------------------------------------------- #
def test_parse_citations_keeps_valid() -> None:
    allowed = frozenset({"eu-ai-act::4"})
    assert generate.parse_citations("Providers shall comply [eu-ai-act::4].", allowed) == (
        "eu-ai-act::4",
    )


def test_parse_citations_drops_dangling_and_dedups() -> None:
    allowed = frozenset({"eu-ai-act::4", "nist-ai-rmf::2"})
    text = "A [eu-ai-act::4] B [eu-ai-act::999] C [nist-ai-rmf::2] D [eu-ai-act::4]"
    assert generate.parse_citations(text, allowed) == ("eu-ai-act::4", "nist-ai-rmf::2")


def test_parse_citations_none_found() -> None:
    assert generate.parse_citations("no citations here", frozenset({"a::1"})) == ()


# --------------------------------------------------------------------------- #
# generate_answer — the three refusal paths + the grounded path
# --------------------------------------------------------------------------- #
def test_generate_answer_grounded() -> None:
    chunks = (_retrieved("eu-ai-act::4", "Providers of high-risk AI shall ensure compliance."),)
    client = StubLLMClient("Providers must ensure compliance [eu-ai-act::4].")
    answer = generate.generate_answer("What must providers do?", chunks, client=client)
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::4",)
    assert answer.prompt_version == generate.PROMPT_VERSION
    assert "[eu-ai-act::4]" in answer.text


def test_generate_answer_refusal_passthrough() -> None:
    chunks = (_retrieved("eu-ai-act::4", "irrelevant text"),)
    client = StubLLMClient(generate.REFUSAL)
    answer = generate.generate_answer("Unanswerable?", chunks, client=client)
    assert answer.refused is True
    assert answer.citations == ()
    assert answer.text == generate.REFUSAL


def test_generate_answer_zero_valid_citation_refuses() -> None:
    # The model answered but cited only a fabricated id we never retrieved.
    chunks = (_retrieved("eu-ai-act::4", "real text"),)
    client = StubLLMClient("Confident claim [eu-ai-act::999].")
    answer = generate.generate_answer("q?", chunks, client=client)
    assert answer.refused is True
    assert answer.citations == ()
    assert answer.text == generate.REFUSAL


def test_generate_answer_no_chunks_refuses_without_calling_model() -> None:
    client = StubLLMClient("should never be returned")
    answer = generate.generate_answer("q?", (), client=client)
    assert answer.refused is True
    assert client.last_prompt is None  # model was never called


def test_generate_answer_empty_question_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        generate.generate_answer("   ", (), client=StubLLMClient("x"))


def test_answer_is_frozen() -> None:
    answer = generate.Answer(text="t", citations=("c::1",), refused=False, prompt_version="v")
    with pytest.raises(dataclasses.FrozenInstanceError):
        answer.text = "mutated"  # type: ignore[misc]
