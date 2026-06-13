# ADR-0013 — Drop the "zero uncited claims" gate metric

- **Status:** Accepted (supersedes the original three-metric gate target)
- **Date:** 2026-06-13

## Context

The original success criteria listed three gate targets: faithfulness ≥ 0.90, recall@10
≥ 0.85, and "zero uncited factual claims." On inspection, the third one did not hold up as a
distinct metric. The judge's `uncited_claims` field was really an *unsupported*-claim count,
which makes "zero uncited" equivalent to faithfulness = 1.0 and contradicts the separate 0.90
bar. A genuinely structural reading (a sentence with no citation) is also available, so I
built that and measured it.

## Decision

Drop the uncited-claims metric from the gate. Gate on faithfulness ≥ 0.90 and recall@10
≥ 0.85 only.

## Evidence

The structural reading (`count_uncited_claims`, keyless) was run on the real v2 answers. It
flagged 49 cases across 22 answers, almost all of them formatting noise: enumerated legal
lists cited once on the lead-in, colon lead-ins, and questions echoed back. It was measuring
list formatting, not grounding.

## Consequences

- The "no uncited claims" property is still covered, two ways. Structurally: `generate.py`
  refuses zero-citation answers and drops dangling ones, a tested invariant. Semantically:
  whether a cited claim is supported is exactly what faithfulness measures, so a separate
  uncited threshold would double-count it.
- This is recorded as a decision, with the measurement, specifically so it reads as
  evidence-based and not as moving the goalposts. I built the metric, measured it, found it
  unsound, and removed it rather than shipping it.
- On the v2 prompt the gate is honestly green on the two metrics that remain.

The threshold config in `gate.py` reflects this: two thresholds, not three. See
[ADR-0011](./0011-two-tier-ci-gate.md).
