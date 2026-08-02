# EVAL-004 — `judge-refresh` commit/push will 403 without `contents: write`

**Priority:** P2 (latent — blocks the step EVAL-002/003 will unlock) · **Type:** config · **Opened:** 2026-07-08

## Symptom
Not yet observed, because `judge-refresh` fails earlier (EVAL-002). But once the judge step passes, the final
step will run:

```yaml
- name: Commit the refreshed scorecard
  run: |
    git config user.name  "eval-gate"
    git config user.email "eval-gate@users.noreply.github.com"
    git add data/eval/scorecard.json
    git commit -m "chore: refresh eval scorecard" || echo "no change"
    git push
```

With the default `GITHUB_TOKEN` set to read-only (the default on many repos since 2023), `git push` returns
`403`/`denied to github-actions[bot]` and reds the job.

## Fix
Grant write scope to the job (preferred — least privilege, not the whole workflow):

```yaml
  judge-refresh:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    permissions:
      contents: write        # allow the scorecard commit/push
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Also confirm repo → Settings → Actions → "Workflow permissions" is not forcing read-only globally. Harden the
push step so a no-op doesn't error:

```bash
git diff --quiet && echo "scorecard unchanged" || { git commit -m "chore(eval): refresh scorecard"; git push; }
```

## Acceptance criteria
- [ ] `permissions: contents: write` is set on `judge-refresh` (or the workflow).
- [ ] A successful `judge-refresh` commits the fresh scorecard back to `main` (or cleanly no-ops when unchanged).

## Note
Not needed if EVAL-002 path **B** (local refresh + manual commit) is adopted — the CI job wouldn't push.

---
## Resolution (2026-07-11)

Applied the least-privilege fix anyway, so the retained **manual** `workflow_dispatch`
`judge-refresh` job can commit cleanly if someone dispatches it:

- Added `permissions: contents: write` to the `judge-refresh` job (not the whole workflow).
- Hardened the push step to no-op when unchanged instead of erroring:
  `git diff --cached --quiet && echo "scorecard unchanged" || { git commit …; git push; }`.

Not on the critical path for a green `main` under Path B (the common path never pushes from CI).

Status: **done.**
