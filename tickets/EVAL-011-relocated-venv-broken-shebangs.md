# EVAL-011 — Relocated `.venv` has broken console-script shebangs (`pip`/`uvicorn` unusable directly)

**Priority:** P4 · **Type:** dev-environment · **Opened:** 2026-07-11
(hit while running the EVAL-001 refresh)

## Symptom
`.venv/bin/pip` fails:

```
.venv/bin/pip: line 2: /Users/lovish/Desktop/LOVISH.EA/Personal/Career + Business/portfolio/asset-stack/projects/grc-rag/.venv/bin/python: No such file or directory
```

The console-script shebangs point at an **old, moved project path** (`…/Personal/Career + Business/
portfolio/asset-stack/projects/grc-rag/…`), i.e. the repo was relocated to
`…/Projects/grc-rag` after the venv was created. `.venv/bin/python` itself works (it's a symlink),
but every generated wrapper (`pip`, `uvicorn`, `ruff`, `pytest`, …) has a hardcoded stale shebang.

## Impact
Cosmetic/workflow only — worked around this session by invoking modules directly:
`PYTHONPATH=src .venv/bin/python -m pip …` / `-m uvicorn …` / `-m pytest …`. But it's a papercut
for anyone following the README's `.venv/bin/pytest` / `uvicorn grc_rag.api:app` instructions.

## Fix
Recreate the virtualenv in place so the shebangs point at the current path:

```bash
cd Projects/grc-rag
rm -rf .venv
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

(Or `python -m venv --upgrade .venv` won't fix shebangs; a clean recreate is simplest.) The venv is
gitignored, so this is a local-only fix — no repo change needed, but worth noting in the README if
others clone.

## Acceptance criteria
- [ ] `.venv/bin/pytest`, `.venv/bin/ruff`, and `uvicorn grc_rag.api:app` run without the stale-path
      error, matching the README's documented commands.

## Notes
Purely local tooling; does not affect CI (which builds a fresh venv via `pip install -e ".[dev]"`)
or any committed code.
