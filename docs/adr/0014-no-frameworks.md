# ADR-0014 — No RAG frameworks; build from scratch

- **Status:** Accepted
- **Date:** 2026-06-11

## Context

RAG frameworks like LangChain and LlamaIndex scaffold large amounts of code and hide the
retrieval and generation internals behind abstractions. For a system whose entire value is a
measurable trust property — cite-or-refuse, gated in CI — those internals are exactly what
needs to be transparent and verifiable. A thin, from-scratch implementation keeps every
decision visible and testable.

## Decision

No RAG framework and no vector database. Build each capability from primitives:
`sentence-transformers` for embeddings, `rank-bm25` for lexical search, a numpy matrix for
the store, `httpx`/`pypdf`/`selectolax` for ingestion, the Anthropic SDK for the judge. Add
dependencies one capability at a time, so each line in `pyproject.toml` maps to something
built and explainable. Heavy or external dependencies sit behind small Protocol seams.

## Alternatives considered

- **LangChain / LlamaIndex.** Rejected: they would scaffold large amounts of code that
  obscures the retrieval and generation path, which is the part that most needs to be
  transparent and verifiable.
- **A managed vector DB.** Rejected at this scale ([ADR-0004](./0004-embeddings-no-vector-db.md)).

## Consequences

- The codebase stays small enough to read end to end.
- Production-grade retrieval (hybrid + re-rank) added exactly one dependency (`rank-bm25`).
- The seams keep it testable with stubs, so the suite runs offline with no model, network, or
  key.
- The cost is writing more from scratch: transparency and testability over speed.
- `langfuse` is the one apparent exception, and it is not one: it is an observability backend
  the system sends traces to, not an orchestrator ([ADR-0010](./0010-observability-tracer-seam.md)).
