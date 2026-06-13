# ADR-0009 — Golden set keyed on clause labels, adversarially verified

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

An evaluation metric is only as honest as the answer key it runs against. A metric scored
against sloppy ground truth is theatre — an easy way to post a near-1.0 number that means
nothing. The golden set has to be clean, and it has to survive the index changing underneath
it.

## Decision

A frozen `GoldenItem` schema with a validating, fail-fast loader. Relevance is keyed on the
stable `clause_label` ("EU AI Act — Article 3"), not the ephemeral `chunk_id`. Out-of-corpus
items are first-class (a `kind` field, zero expected clauses, scored by whether the system
refused). The set was drafted per clause and then put through a strict adversarial verifier
that audited each question against only its cited clause text.

The current set is 41 items: 36 in-corpus across 20 clauses, plus 5 out-of-corpus.

## Alternatives considered

- **Keying relevance on chunk_id.** Rejected: chunk ids shift on every re-chunk, so the
  answer key would rot whenever the window size or structure logic changes. Clause labels are
  stable.
- **Unverified drafted questions.** Rejected: the adversarial pass caught questions that
  simply restated their own clause's wording, which would have inflated retrieval scores.

## Consequences

- The answer key survives re-chunking, so retrieval changes can be measured without
  re-labelling.
- A malformed golden line raises with its line number on load, never silently skipped.
- The set's SHA-256 is recorded in the scorecard, so the gate can tell when a score was
  measured against a different set ([ADR-0011](./0011-two-tier-ci-gate.md)).
