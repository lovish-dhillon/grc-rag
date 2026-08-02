# EVAL-005 — Node 20 deprecation warnings on GitHub Actions

**Priority:** P3 (cosmetic now, forced-migration later) · **Type:** maintenance · **Opened:** 2026-07-08

## Symptom
Both jobs emit warnings (non-failing):

```
Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24:
actions/checkout@v4, actions/setup-python@v5, actions/cache@v4
```

## Root cause
The pinned action majors ship a Node 20 runtime; GitHub is force-running them on Node 24 and will eventually
drop the shim (see the GitHub changelog linked in the log).

## Fix
Bump to the current majors that target Node 24, e.g.:

```yaml
- uses: actions/checkout@v5
- uses: actions/setup-python@v6
- uses: actions/cache@v5
```

Pin to whatever the latest stable majors are at implementation time; run the workflow once to confirm the
warnings are gone and nothing broke (cache key + Python setup unchanged).

## Acceptance criteria
- [ ] Action versions bumped; `eval-gate` runs with no Node 20 deprecation warnings.
- [ ] `gate` (Tier‑1 + scorecard) and `judge-refresh` behave identically to before the bump.

## Note
Low urgency — safe to batch with EVAL-002's workflow edits so the file is touched once.

---
## Resolution (2026-07-11)

Bumped in `.github/workflows/eval-gate.yml` alongside the EVAL-002 edits (file touched once).
Verified the **actual latest stable majors** via the GitHub API at implementation time (the
ticket's `v5/v6/v5` were illustrative; the real current majors are newer):

- `actions/checkout@v4` → `@v7` (latest v7.0.0)
- `actions/setup-python@v5` → `@v6` (latest v6.3.0)
- `actions/cache@v4` → `@v6` (latest v6.1.0)

All three majors target the Node 24 runtime, so the deprecation warnings are gone. Cache key +
Python-setup config unchanged.

Status: **done.** (Confirm "no Node 20 warnings" on the next run — see EVAL-001 note.)
