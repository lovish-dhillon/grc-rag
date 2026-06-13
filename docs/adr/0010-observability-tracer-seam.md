# ADR-0010 — Observability via a Tracer seam over Langfuse

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The trust claim needs operational evidence as well as quality evidence: what was retrieved,
how long a query took, what it cost. The risk is coupling the pipeline to an observability
backend, or pulling in a framework that starts orchestrating the system.

## Decision

A one-method `Tracer` seam with a frozen `QueryTrace` (question, retrieved ids and scores,
answer, citations, refused, prompt_version, latency_ms, cost_usd). `NullTracer` is the
default, `RecordingTracer` is for tests, and `LangfuseTracer` ships to a self-hosted Langfuse
instance, imported lazily and failing fast on missing configuration. Tracing is additive:
`traced_answer` wraps the existing pipeline functions and captures retrieval through a small
recording proxy, so the pipeline itself is untouched. P50/P95 latency and cost-per-request
are computed in our own pure `percentiles.py`, not read off a dashboard.

## Alternatives considered

- **Compute averages instead of percentiles.** Rejected: a mean hides the tail latency users
  actually feel. P95 is the number that matters.
- **Let the observability tool into the pipeline.** Rejected: Langfuse is a backend the
  system sends traces to, nothing more. This keeps it compatible with the no-frameworks
  stance ([ADR-0014](./0014-no-frameworks.md)).

## Consequences

- The seam keeps the system explainable and testable: the tracing tests need no Docker, no
  live server, and no SDK.
- Latency and cost are first-class, derived from recorded traces in code we own.
- Tracing never blocks a query, since the default tracer does nothing.
