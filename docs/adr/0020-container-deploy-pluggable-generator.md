# ADR-0020 — Container deployment with a config-selected generator

**Status:** Accepted
**Date:** 2026-08-02

## Context

Everything in this system was built to be *checkable by a stranger*: the corpus is public, the
golden set is committed, the scorecard is committed, and the gate runs in CI. But until now the
only way to see it answer anything was to clone the repo, create a virtualenv, download ~90 MB of
models and install Ollama. That is a high bar for the person the project is meant to persuade, and
it means the strongest claim the repo makes — *it refuses rather than guesses* — cannot be observed
without a local build.

Deploying introduces one genuine problem. ADR-0007 chose a **local Ollama generator**, deliberately:
it is keyless, zero marginal cost, and keeps the request path free of an API dependency. That
choice does not survive a container. There is no Ollama daemon in a Container App, and bundling one
would mean shipping a multi-gigabyte model server to answer questions that a hosted model answers
in one HTTP call.

So the generator must differ between laptop and cloud. The risk is that "differ" quietly becomes
"fork": two code paths, two behaviours, and a deployed system whose answers are no longer the ones
the committed scorecard measured.

## Decision

**Ship a container that selects its generator from configuration, through the existing
`LLMClient` seam — not through a second code path.**

- `api.build_llm_client()` reads `GRC_RAG_LLM` (`ollama` | `anthropic`), defaulting to `ollama`.
  The local experience is unchanged and still keyless.
- The container sets `GRC_RAG_LLM=anthropic` and receives `ANTHROPIC_API_KEY` as a runtime secret.
  `GRC_RAG_LLM_MODEL` pins the generation model explicitly, so a deployment never inherits the
  *judge's* default model by accident.
- An unrecognised backend name **raises**. It does not fall back to a default.
- The image bakes in the retrieval models and the committed index, so the deployed retrieval path
  is byte-identical to the local one and the container needs no network at boot.

## Consequences

**Good.** There is now a URL a reviewer can open and watch the system refuse — which is the whole
point of the project, and previously took a 20-minute local setup to see. The seam introduced in
ADR-0007 proved sufficient: the deployment cost one function and zero changes to retrieval,
enforcement or generation logic. Retrieval is identical in both environments, so a difference in
answers can only come from the generator, which narrows debugging to one variable.

**Bad, and stated plainly.** *The committed scorecard does not cover the hosted generator.*
Faithfulness 0.924 / recall@10 0.889 / 5-of-5 refusal (2026-07-11, prompt v3) were measured with
the **local Ollama generator**. Retrieval metrics (recall@10) are generator-independent and carry
over unchanged. Faithfulness and relevancy are not: they are a property of the generated text, and
a different model can produce different numbers. Until the harness is re-run against
`GRC_RAG_LLM=anthropic` and a second scorecard is committed, **the published faithfulness number
describes the local path only, and the deployed demo must not be cited as evidence for it.**
This is recorded as a known gap rather than papered over — a project whose thesis is "measure it,
don't assert it" cannot quietly extend a measurement to a configuration it never measured.

**Cost.** The request path in the deployed configuration is no longer free; each answer is one
hosted-model call. The `cost_usd=0.0` currently hard-coded in the API's trace record is therefore
wrong for the cloud configuration and is tracked as a follow-up ticket.

## Alternatives considered

- **Bundle Ollama in the image.** Preserves the measured configuration exactly, at the price of a
  multi-gigabyte image and a container that needs far more memory than the free tier allows.
  Rejected as disproportionate for a demo surface.
- **Deploy retrieval only, and refuse to generate.** Honest and cheap, but it removes the one
  behaviour worth showing.
- **Default to `anthropic` everywhere.** Simpler, one path, no branch — but it breaks the keyless
  local development loop that ADR-0007 exists to protect, and would put an API key in the way of
  running the tests.
