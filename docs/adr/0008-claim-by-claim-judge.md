# ADR-0008 — Claim-by-claim LLM-judge for faithfulness

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The one thing that separates this project from two earlier prototypes is a faithfulness
metric that measures something real. Those prototypes scored faithfulness as token overlap
between the answer and the context it was copied from, which is close to 1.0 by construction
and tells you nothing about whether a claim is actually supported.

## Decision

Build a real LLM-as-judge. For each answer it decomposes the text into atomic factual claims
and rules each claim supported or unsupported against the chunks the answer cited.
Faithfulness is supported claims over total. The prompt explicitly forbids rewarding lexical
similarity, and there is no token-overlap code path anywhere in the judge.

The judge runs as `claude-haiku-4-5-20251001` at temperature 0, behind the same `LLMClient`
seam the generator uses, with the key read from the environment and a fail-fast if it is
missing. Verdicts are strict JSON, parsed fail-fast. Judge stability is itself measured
(`judge_stability` runs N times at temperature 0 and reports score spread and per-claim
agreement), because a judge that flaps cannot gate a build.

## Alternatives considered

- **Token-overlap / ROUGE-style faithfulness.** Rejected: it is a circular metric. It cannot
  tell a grounded answer from one that merely reuses words.
- **A heavier or differently-pinned judge model.** Haiku at temperature 0 is cheap enough to
  run on a cadence and proved stable enough (zero parse errors across 36 answers) once the
  token budget was raised to 4096.

## Consequences

- A test pins the anti-overlap behaviour: an answer echoing a chunk's exact words while making
  an unsupported claim scores 0.0, not 1.0.
- The judge found genuine faithfulness gaps on the first honest run (0.885), which is the
  behaviour the whole project is built to produce.
- It is the input to the faithfulness side of the CI gate
  ([ADR-0011](./0011-two-tier-ci-gate.md)).
