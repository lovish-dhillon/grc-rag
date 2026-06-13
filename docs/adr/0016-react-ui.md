# ADR-0016 — React/Vite UI with first-class refusal

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The pipeline is trustworthy but invisible. A demo that makes cite-or-refuse legible to a
non-engineer is what turns the work into something I can show. The danger is that a UI
quietly reintroduces the exact failure the backend prevents, by rendering a refusal as an
error or hiding how an answer was retrieved.

## Decision

A standalone Vite + React + TypeScript package, separate from the Python side (it does not
touch `pyproject.toml`) and owning no cite-or-refuse logic of its own. Four choices carry it:

1. **Citations are click-through chips** local to the response DTO; clicking expands the
   exact clause text with no second request.
2. **Refusal is first-class**, a calm `role="status"` state, visually distinct from a network
   error (`role="alert"`).
3. **A "how it answered" panel** shows the ranked clauses, scores, and latency, collapsed by
   default — honest disclosure rather than a black box.
4. **One discriminated result state** (`idle | answer | refusal | error`) so every case
   renders unambiguously.

The stack is deliberately small: hand-written CSS (no Tailwind), `useState` only (no Redux),
and the API base URL from `VITE_API_BASE` config rather than hardcoded.

## Alternatives considered

- **A CSS/state framework.** Rejected: more dependencies to defend for a single-screen demo.
- **Refusal styled like an error.** Rejected: it would contradict the backend's whole point,
  that refusal is a legitimate answer ([ADR-0001](./0001-cite-or-refuse-invariant.md)).

## Consequences

- The UI makes the invariant visible: a citation you can click to its source, and a refusal
  that reads as a deliberate, calm outcome.
- It builds to a static bundle in `ui/dist/`, deployable to any static host with the API base
  pointed at a deployed backend.
- A reported `npm audit` advisory is dev-toolchain only (esbuild's dev-server issue via Vite)
  and does not ship in the production bundle; the project stays on the stable Vite 6 for the
  demo.
