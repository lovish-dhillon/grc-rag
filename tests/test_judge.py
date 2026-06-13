"""Tests for the LLM-as-judge.

The judge holds an ``LLMClient`` seam, so every test drives it with a deterministic stub
returning canned JSON — no network, no key, no flap. This is also where we pin the
anti-pattern guard: faithfulness is whatever the per-claim verdict says, never token overlap.
"""

from __future__ import annotations

import dataclasses
import json
import os

import pytest

from grc_rag.chunking import Chunk
from grc_rag.generate import PROMPT_VERSION, Answer
from grc_rag.judge import (
    ClaimVerdict,
    FaithfulnessVerdict,
    judge_answer_relevancy,
    judge_faithfulness,
    judge_stability,
)
from grc_rag.retrieve import RetrievedChunk


class SequenceClient:
    """An ``LLMClient`` stub that returns a fixed response, or cycles through a list of them
    (so a stability test can make the judge 'flap')."""

    def __init__(self, responses: str | list[str]) -> None:
        self._responses = [responses] if isinstance(responses, str) else list(responses)
        self.calls = 0

    def complete(self, prompt: str) -> str:
        response = self._responses[self.calls % len(self._responses)]
        self.calls += 1
        return response


def _answer(text: str = "Providers must do X [eu-ai-act::16].") -> Answer:
    return Answer(
        text=text, citations=("eu-ai-act::16",), refused=False, prompt_version=PROMPT_VERSION
    )


def _chunks() -> tuple[RetrievedChunk, ...]:
    chunk = Chunk(
        chunk_id="eu-ai-act::16",
        doc_id="eu-ai-act",
        text="Providers of high-risk AI systems shall do X.",
        token_count=8,
        start_token=0,
        clause_label="EU AI Act — Article 16",
    )
    return (RetrievedChunk(chunk=chunk, score=5.0),)


def _faith_json(claims: list[tuple[str, bool]]) -> str:
    return json.dumps({"claims": [{"claim": c, "supported": s, "reason": "r"} for c, s in claims]})


# --------------------------------------------------------------------------- #
# faithfulness scoring
# --------------------------------------------------------------------------- #
def test_faithfulness_partial() -> None:
    client = SequenceClient(_faith_json([("a", True), ("b", True), ("c", False)]))
    verdict = judge_faithfulness(_answer(), _chunks(), client=client)
    assert verdict.faithfulness == pytest.approx(2 / 3)
    assert verdict.unsupported_claims == 1
    assert len(verdict.claims) == 3


def test_faithfulness_all_supported() -> None:
    client = SequenceClient(_faith_json([("a", True), ("b", True)]))
    verdict = judge_faithfulness(_answer(), _chunks(), client=client)
    assert verdict.faithfulness == 1.0
    assert verdict.unsupported_claims == 0


def test_faithfulness_no_claims_is_vacuously_faithful() -> None:
    # A refusal asserts nothing → faithfulness 1.0, zero uncited claims (documented convention).
    client = SequenceClient(json.dumps({"claims": []}))
    verdict = judge_faithfulness(
        _answer(text="Not supported by the corpus."), _chunks(), client=client
    )
    assert verdict.faithfulness == 1.0
    assert verdict.unsupported_claims == 0
    assert verdict.claims == ()


def test_faithfulness_is_per_claim_not_token_overlap() -> None:
    """The anti-pattern guard. The answer echoes the chunk's exact words but the judge rules the
    claim UNSUPPORTED — and the harness must honour that verdict, not reward the overlap."""
    echo = _answer(text="Providers of high-risk AI systems shall do X [eu-ai-act::16].")
    client = SequenceClient(_faith_json([("Providers of high-risk AI systems shall do X", False)]))
    verdict = judge_faithfulness(echo, _chunks(), client=client)
    assert verdict.faithfulness == 0.0  # NOT 1.0, despite total lexical overlap
    assert verdict.unsupported_claims == 1


def test_faithfulness_tolerates_code_fence() -> None:
    fenced = "```json\n" + _faith_json([("a", True)]) + "\n```"
    verdict = judge_faithfulness(_answer(), _chunks(), client=SequenceClient(fenced))
    assert verdict.faithfulness == 1.0


def test_faithfulness_malformed_json_fails_fast() -> None:
    with pytest.raises(ValueError, match="non-JSON"):
        judge_faithfulness(_answer(), _chunks(), client=SequenceClient("not json at all"))


def test_faithfulness_missing_claims_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="claims"):
        judge_faithfulness(_answer(), _chunks(), client=SequenceClient(json.dumps({"foo": 1})))


def test_faithfulness_non_bool_supported_fails_fast() -> None:
    bad = json.dumps({"claims": [{"claim": "a", "supported": "yes", "reason": "r"}]})
    with pytest.raises(ValueError, match="supported"):
        judge_faithfulness(_answer(), _chunks(), client=SequenceClient(bad))


# --------------------------------------------------------------------------- #
# answer relevancy
# --------------------------------------------------------------------------- #
def test_relevancy_true() -> None:
    client = SequenceClient(json.dumps({"relevant": True, "reason": "addresses the question"}))
    assert judge_answer_relevancy("What must providers do?", _answer(), client=client) == 1.0


def test_relevancy_false() -> None:
    client = SequenceClient(json.dumps({"relevant": False, "reason": "off topic"}))
    assert judge_answer_relevancy("What must providers do?", _answer(), client=client) == 0.0


def test_relevancy_rejects_empty_question() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        judge_answer_relevancy("  ", _answer(), client=SequenceClient("{}"))


def test_relevancy_malformed_fails_fast() -> None:
    with pytest.raises(ValueError, match="relevant"):
        judge_answer_relevancy("q?", _answer(), client=SequenceClient(json.dumps({"x": 1})))


# --------------------------------------------------------------------------- #
# judge stability
# --------------------------------------------------------------------------- #
def test_stability_identical_runs() -> None:
    client = SequenceClient(_faith_json([("a", True), ("b", False)]))  # same response every call
    report = judge_stability(_answer(), _chunks(), client=client, runs=3)
    assert report.runs == 3
    assert report.max_score_spread == 0.0
    assert report.verdict_agreement == 1.0


def test_stability_flapping_runs() -> None:
    # Run 1: a,b both supported (1.0). Run 2: b flips to unsupported (0.5). Run 3: back to 1.0.
    responses = [
        _faith_json([("a", True), ("b", True)]),
        _faith_json([("a", True), ("b", False)]),
        _faith_json([("a", True), ("b", True)]),
    ]
    report = judge_stability(_answer(), _chunks(), client=SequenceClient(responses), runs=3)
    assert report.max_score_spread == pytest.approx(0.5)  # 1.0 - 0.5
    # 'a' agrees across all runs; 'b' does not → 1 of 2 distinct claims agree.
    assert report.verdict_agreement == pytest.approx(0.5)


def test_stability_rejects_zero_runs() -> None:
    with pytest.raises(ValueError, match="runs"):
        judge_stability(_answer(), _chunks(), client=SequenceClient("{}"), runs=0)


# --------------------------------------------------------------------------- #
# dataclasses + AnthropicClient fail-fast (no network)
# --------------------------------------------------------------------------- #
def test_verdict_dataclasses_frozen() -> None:
    cv = ClaimVerdict(claim="a", supported=True, reason="r")
    fv = FaithfulnessVerdict(claims=(cv,), faithfulness=1.0, unsupported_claims=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        fv.faithfulness = 0.0  # type: ignore[misc]


def test_anthropic_client_fails_fast_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from grc_rag.llm import AnthropicClient

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient().complete("anything")  # must not reach the network


@pytest.mark.skipif(
    "ANTHROPIC_API_KEY" not in os.environ,
    reason="needs a real key; set ANTHROPIC_API_KEY to run the live judge smoke test",
)
def test_anthropic_client_live_smoke() -> None:
    from grc_rag.llm import AnthropicClient

    out = AnthropicClient(max_tokens=16).complete("Reply with the single word: ok")
    assert isinstance(out, str) and out.strip()
