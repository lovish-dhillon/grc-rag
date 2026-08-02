# EVAL-002 — `judge-refresh` fails at the generator (Ollama httpx connection in CI)

**Priority:** P1 · **Type:** bug / CI-reliability · **Opened:** 2026-07-08

## Symptom
The scheduled `judge-refresh` job installs Ollama and pulls `qwen2.5:7b` successfully, then fails at
**"Run the judge and write the scorecard"** (`python -m grc_rag.gate --judge`), exit code 1. The
"Commit the refreshed scorecard" step never runs.

Traceback (abridged) — the failure is an `httpx`/`httpcore` connection error raised from the **generator**
call, not the judge:

```
File "src/grc_rag/generate.py", line 126, in generate_answer
    answer = generate_answer(item.question, ranked, client=gen_client)
  … httpx _transports/default.py map_httpcore_exceptions …
##[error]Process completed with exit code 1
Terminate orphan process: pid (2648) (ollama)
```

## Root cause
`gate.py --judge` wires `gen_client=OllamaClient()` (`src/grc_rag/llm.py`: `host="http://localhost:11434"`,
`timeout=120.0`). In CI the request to the local Ollama server fails to connect / times out. The workflow
starts Ollama with a race-prone `sleep 5`:

```yaml
- name: Start Ollama + pull the generator model
  run: |
    curl -fsSL https://ollama.com/install.sh | sh
    ollama serve &
    sleep 5
    ollama pull qwen2.5:7b
- name: Run the judge and write the scorecard
  run: python -m grc_rag.gate --judge
```

The runner is CPU-only (`inference compute id=cpu … total 15.6 GiB`). A 7B model generating answers for the
full golden set on CPU is slow and can exceed the client `timeout=120s` per call or exhaust the server, and
`ollama serve &` may not be ready/healthy when the judge starts.

## Fix — pick one path (record the choice as an ADR)
**A. Harden the CI Ollama step (keep CI refresh):**
- Replace `sleep 5` with a readiness poll: loop `curl -sf http://localhost:11434/api/tags` until 200 (cap ~60s).
- Warm the model once (`ollama run qwen2.5:7b "ok"`) before the judge so the first real call isn't cold.
- Raise `OllamaClient.timeout` (e.g. 300s) or make it configurable via env for the CPU CI path.
- Add a step timeout + one retry so a single flaky call doesn't red the badge.

**B. Drop CI generation, refresh locally (simplest, least flaky):**
- Remove `judge-refresh` from `schedule`; keep it `workflow_dispatch`-only or delete it.
- Make **local** `--judge` + commit the supported refresh path; widen `--check-scorecard --max-age-days` to
  match a realistic manual cadence (e.g. 30). Document the ritual in `README`.

**C. Self-hosted / GPU runner:** run `judge-refresh` on a runner that can host the 7B model reliably.

Recommendation: **B** for now (kills the flakiness and the cost/secret surface), revisit A/C if automated
nightly refresh becomes a hard requirement.

## Acceptance criteria
- [ ] The chosen path is implemented and an ADR is added under `docs/adr/`.
- [ ] A manual `workflow_dispatch` (path A/C) **or** a local refresh + commit (path B) produces a fresh
      scorecard with no connection error.
- [ ] `eval-gate` is green on `main`, and stays green across the next scheduled window.

## Related
EVAL-003 (API key), EVAL-004 (push permission) — both must also be fixed for a CI refresh (paths A/C).

---
## Resolution (2026-07-11) — Path B adopted (+ hardened manual A)

Chosen: **Path B** (local-first refresh) as the supported path, recorded in **ADR-0018**
(supersedes the nightly-`schedule` half of ADR-0011).

- `.github/workflows/eval-gate.yml`: removed the nightly `schedule` trigger — the nightly
  `judge-refresh` can no longer red `main`. The job is now `workflow_dispatch`-only.
- Kept a **hardened** manual path (path A applied to the dispatch trigger): Ollama readiness
  poll replaces `sleep 5`, model warm-up before the first real call, and a configurable
  generator timeout via the new `GRC_RAG_OLLAMA_TIMEOUT` env var (implemented immutably in
  `src/grc_rag/llm.py` + `tests/test_llm.py`).
- Per-PR freshness window widened to `--max-age-days 30` to match a manual/local cadence.
- Local refresh ritual documented in `README.md` and `CLAUDE.md`.

Status: **done.**
