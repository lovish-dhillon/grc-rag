# EVAL-003 — `ANTHROPIC_API_KEY` secret is empty in CI

**Priority:** P1 · **Type:** config · **Opened:** 2026-07-08

## Symptom
In the `judge-refresh` job log the environment shows the key unset:

```
env:
  ANTHROPIC_API_KEY:
```

`src/grc_rag/llm.py` reads `ANTHROPIC_API_KEY` at call time and "a missing key raises immediately". So even
once the generator connection is fixed (EVAL-002), the Anthropic Haiku judge call would fail auth.

## Root cause
The workflow references `secrets.ANTHROPIC_API_KEY`:

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

…but the repository has no `ANTHROPIC_API_KEY` secret set (or it's empty), so it resolves to blank.

## Fix
Set the repo secret (only needed if keeping a CI-side judge — paths A/C in EVAL-002):

```bash
gh secret set ANTHROPIC_API_KEY --repo lovish-dhillon/grc-rag   # paste the key when prompted
# verify it now appears (value is masked):
gh secret list --repo lovish-dhillon/grc-rag
```

Use a scoped/limited key with a small budget — the judge is a low-volume nightly call. If EVAL-002 path **B**
(local refresh) is chosen, this secret is not needed in CI at all and this ticket closes as "won't do (local
only)".

## Acceptance criteria
- [ ] Either `gh secret list` shows `ANTHROPIC_API_KEY`, **or** EVAL-002 path B is adopted and CI no longer
      references the secret.
- [ ] A `judge-refresh` run reaches the judge step without an auth error.

## Security note
Never commit the key or echo it in logs. The workflow already scopes it to the `judge-refresh` job only, which
is correct — keep it out of the keyless `gate` job.

---
## Resolution (2026-07-11) — not needed for a green `main` (EVAL-002 Path B)

With **Path B** (ADR-0018), the paid judge no longer runs on a schedule, so **no CI secret is
needed to green the badge.** The keyless `gate` job (Tier-1 + scorecard freshness) has never
referenced the key.

- The secret is now consumed **only** by the opt-in `workflow_dispatch` `judge-refresh` job, which
  stays correctly scoped (`env` on that job only, not the keyless `gate`).
- Setting the repo secret is **deferred to the repo owner** — it is a live personal API key, so
  auto-setting it into GitHub Actions is intentionally left as an explicit human action. Set it
  only if you want to use the manual cloud refresh path:
  `gh secret set ANTHROPIC_API_KEY --repo lovish-dhillon/grc-rag`.
- The local refresh (the supported path) reads the key from the gitignored `.env.local`.

Status: **resolved — won't-do in CI for the common path; secret optional for the manual dispatch.**
