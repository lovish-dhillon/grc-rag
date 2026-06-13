# ADR-0006 — Cross-encoder re-rank and calibrated refusal threshold

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

Phase 1 refused only reactively, when the model volunteered the refusal sentinel or cited
nothing. But a model handed weak, barely-relevant chunks will still write a confident,
correctly-formatted, cited answer. That is false assurance, and the cite-or-refuse invariant
([ADR-0001](./0001-cite-or-refuse-invariant.md)) needs a structural decision point that
refuses on weak support before the model ever runs.

## Decision

Two steps. First, re-rank the fused candidates with a cross-encoder
(`ms-marco-MiniLM-L-6-v2`) that scores query and chunk jointly rather than independently.
Second, read the top re-ranked score and refuse before generation when it is below a
calibrated `SupportThreshold`. The threshold is fitted from a probe set: it sits in the gap
between the in-corpus and out-of-corpus top-1 score populations, and calibration fails closed
if those populations overlap.

## Alternatives considered

- **Threshold on the RRF score directly.** Rejected because it does not work: on RRF scores
  the in-corpus minimum (0.0311) sits below the out-of-corpus maximum (0.0328), so the
  populations overlap and calibration correctly refuses to fit. Only the cross-encoder's
  score separates the two. This is the concrete reason re-rank precedes the gate.
- **A hand-picked constant threshold.** Rejected: arbitrary and corpus-specific. Calibration
  ties the number to measured evidence.

## Consequences

- On the cross-encoder scores the gap is wide (in-corpus around 4–10, out-of-corpus around
  −3 to −9), which lands the threshold at 0.3325 with clean separation: out-of-corpus refuses
  5 of 5, in-corpus passes 5 of 5.
- The gate only ever adds refusals; the Phase-1 citation checks still apply afterwards.
- It is a near-zero-cost structural proxy for the Phase-3 judge, and it saves the generation
  call entirely on a refusal.
- The threshold is persisted to `support-threshold.json` and applied by the CLI and API.
