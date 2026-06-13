"""The LLM-as-judge — is the answer actually supported by what it cited?

This is the module that earns the project's trust claim, and it is built as the deliberate
*inverse* of a common anti-pattern: the **circular faithfulness metric**, where the "answer" is
the retrieved context copied back and "faithfulness" is *token overlap* between the answer and
that same context — so the score is ≈1.0 by construction and measures nothing.

The judge here does the opposite. It never compares strings. It decomposes the answer into
atomic factual **claims** and, claim by claim, asks a real language model whether the **cited
chunks entail that claim**. Token similarity is explicitly forbidden in the prompt and there is
no overlap code path in this module — a claim that reuses a chunk's words but asserts something
the chunk never states is scored *unsupported*. ``faithfulness`` is the supported fraction;
``uncited_claims`` is the number a careful reader could not ground in the cited sources (under
cite-or-refuse, an ungroundable claim is an uncited one — a factual assertion with no backing in
the sources it points at). That integer is what the CI gate's "0 uncited claims" bar reads.

The judge holds an :class:`~grc_rag.generate.LLMClient` — the same seam the generator uses — so
it is driven by a deterministic stub in unit tests (no network, no key) and by the cheapest
adequate cloud model (:class:`~grc_rag.llm.AnthropicClient`, temperature 0) in a real run. The
load-bearing operational risk is **stability**: a judge whose verdicts flap run-to-run can't
arbitrate a build. :func:`judge_stability` measures that directly — repeated runs at
temperature 0, with the score spread and the per-claim agreement reported, not assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from grc_rag.generate import Answer, LLMClient
from grc_rag.prompts import load_prompt
from grc_rag.retrieve import RetrievedChunk

JUDGE_FAITHFULNESS_PROMPT_VERSION = "judge-faithfulness/v1"
JUDGE_RELEVANCY_PROMPT_VERSION = "judge-relevancy/v1"

_FAITHFULNESS_PROMPT_ID = "judge-faithfulness.v1"
_RELEVANCY_PROMPT_ID = "judge-relevancy.v1"


@dataclass(frozen=True)
class ClaimVerdict:
    """One atomic claim extracted from an answer, and whether the cited chunks support it."""

    claim: str
    supported: bool
    reason: str


@dataclass(frozen=True)
class FaithfulnessVerdict:
    """The faithfulness judgement of a single answer. Immutable.

    ``faithfulness`` is ``supported_claims / total_claims``. An answer with **no** factual
    claims (e.g. a refusal) is vacuously faithful → ``1.0`` with ``unsupported_claims == 0``.
    ``unsupported_claims`` counts the claims the cited chunks do **not** entail — this is the
    *semantic* shortfall already reflected in ``faithfulness``. It is **not** the gate's
    "uncited claims" metric: an *uncited* claim is one with no citation at all (a structural
    property, :func:`grc_rag.generate.count_uncited_claims`), which is a different thing from a
    cited-but-unsupported one.
    """

    claims: tuple[ClaimVerdict, ...]
    faithfulness: float
    unsupported_claims: int


@dataclass(frozen=True)
class StabilityReport:
    """How steady the judge is across repeated runs at temperature 0.

    ``max_score_spread`` is ``max(faithfulness) - min(faithfulness)`` over the runs (0.0 = the
    score never moved). ``verdict_agreement`` is the fraction of distinct claims that appeared
    in **every** run with the **same** supported label (1.0 = unanimous). Both near their ideal
    means the judge is a trustworthy arbiter; a low value is a finding to log, not to hide.
    """

    runs: int
    max_score_spread: float
    verdict_agreement: float


def _chunk_blocks(chunks: Sequence[RetrievedChunk]) -> str:
    """Render the cited chunks the way the generator does — id-labelled — so the judge sees
    exactly the sources the answer was allowed to cite."""
    return "\n\n".join(f"[{rc.chunk.chunk_id}]\n{rc.chunk.text}" for rc in chunks)


def _extract_json_object(text: str) -> dict:
    """Parse the single JSON object a judge prompt asks for, failing fast on anything else.

    Tolerates a leading/trailing code fence (```json … ```) but **not** free-form prose or a
    truncated object — a malformed verdict raises ``ValueError`` rather than being guessed at,
    because a judge we can't parse is a judge we can't trust.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # drop the opening fence line and the trailing fence
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
    stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise ValueError(f"judge returned non-JSON output: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"judge output must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _parse_faithfulness(raw: dict) -> FaithfulnessVerdict:
    """Validate the judge's faithfulness JSON into a :class:`FaithfulnessVerdict`. Fail-fast."""
    claims_raw = raw.get("claims")
    if not isinstance(claims_raw, list):
        raise ValueError("judge faithfulness output must have a 'claims' list")

    claims: list[ClaimVerdict] = []
    for entry in claims_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"each claim must be an object, got {type(entry).__name__}")
        claim = entry.get("claim")
        supported = entry.get("supported")
        reason = entry.get("reason", "")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("each claim must carry a non-empty 'claim' string")
        if not isinstance(supported, bool):
            raise ValueError("each claim's 'supported' must be a boolean")
        if not isinstance(reason, str):
            raise ValueError("each claim's 'reason' must be a string")
        claims.append(ClaimVerdict(claim=claim, supported=supported, reason=reason))

    total = len(claims)
    supported_count = sum(1 for c in claims if c.supported)
    # No claims → vacuously faithful (a refusal asserts nothing to be unfaithful about).
    faithfulness = 1.0 if total == 0 else supported_count / total
    unsupported = total - supported_count
    return FaithfulnessVerdict(
        claims=tuple(claims), faithfulness=faithfulness, unsupported_claims=unsupported
    )


def judge_faithfulness(
    answer: Answer,
    cited_chunks: Sequence[RetrievedChunk],
    *,
    client: LLMClient,
) -> FaithfulnessVerdict:
    """Score ``answer``'s faithfulness against the chunks it was allowed to cite, claim by claim.

    Builds the versioned judge prompt, calls the model behind ``client``, and parses a strict
    JSON verdict (fail-fast on malformed output). Never compares tokens — entailment only.
    """
    # The prompt template carries a literal JSON example ({"claims": ...}), so str.format would
    # collide with those braces — substitute the placeholders directly instead.
    prompt = (
        load_prompt(_FAITHFULNESS_PROMPT_ID)
        .replace("{chunks}", _chunk_blocks(cited_chunks))
        .replace("{answer}", answer.text)
    )
    return _parse_faithfulness(_extract_json_object(client.complete(prompt)))


def judge_answer_relevancy(question: str, answer: Answer, *, client: LLMClient) -> float:
    """1.0 if the answer actually responds to ``question``, else 0.0.

    Responsiveness, not correctness (faithfulness covers that): a faithful answer to the *wrong*
    question still fails the user. Raises ``ValueError`` on an empty question or a malformed
    judge verdict.
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")
    prompt = (
        load_prompt(_RELEVANCY_PROMPT_ID)
        .replace("{question}", question)
        .replace("{answer}", answer.text)
    )
    raw = _extract_json_object(client.complete(prompt))
    relevant = raw.get("relevant")
    if not isinstance(relevant, bool):
        raise ValueError("judge relevancy output must have a boolean 'relevant'")
    return 1.0 if relevant else 0.0


def judge_stability(
    answer: Answer,
    cited_chunks: Sequence[RetrievedChunk],
    *,
    client: LLMClient,
    runs: int = 3,
) -> StabilityReport:
    """Run the faithfulness judge ``runs`` times and report how steady it was.

    ``max_score_spread`` is the range of the faithfulness score across runs; ``verdict_agreement``
    is the fraction of distinct claims that appeared in every run with the same supported label
    (1.0 when there are no claims). Raises ``ValueError`` on ``runs < 1``.
    """
    if runs < 1:
        raise ValueError(f"runs must be >= 1, got {runs}")

    verdicts = [judge_faithfulness(answer, cited_chunks, client=client) for _ in range(runs)]
    scores = [v.faithfulness for v in verdicts]
    max_score_spread = max(scores) - min(scores)

    # A claim "agrees" iff it appears in every run with one consistent supported value.
    per_run_labels: list[dict[str, bool]] = [
        {c.claim: c.supported for c in v.claims} for v in verdicts
    ]
    distinct_claims = {claim for labels in per_run_labels for claim in labels}
    if not distinct_claims:
        verdict_agreement = 1.0
    else:
        agreed = 0
        for claim in distinct_claims:
            values = [labels.get(claim) for labels in per_run_labels]
            if all(v is not None for v in values) and len(set(values)) == 1:
                agreed += 1
        verdict_agreement = agreed / len(distinct_claims)

    return StabilityReport(
        runs=runs, max_score_spread=max_score_spread, verdict_agreement=verdict_agreement
    )
