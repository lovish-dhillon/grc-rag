# ADR-0021 — Expose the pipeline as an MCP tool

**Status:** Accepted
**Date:** 2026-08-02

## Context

Ask any general assistant what the EU AI Act says about prohibited practices and it will answer
from parametric memory: fluent, mostly right, occasionally wrong, and never with a clause you can
check. That is precisely the failure this repo was built to characterise — in GRC, a confident
wrong citation is an incident, not bad UX (ADR-0001).

The system already answers that question properly, but only for two consumers: a human at the CLI,
and a human in the React console (ADR-0015, ADR-0016). An assistant is a third consumer with the
same need and no way in. Model Context Protocol is the standard way to give it one.

There is a second, quieter reason. The cite-or-refuse invariant is *more* valuable to a model than
to a human. A human who receives "not supported by the corpus" simply reads it. A model that
receives it has been handed an explicit instruction not to fall back on its own memory — which is
the single most useful thing this corpus can tell it.

## Decision

**Expose `answer_with_enforcement` as one MCP tool, `ask_grc`, over stdio — as a transport, not a
new code path.**

- `grc_rag.mcp_server.build_answer_payload()` is a pure function over injected collaborators. It
  wraps the retriever in the existing `_RecordingRetriever` and resolves citations to clause label
  and source text exactly as `api.build_response` does. There is no second implementation of
  anything that makes the system trustworthy.
- **A refusal is a successful result**, returned as `{"refused": true, "citations": []}`. It is not
  an error and does not raise.
- The tool description tells the calling model, in words, to treat a refusal as authoritative and
  not to substitute its own knowledge.
- The `mcp` SDK is an **optional extra**. It is imported lazily inside `serve()`, so the package,
  CLI, eval harness, HTTP API and the full test suite work whether or not it is installed.
- Transport is **stdio**: every MCP client supports it, and it needs no port, no CORS and no auth
  design — the right default for a tool a developer wires into their own assistant.

## Consequences

**Good.** The system's central property now reaches the consumer that most needs it. The build cost
was one module and no change to retrieval, enforcement or generation — which is the strongest
available evidence that the seams introduced in ADR-0007 and ADR-0015 were drawn in the right
place. Because the payload builder is pure, it is tested with the same stubs as everything else:
no models, no key, no network, and no MCP SDK required to run the suite.

**Bad.** There are now three boundaries (CLI, HTTP, MCP) over one pipeline, and a change to the
citation contract has to be reflected in two response builders. That duplication is deliberate —
each transport owns its own DTO shape — but it is real, and a third transport would justify
extracting a shared resolver.

**Neutral.** `serve()` itself is untested: it is SDK plumbing over a function that is thoroughly
tested. Marked `# pragma: no cover` rather than papered over with a mock that would assert nothing.

## Alternatives considered

- **Expose the raw retriever as the tool** (`search` returning chunks, letting the assistant write
  the answer). Simpler, and it sidesteps generation cost entirely — but it hands grounding back to
  the model and discards the enforced refusal, which is the whole contribution.
- **HTTP/SSE transport instead of stdio.** Needed if the server is ever hosted for remote clients;
  it also drags in auth, CORS and rate limiting. Deferred until there is a caller that needs it.
- **A second tool for the eval scorecard.** Attractive, but the scorecard is a static committed
  file that a client can simply read. No tool needed.
