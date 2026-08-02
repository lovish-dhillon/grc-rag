# EVAL-009 — Characterize & guard faithfulness nondeterminism near the 0.90 gate

**Priority:** P3 · **Type:** reliability / eval · **Opened:** 2026-07-11
(surfaced across repeated judge runs during the EVAL-001 fix)

## Symptom
Faithfulness is not perfectly reproducible run-to-run, and the gate reads a single committed number
against a hard threshold. Observed on the current stack:

- v2 measured `0.890741` **twice, identically** (deterministic that day).
- v3 measured `0.914352` (probe) then `0.923611` (official) — a ~0.009 swing, ≈ one claim across
  36 items.

Both v3 values clear 0.90 comfortably, but the swing shows the number can move ~1 claim between
runs with no code change. A future refresh that lands on the low side of the band could re-red the
gate near the threshold.

## Root cause
- The Ollama generator (temperature 0, greedy) is *mostly* deterministic but not bit-guaranteed on
  Metal (non-associative float reductions) across builds/runs.
- The Anthropic judge (temperature 0) is also only approximately deterministic; a borderline claim
  can flip supported↔unsupported between runs.

The judge module already ships `judge_stability` (`src/grc_rag/judge.py`) to measure exactly this,
but it is **not run over the golden set** as part of a refresh.

## Fix — measure the band, then decide the guard
- Run `judge_stability` (N runs, temp 0) over the golden set to quantify `max_score_spread` and
  per-claim `verdict_agreement`; record the observed faithfulness band.
- Decide a principled guard given the band, e.g.:
  - keep the 0.90 gate but require the committed scorecard to sit a documented margin above it, or
  - average faithfulness over N judge runs when writing the scorecard (more stable committed
    number), or
  - pin/relax as the data warrants — **without** lowering the bar to pass (that's out of scope; see
    ADR-0019's rejected "recalibrate" option).

## Acceptance criteria
- [ ] The faithfulness band (spread + verdict agreement) is measured over the golden set and
      recorded (docs or an ADR).
- [ ] A deliberate, documented policy for the margin/averaging is in place so a near-threshold
      refresh can't flap red on noise alone.

## Related
[[EVAL-001]] (near-threshold refresh), [[EVAL-008]] (denominator honesty affects the mean).
