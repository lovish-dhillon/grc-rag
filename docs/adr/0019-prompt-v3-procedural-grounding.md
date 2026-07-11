# ADR-0019 — Prompt v3: procedural per-sentence grounding

- **Status:** Accepted
- **Date:** 2026-07-11
- **Relates to:** [ADR-0012](./0012-prompt-versioning-tradeoff.md) (v2 accepted with a known
  faithfulness↔relevancy tradeoff), [ADR-0008](./0008-claim-by-claim-judge.md) (the judge that
  measures this).

## Context

The nightly scorecard had gone stale (EVAL-001). Refreshing it on the current generator stack
(Ollama 0.24 + `qwen2.5:7b` + the pinned Haiku judge) surfaced a real regression: faithfulness
measured a **reproducible 0.879–0.891**, below the 0.90 gate. The committed 0.905 was from an
earlier (June) Ollama build that decoded slightly differently — the metric had always sat on a
knife's edge (ADR-0012).

A per-claim diagnostic (the judge's own reasons, item by item) showed the shortfall was **real,
not judge noise**. Two failure modes dominated the 15 unsupported claims across 9 items:

1. **Elaboration beyond the cited chunks** — the 7B model added real-sounding regulatory detail
   (article numbers, deletion/retention rules, monetary thresholds) that its cited chunk never
   stated, drawn from parametric memory.
2. **Mis-citation and paraphrase drift** — asserting things the *cited* chunk did not back
   (e.g. attributing an importer's duty to the provider), and changing legal terms of art
   (writing "immediately" where the source says "without undue delay").

v2 already forbade these in prose; the 7B model did not reliably obey a prose prohibition.

## Decision

Introduce **`cite-or-refuse/v3`** — a *procedural* rewrite that turns the prohibitions into a
per-sentence construction recipe, and re-pin the live generator to it. `v1`/`v2` stay on disk as
frozen history; the version id is stamped on every `Answer` and on the scorecard.

v3's load-bearing changes:

- **Write each sentence from the ONE chunk that literally states it**, in that chunk's own words;
  if no single chunk states a fact, **omit that sentence** — do not supply it from knowledge.
- **Keep the standard's exact terms** (no "immediately" for "without undue delay"; no "operators"
  for "providers"; no re-attributing duties across actors).
- **Match scope exactly** — do not split a listed phrase ("recruitment or selection") into
  specific purposes the chunk never names, and do not merge two chunks into a claim neither makes.
- **Omit, don't refuse.** A first strict draft cut faithfulness's *opposite* corner — it made the
  model refuse 8/36 answerable in-corpus questions, and a refusal is vacuously faithful, so that
  would have *inflated* the metric while gutting usefulness. v3 was softened to bias toward writing
  grounded partial answers and to refuse only when no chunk is on-topic at all.

## Alternatives considered

- **Recalibrate the gate to the measured ~0.88.** Rejected: lowering the bar so a failing run
  passes reads as goalpost-moving on a project whose thesis is "the gate bites."
- **Accept the badge red at 0.90.** Honest, but a real generation fix was available and is the
  better outcome.
- **Swap in a stronger (cloud) generator.** Rejected here: it breaks the local-first, keyless
  generation stance ([ADR-0007]); revisit only if prompt work stops being enough.
- **First (strict) v3 draft.** Rejected: it hit 0.953 faithfulness *by over-refusing* (8 false
  in-corpus refusals, flat 0.722 relevancy) — a gamed number, not a better system.

## Consequences

- **Both trust axes improved on the same measurement** (36 judged in-corpus items, 0 judge parse
  errors, golden set unchanged): faithfulness **0.879→0.924** (clears the 0.90 gate with margin)
  and answer relevancy **0.722→0.806**. This is the improvement ADR-0012 hoped a later prompt
  could reach — v2 had traded relevancy *for* faithfulness; v3 lifts both. Recall@10 is unchanged
  (0.889 — deterministic IR, independent of the prompt) and out-of-corpus refusal accuracy stays
  5/5.
- **A small honest cost:** v3 refuses ~4/36 in-corpus questions it cannot ground in the retrieved
  chunks (v2 answered them, sometimes by mis-citing). Under cite-or-refuse that is the *correct*
  behaviour — refuse rather than fabricate a citation — and it surfaces where retrieval, not the
  prompt, is the real limit.
- **The gate stays honest.** The number moved because the *system* got better, verified per-claim,
  not because the bar moved.
