# EVAL-010 — Verify or retire the manual `judge-refresh` CI path

**Priority:** P3 · **Type:** ci / cleanup · **Opened:** 2026-07-11
(loose end from the EVAL-002 Path-B decision)

## Context
EVAL-002 dropped the nightly `schedule` and kept `judge-refresh` as a **hardened,
`workflow_dispatch`-only** escape hatch (Ollama readiness poll, model warm-up,
`GRC_RAG_OLLAMA_TIMEOUT`, `contents: write`). It is correct on paper and no longer reds `main`
(it `skip`s on PR/push — confirmed on PR #1), but it has **never actually run green in CI**:

- It needs the `ANTHROPIC_API_KEY` repo secret set (EVAL-003 left this deferred to the owner).
- It still runs a 7B generator on a free CPU runner, which is exactly the slow/flaky path Path B
  chose to avoid — the manual trigger inherits that risk.

So there is a hardened-but-unexercised job in the workflow. Either prove it works once, or delete
it to keep the workflow honest (local refresh remains the supported path per ADR-0018).

## Fix — decide and act
- **Verify:** set the scoped secret, dispatch `judge-refresh` once, confirm it reaches the judge,
  writes a fresh scorecard, and commits/pushes (or cleanly no-ops). If it passes, it's a real
  escape hatch; document the one-time proof.
- **Retire:** if CPU-runner generation is too slow/flaky to be worth it, delete the `judge-refresh`
  job (and the secret/`contents: write` it needs). CI becomes purely the keyless `gate`; the
  scorecard is refreshed locally only. This is the simplest end state and fully matches ADR-0018.

Recommendation: **retire** unless an automated cloud refresh becomes a hard requirement — it
removes the paid/secret/push surface entirely.

## Acceptance criteria
- [ ] Either a `judge-refresh` dispatch is shown green end-to-end (secret set, scorecard committed),
      **or** the job is removed and the workflow/docs updated to say refresh is local-only.
- [ ] EVAL-003 (secret) and EVAL-004 (`contents: write`) are closed accordingly.

## Related
[[EVAL-002]] [[EVAL-003]] [[EVAL-004]] — this closes the trio's remaining ambiguity.
