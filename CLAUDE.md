# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`grc-rag` is a grounded, **cite-or-refuse** RAG system that answers questions over
AI-governance regulation (NIST AI RMF, NIST Generative AI Profile, EU AI Act) and
cites the exact source clause — or refuses when retrieval can't ground the claim.
It is built from scratch, one capability at a time, with **no RAG framework** — small
enough to read end to end. That intent shapes how to work here (see below).

## Repository layout

The root is kept clean — code, config, and a public README. Everything written lives under `docs/`.

```
grc-rag/
  README.md            # public front door (problem · differentiator · results · how to run)
  CLAUDE.md            # this file — dev guide
  pyproject.toml
  src/grc_rag/         # the package (one module per capability)
  tests/               # pytest suite (offline; stubs for models/keys)
  data/                # processed index + golden set + committed eval scorecard
  .github/workflows/   # eval-gate CI
  ui/                  # the React/Vite demo frontend (its own package; doesn't touch pyproject.toml)
  docs/
    README.md          # doc index + reading order
    01-overview.md     # case study: problem · audience · what it does · headline results
    02-architecture.md # boundary, components, principles, quality attributes (Mermaid)
    03-data-flow.md    # ingest → index → query, with the concrete data structures
    04-evaluation.md   # golden set, faithfulness judge, measured results, CI gate
    05-demo.md         # real transcripts, how to run, the web UI
    adr/               # Architecture Decision Records — one file per significant decision
```

The private learning log that ran alongside this build is kept **outside the repo**, under
`Personal/My Learning/grc-rag notes docs/`. Don't reproduce it here.

## Commands

This is a Python ≥3.11 package using a local `.venv` (Python 3.12). All tooling is in `.venv/bin`.

```bash
.venv/bin/pytest                        # run the full test suite
.venv/bin/pytest -q                     # quiet
.venv/bin/pytest tests/test_chunking.py # single file
.venv/bin/pytest -k overlap             # single test by name substring
.venv/bin/ruff check src tests          # lint (line-length 100, py311 target)
.venv/bin/ruff format src tests         # format
.venv/bin/pip install -e ".[dev]"       # editable install + dev deps

python -m grc_rag.query "…"             # ask a question (cite-or-refuse), local Ollama generator
python -m grc_rag.evaluate              # run the eval harness over the golden set (needs ANTHROPIC_API_KEY)
python -m grc_rag.gate --tier1          # deterministic recall gate (keyless)
python -m grc_rag.gate --check-scorecard --max-age-days 14   # faithfulness gate off the committed scorecard
```

`pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`, so tests
import `grc_rag.*` directly with no path juggling.

## Working norms specific to this repo

1. **Transparency over magic.** The system's value is a measurable trust property
   (cite-or-refuse, gated in CI), so the retrieval and generation internals must stay
   readable and verifiable. Common hollow shortcuts are explicitly avoided: extractive
   fake generation, hashing-trick embeddings, and a circular token-overlap faithfulness
   metric. So: **do not silently scaffold large modules, pull in heavyweight frameworks
   (LangChain/LlamaIndex), or add code whose behaviour isn't explainable.** Build the
   minimum real thing, explain the why, prefer transparency over magic.

2. **Add dependencies one capability at a time.** Every line in `pyproject.toml`
   maps to something actually built and explainable. Current deps: `tiktoken`, `httpx`,
   `pypdf`, `selectolax`, `sentence-transformers`, `numpy`, `rank-bm25` (retrieval/gen),
   plus `anthropic` (the LLM-judge) and `langfuse` (observability backend, not a framework).
   Don't front-load a stack a capability doesn't yet need.

3. **Immutability + fail-fast are non-negotiable here** (and globally — see
   `~/.claude/rules`). See `src/grc_rag/chunking.py` as the reference style:
   `@dataclass(frozen=True)`, pure functions returning new tuples, boundary
   validation that raises `ValueError` loudly rather than emitting silent garbage,
   and a module docstring that teaches the *why*.

## Two hard invariants (recorded as decisions — never violate silently)

- **Cite-or-refuse.** The system must refuse ("not supported by the corpus") rather
  than answer when retrieval doesn't ground the claim. A confident wrong citation in
  GRC is worse than no answer. Faithfulness is a measured, CI-gated metric, not a vibe.
- **Corpus = freely-redistributable standards only.** Ingest NIST AI RMF, NIST
  GenAI Profile, EU AI Act (EUR-Lex). **ISO/IEC 42001 is copyrighted and paywalled —
  never ingest or ship its text.** Mapping to its *clause IDs* (factual references)
  is fine; shipping its content is not.

## Architecture & where the build is

```
ingest → chunk → embed (hybrid BM25 + dense) → rerank (cross-encoder)
       → generate (LLM, cite-or-refuse) → eval (LLM-judge faithfulness + IR metrics)
       → observability (traces · P50/P95 · cost/req) → CI regression gate → UI
```

**Built: Phases 1–4 complete (2026-06-13).** The full pipeline runs end-to-end and is
*measured*: `chunking`/`structure` → `ingest` → `embeddings`/`retrieve` → `bm25`/`hybrid` (RRF)
→ `rerank` → `enforce` (calibrated threshold) → `generate` (cite-or-refuse) → `query` CLI;
then `golden` (41-item hand-verified set) → `ir_metrics` + `judge` (a **real claim-by-claim
LLM-judge**, `AnthropicClient` behind the `LLMClient` seam) → `evaluate` → `tracing`
(`Tracer` seam over self-hosted Langfuse) + `percentiles` → `gate` + CI workflow; and a thin
`api` (FastAPI) boundary with the `ui/` React frontend. The gate is **green on prompt v2**
(faithfulness 0.905, recall@10 0.889). Architecture + phased plan: `docs/02-architecture.md`;
measured results: `docs/04-evaluation.md`.

## The docs are the source of truth (`docs/`)

The numbered docs are both the case-study presentation **and** the cold-start brief. A fresh
session reads `01`→`02`→`03` and can work without re-explaining.

| File | Role |
|---|---|
| [`docs/README.md`](./docs/README.md) | Doc index + reading order. **Read first.** |
| [`docs/01-overview.md`](./docs/01-overview.md) | Problem, audience, what it does, headline results. |
| [`docs/02-architecture.md`](./docs/02-architecture.md) | Boundary, components, principles, quality attributes. |
| [`docs/03-data-flow.md`](./docs/03-data-flow.md) | Ingest → index → query, with the data structures. |
| [`docs/04-evaluation.md`](./docs/04-evaluation.md) | Golden set, judge, measured results, the CI gate. |
| [`docs/05-demo.md`](./docs/05-demo.md) | Real transcripts, how to run, the web UI. |
| [`docs/adr/`](./docs/adr/) | Architecture Decision Records — one file per significant decision. |
| [`README.md`](./README.md) | Public-facing repo readme. |

When you make a meaningful design choice, **add a new ADR** under `docs/adr/` (next number,
Nygard format: Status · Context · Decision · Consequences) and add its row to
[`docs/adr/README.md`](./docs/adr/README.md). ADRs are immutable once accepted — a change of
course gets a new record that supersedes the old one, never an edit to a past entry. After a
material change, refresh the status in `docs/01-overview.md` and any measured numbers in
`docs/04-evaluation.md`.

## The learning loop (kept private, outside the repo)

A private learning log runs alongside this build, but it lives **outside the repo** under
`Personal/My Learning/grc-rag notes docs/` (two tracks: RAG-system engineering, and the
AI-governance domain). Don't reproduce it in this repo. The discipline still applies to any
note written there — **cite-or-refuse**: a note claims only what the source actually said,
and never fills a gap with a plausible guess.

## Not a git repo

This directory is not git-initialised. Don't assume git history exists; offer to
`git init` if version control is needed.
