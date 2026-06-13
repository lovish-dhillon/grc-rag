# ADR-0007 — Local generator with citation verification

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

The generator turns retrieved chunks into an answer. Two requirements pull on it: it should
cost nothing to run (local-first), and it must not be trusted to be honest about its own
citations. A real LLM will happily cite a `chunk_id` it never saw, or write a confident
answer with no citation at all.

## Decision

Generate with `qwen2.5:7b` via local Ollama at temperature 0, with `num_ctx` set to 8192.
That context-window setting matters: Ollama's 2048 default silently truncates the chunk text
the model is supposed to cite, so it has to be raised. After generation, extract every `[chunk_id]` with a regex and
validate each against the set of ids actually retrieved. Dangling citations are dropped; if
no valid citation survives, the answer is downgraded to the refusal sentinel.

## Alternatives considered

- **A cloud generator.** Rejected for the default path: it adds cost and a key to every
  query. The one cloud call in the system is the judge, on a cadence, not the generator.
- **Trusting the model's citations.** Rejected outright: it makes fabricated provenance
  possible, which defeats the entire purpose.

## Consequences

- Per-query generation cost is effectively zero, with no key required.
- Fabricated citations are structurally impossible to ship: "uncited" collapses to
  "refused." Verified live, this produced zero dangling citations and 5-of-5 out-of-corpus
  refusals.
- The local 7B model is the current ceiling on answer quality; the v2 prompt's relevancy
  regression ([ADR-0012](./0012-prompt-versioning-tradeoff.md)) points at a stronger
  generator as the real fix.
