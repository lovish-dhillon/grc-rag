# ADR-0015 — Thin FastAPI boundary; refusal as HTTP 200

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The frontend needs an HTTP edge over the pipeline. The risk is that the API becomes a second,
drifting copy of the cite-or-refuse logic, or that it models a refusal as an error and
teaches clients that refusing is a failure.

## Decision

`api.py` is pure transport. Three choices carry it:

1. **Reuse, don't fork.** Retrieval is captured by reusing the tracing recording proxy
   (wrap the real function, read what it retrieved), so the pipeline is not duplicated.
2. **Refusal is HTTP 200** with `refused: true`, not a 4xx or 5xx. A refusal is a valid,
   intended answer; making it an HTTP error would be a category mistake and would push
   clients to treat it as something gone wrong.
3. **Resolve citations at the edge.** The response DTO carries each citation's `clause_label`
   and the chunk text, so the client can show clause text on click with no second round-trip.

Collaborators are injected via a factory, so the tests drive a `TestClient` with stubs and
need no model, key, or network.

## Alternatives considered

- **Refusal as 422/409.** Rejected: it conflates an intended outcome with a client or server
  fault.
- **Return citation ids only, resolve client-side.** Rejected: it forces a second request per
  citation. Resolving once at the edge is simpler and faster for the UI.

## Consequences

- The API exposes cite-or-refuse without owning a copy of it, so there is nothing to drift.
- `GET /health` and `POST /ask` are the surface; the app is built lazily so importing the
  module never loads a model.
- The UI can render an answer, its clause text, and a refusal without any extra calls.
