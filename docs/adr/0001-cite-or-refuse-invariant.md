# ADR-0001 — Cite-or-refuse is a hard invariant

- **Status:** Accepted
- **Date:** 2026-06-11

## Context

The system answers regulatory questions for a compliance audience. In that setting the
failure mode that matters is not an unhelpful answer; it is a confident wrong one. A
fabricated but plausible article number gets pasted into a risk register or a board paper
and creates false assurance. Nobody goes back to check an answer that looked authoritative.

## Decision

Every answer must either cite the source clauses it relied on, inline, or refuse with the
fixed sentinel "Not supported by the corpus." Refusal is a legitimate, first-class output,
not an error. Faithfulness to this contract is a measured metric wired into CI, not a
property asserted in prose.

## Consequences

- The bar for answering is deliberately high, and the system will refuse questions a chattier
  assistant would attempt. That is the intended behaviour for this domain.
- The invariant has to be enforced structurally downstream (citation validation in
  `generate.py`, the threshold gate in `enforce.py`) rather than left to the model's
  goodwill. Those are separate records ([ADR-0006](./0006-rerank-threshold-enforcement.md),
  [ADR-0007](./0007-local-generator-citation-check.md)).
- It sets the whole evaluation agenda: faithfulness and refusal correctness become the
  numbers the build defends ([ADR-0008](./0008-claim-by-claim-judge.md),
  [ADR-0011](./0011-two-tier-ci-gate.md)).
