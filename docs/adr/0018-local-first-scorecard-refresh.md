# ADR-0018 — Local-first scorecard refresh; no nightly CI judge

- **Status:** Accepted
- **Date:** 2026-07-11
- **Supersedes:** the nightly-`schedule` half of [ADR-0011](./0011-two-tier-ci-gate.md) (the two-tier
  gate and committed scorecard stand; only *how the scorecard is refreshed* changes).

## Context

ADR-0011 refreshed the committed faithfulness scorecard on a **nightly GitHub Actions schedule**:
the `judge-refresh` job installed Ollama, pulled `qwen2.5:7b`, ran the paid Anthropic judge over
the golden set, and committed the result. In practice that job failed every night from ~2026-07-04:

- A **7B generator on a free CPU runner** is slow and racy. The step started Ollama with `sleep 5`
  (not a readiness poll) and the per-call `OllamaClient` timeout (120s) was exceeded generating the
  full golden set on CPU — an `httpx`/`httpcore` connection error out of the generator (EVAL-002).
- The `ANTHROPIC_API_KEY` repo secret was empty, so even a healthy generator would fail the judge
  auth (EVAL-003).
- The final commit step would have `403`'d without `contents: write` (EVAL-004).

Because the nightly job never committed a fresh card, the committed scorecard went stale (dated
2026-06-13). The keyless per-PR `gate` checks `--check-scorecard --max-age-days 14`, so once the
card passed 14 days **every push to `main` went red** (`scorecard_fresh 0 vs 1`) — even though the
deterministic Tier-1 recall gate still passed. A project whose thesis is "a CI gate so quality
can't silently regress" was red for a stale *timestamp*, not a real regression (EVAL-001).

Three ways out were weighed (EVAL-002): **(A)** harden the CI Ollama step, **(B)** drop the CI
generation and refresh locally, **(C)** move the job to a self-hosted/GPU runner.

## Decision

Adopt **path B — local-first refresh — as the supported path**, and keep a hardened CI judge as a
manual escape hatch only.

- **Refresh locally.** The judge runs where Ollama + the key already work:
  `python -m grc_rag.gate --judge` regenerates `data/eval/scorecard.json` with today's date; commit
  it. This is the documented ritual (README + CLAUDE.md).
- **No nightly schedule.** The `judge-refresh` job is `workflow_dispatch`-only — it can never red
  `main` on a cadence again. When run manually it is hardened: an Ollama readiness poll (not
  `sleep 5`), a model warm-up, `contents: write` for the commit, and a longer generator timeout via
  the new `GRC_RAG_OLLAMA_TIMEOUT` env var (config, not code).
- **Widen the freshness window to 30 days.** The per-PR gate now checks `--max-age-days 30`, matching
  a realistic manual cadence. A 14-day window against a hand-refreshed card just re-reds at the
  boundary; 30 days gives margin while still failing on a genuinely abandoned card.

The keyless tiers are unchanged: Tier-1 recall@10 and the scorecard freshness/faithfulness check
still run on every PR/push with no key and no cost.

## Alternatives considered

- **(A) Harden the CI Ollama step and keep the nightly run.** Rejected as the *primary* path: it
  keeps a slow, flaky, paid, secret-bearing job on a cadence for a card that changes rarely. The
  hardening itself is worth keeping, so it lives on the manual dispatch path instead of nightly.
- **(C) Self-hosted / GPU runner.** Rejected for a portfolio project: real infra cost and
  maintenance to automate a refresh that a human does in minutes locally.
- **Keep `--max-age-days 14`.** Rejected: with manual refresh it guarantees a periodic red at the
  window edge; the freshness guard should bound staleness, not manufacture churn.

## Consequences

- **The badge reflects real quality, not a stale clock.** `main` goes green on a refreshed card and
  stays green for 30 days; a truly neglected card (>30 days) still reds the build, as intended.
- **Honest tradeoff, restated:** faithfulness is the last *locally* committed judge score, refreshed
  by a human ritual rather than a nightly bot. The freshness guard bounds how old it can be.
- **Smaller attack/cost surface:** no paid job, no `ANTHROPIC_API_KEY` in CI, and no bot push on the
  common path. The secret is needed only if someone deliberately dispatches the manual judge job.
- **EVAL-003 / EVAL-004** are no longer on the critical path: the secret and `contents: write` matter
  only for the opt-in manual dispatch, not for a green `main`.
