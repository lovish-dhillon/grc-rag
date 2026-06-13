# ADR-0011 — Two-tier CI gate with a committed scorecard

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

"Trust is measured" only counts if a quality drop fails the build. The obstacle is cost and
secrets: the faithfulness judge needs an Anthropic key and costs money, so running it on
every push would burn budget and expose a secret on forked PRs. Recall, by contrast, is
deterministic and free.

## Decision

Split the gate by how each metric is produced.

- **`--tier1`** computes recall@10 over the committed index and gates at 0.85. Keyless,
  deterministic, runs on every PR and push.
- **`--judge`** runs the paid judge, writes a committed `scorecard.json` (faithfulness, date,
  judge model, prompt version, and a SHA-256 of the golden set), and runs only on a nightly
  schedule or manual dispatch.
- **`--check-scorecard`** gates each PR on the committed scorecard's faithfulness (≥ 0.90)
  and on its freshness, failing if the card is older than the allowed age or was measured
  against a different golden set. Keyless.

The gate decision (`evaluate_gate`) is a pure function of `(EvalReport, GateThresholds)`, so
it is fully unit-tested without a model. A seeded regression fixture, routed in via the
`GRC_RAG_SEED_REGRESSION` environment variable, collapses recall and turns the gate red on
demand, reversibly.

## Alternatives considered

- **Run the judge on every push.** Rejected: cost and secret exposure, especially on forks.
- **Skip the freshness check.** Rejected: a stale scorecard would let a PR pass on a number
  from a pipeline that no longer exists. A stale card is itself a gate failure.

## Consequences

- Honest tradeoff, stated plainly: a PR is gated on the last committed faithfulness score, not
  a fresh one. The staleness guard and nightly refresh bound how old it can be.
- The keyless tiers make the common case fast and safe; the paid run is controlled.
- The seeded-regression fixture is the reversible proof that the gate actually bites.
