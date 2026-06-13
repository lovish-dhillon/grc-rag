"""Tests for prompts-as-files.

Two guarantees. (1) **v1 is frozen history**: the Phase-1 rendered prompt is byte-identical to
the captured golden (SHA-256 8e20d44…), so the retired version can never silently drift — an
``Answer`` stamped ``cite-or-refuse/v1`` always means exactly this text. (2) The live
``build_prompt`` now renders **v2** (Phase 3 tightened cite-or-refuse to curb v1 over-claiming),
so it must carry the v2 wording and differ from the v1 golden, while still filling the same
placeholders.
"""

from __future__ import annotations

import hashlib

import pytest

from grc_rag.chunking import Chunk
from grc_rag.generate import PROMPT_VERSION, REFUSAL, build_prompt
from grc_rag.prompts import load_prompt
from grc_rag.retrieve import RetrievedChunk

# The exact Phase-1 (v1) output for the input below — the byte-for-byte frozen-history contract.
_V1_GOLDEN_PROMPT = (
    "You are a careful assistant answering questions about AI-governance standards "
    "(NIST AI RMF, NIST Generative AI Profile, EU AI Act). Answer using ONLY the numbered "
    "source chunks below.\n\nRules:\n- Use only information contained in the CHUNKS. Never use "
    "outside knowledge.\n- Support every factual claim with an inline citation in square "
    "brackets, using the exact chunk id shown — for example [eu-ai-act::96]. Cite the specific "
    "chunk the claim came from.\n- If the CHUNKS do not contain enough information to answer the "
    "question, reply with EXACTLY this line and nothing else:\nNot supported by the corpus.\n\n"
    "CHUNKS:\n[eu-ai-act::4]\nProviders shall ensure compliance.\n\nQUESTION: What must "
    "providers do?\n\nANSWER:"
)


def _one_chunk() -> tuple[RetrievedChunk, ...]:
    chunk = Chunk(
        chunk_id="eu-ai-act::4",
        doc_id="eu-ai-act",
        text="Providers shall ensure compliance.",
        token_count=5,
        start_token=0,
    )
    return (RetrievedChunk(chunk=chunk, score=1.0),)


def _render(prompt_id: str) -> str:
    """Render a prompt id with the standard single-chunk input, the way ``build_prompt`` does."""
    blocks = "[eu-ai-act::4]\nProviders shall ensure compliance."
    return load_prompt(prompt_id).format(
        refusal=REFUSAL, chunks=blocks, question="What must providers do?"
    )


def test_v1_is_frozen_history() -> None:
    rendered = _render("cite-or-refuse.v1")
    assert rendered == _V1_GOLDEN_PROMPT
    assert hashlib.sha256(rendered.encode()).hexdigest() == (
        "8e20d44a8567f5a83e863039b233623961d025eadcb66b12641229e9e8533def"
    )


def test_build_prompt_now_renders_v2() -> None:
    rendered = build_prompt("What must providers do?", _one_chunk())
    # carries the v2-specific wording, fills the input, and is NOT the v1 golden
    assert "Faithfulness is the priority" in rendered
    assert "[eu-ai-act::4]\nProviders shall ensure compliance." in rendered
    assert "QUESTION: What must providers do?" in rendered
    assert rendered != _V1_GOLDEN_PROMPT


def test_prompt_version_is_v2() -> None:
    assert PROMPT_VERSION == "cite-or-refuse/v2"


def test_load_prompt_returns_template_with_placeholders() -> None:
    template = load_prompt("cite-or-refuse.v2")
    assert "{refusal}" in template and "{chunks}" in template and "{question}" in template
    assert not template.endswith("\n")  # the single trailing newline is stripped on load


def test_load_prompt_unknown_id_fails_fast() -> None:
    with pytest.raises(ValueError, match="unknown prompt id"):
        load_prompt("does-not-exist")
