# Tickets — eval-gate CI is red on `main`

Opened 2026-07-08 after GitHub emailed a failed `eval-gate` run (nightly `schedule`, commit `59e8651`).
The public repo's CI badge is red, which is a bad look for a project whose thesis is "a CI gate so
quality can't silently regress." This is a **cascade from one root cause**, not five independent bugs.

## The incident in one paragraph

The nightly `judge-refresh` job (paid Anthropic judge + local Ollama generator) has failed every night
since at least 2026-07-04, so it has never committed a fresh `data/eval/scorecard.json`. The committed
scorecard is dated **2026-06-13** — now **25 days old**. The keyless `gate` job that runs on every push
checks `--check-scorecard --max-age-days 14` and fails `scorecard_fresh 0 vs 1` once the scorecard passes
14 days. So **every push to `main` is now red**, even though Tier‑1 `recall@10` still passes.

## Fix order

| # | Ticket | Priority | Effect |
|---|--------|----------|--------|
| [EVAL-001](EVAL-001-scorecard-stale-main-red.md) | Refresh the scorecard → green the badge now | **P0** | Immediate: unblocks `main` for 14 days |
| [EVAL-002](EVAL-002-judge-refresh-ollama-connection.md) | `judge-refresh` fails at generator (Ollama httpx connection) | **P1** | Root cause: makes the nightly refresh actually run |
| [EVAL-003](EVAL-003-anthropic-api-key-secret.md) | `ANTHROPIC_API_KEY` secret is empty in CI | **P1** | Judge can't auth even if generation succeeds |
| [EVAL-004](EVAL-004-workflow-write-permission.md) | `judge-refresh` commit/push needs `contents: write` | **P2** | The step it never reached will 403 next |
| [EVAL-005](EVAL-005-node20-actions-bump.md) | Node 20 deprecation warnings on actions | **P3** | Cosmetic; forced-migration risk later |

**Do EVAL-001 first** (green today), then EVAL-002/003/004 together (make the nightly refresh reliable so
it never goes stale again), then EVAL-005 when convenient.

> **Status (2026-07-11): all of EVAL-001…005 are RESOLVED** (see each ticket's Resolution section).
> The badge is green on `main`. EVAL-001 turned out to hide a real faithfulness regression, fixed with
> prompt **v3** (faithfulness 0.879→0.924, relevancy 0.722→0.806) — see ADR-0018 / ADR-0019, not a
> lowered gate. The follow-up work that fix surfaced is tracked below.

## Follow-up backlog (opened 2026-07-11 from the EVAL-001 fix)

Not part of the incident — new work discovered while fixing it. Ordered by priority.

| # | Ticket | Priority | What |
|---|--------|----------|------|
| [EVAL-006](EVAL-006-eval-deploy-k-skew.md) | Eval measures at k=10 but deployed API/CLI generate at k=6 | **P1** | Scorecard is optimistic vs the live system; reconcile the retrieval `k`. |
| [EVAL-007](EVAL-007-retrieval-grounding-gap-false-refusals.md) | Retrieval misses the grounding clause for some in-corpus questions | **P2** | v3 correctly refuses a few answerable questions → retrieval recall is the next limit. |
| [EVAL-008](EVAL-008-faithfulness-relevancy-judge-coupling.md) | Faithfulness mean drops an item when the *relevancy* judge errors | **P2** | Coupled `try/except` in `run_eval`; decouple so one judge's failure can't bias the other. |
| [EVAL-009](EVAL-009-judge-nondeterminism-gate-margin.md) | Characterize & guard faithfulness nondeterminism near the 0.90 gate | **P3** | ~1-claim run-to-run swing; run `judge_stability`, set a principled margin. |
| [EVAL-010](EVAL-010-verify-or-retire-manual-judge-refresh.md) | Verify or retire the manual `judge-refresh` CI path | **P3** | Hardened but never run green; prove it once or delete it. |
| [EVAL-011](EVAL-011-relocated-venv-broken-shebangs.md) | Relocated `.venv` has broken console-script shebangs | **P4** | `pip`/`uvicorn` wrappers point at the old moved path; recreate the venv. |

_These ticket files are kept **local and private** — not committed to the public repo._

## Design question raised (decide, don't just patch)

Running a 7B generator on a free CPU GitHub runner is inherently slow and flaky (EVAL-002). Options to weigh
in EVAL-002: (a) harden the CI Ollama step, (b) drop CI refresh and rely on **local refresh + commit** with a
longer `--max-age-days`, or (c) move `judge-refresh` to a self-hosted runner. Pick one deliberately and
record it as an ADR under `docs/adr/`.
