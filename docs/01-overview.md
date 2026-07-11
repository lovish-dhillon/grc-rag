# Overview

A grounded question-answering system over AI-governance regulation. You ask a question in
plain English, and the system answers with an inline citation to the exact clause it relied
on. When the corpus doesn't support an answer, it refuses instead of guessing. The contract
is *cite or refuse*, and faithfulness to that contract is measured, not asserted.

It is built from scratch, one capability at a time, with no RAG framework — small enough to
read end to end and reason about.

## The problem

Any organisation deploying AI now has to map its systems against frameworks like the NIST
AI Risk Management Framework, ISO/IEC 42001, and the EU AI Act. The source texts are long,
heavily cross-referential, and written in legal register. A compliance analyst who asks
"does the EU AI Act class this system as high-risk?" today gets one of two things: a
lawyer's billable hours, or a general-purpose chatbot that confidently produces a
plausible but wrong article number.

In a compliance setting the second outcome is the dangerous one. A wrong citation that
*looks* right gets pasted into a risk register or a board paper and creates false
assurance. That is worse than no answer, because no answer at least prompts someone to go
and check. The whole system is built around that asymmetry: a confident wrong citation is a
compliance incident, so the bar for answering is high and refusal is a legitimate output.

## Who it's for

- **AI-governance and GRC consultancies** doing first-pass regulatory research, where every
  engagement currently starts with manual reading.
- **In-house compliance and legal teams** at organisations adopting AI.
- **Me.** It is the working demo behind my own AI-readiness audit service, and proof that I
  can ship a RAG system whose grounding I can stand behind.

## What it does

It answers questions across three freely-redistributable standards:

- NIST AI RMF 1.0
- NIST Generative AI Profile
- EU AI Act (Regulation (EU) 2024/1689, via EUR-Lex)

ISO/IEC 42001 is deliberately excluded from the indexed text because it is copyrighted and
paywalled. The system can still reference its clause identifiers as factual pointers, but it
never ingests or ships the standard's content. That boundary is enforced in code, not by
good intentions (see [ADR-0002](./adr/0002-corpus-licensing-as-code.md)).

A question runs through hybrid retrieval (lexical plus dense), a cross-encoder re-ranker, a
calibrated support threshold, and a generator under a strict cite-or-refuse prompt. Every
citation in the output is validated against the chunks actually retrieved, so the model
cannot invent a source it never saw. The full path is in
[02-architecture.md](./02-architecture.md) and [03-data-flow.md](./03-data-flow.md).

## The differentiator: cite-or-refuse, measured

Plenty of RAG demos claim to be faithful. The difference here is that faithfulness is a
number the build defends, not a property I assert.

A real LLM-as-judge reads each answer, decomposes it into atomic claims, and rules each
claim supported or unsupported against the chunks that were cited. Faithfulness is the
fraction of claims that hold up. This replaces the token-overlap metric my two earlier
prototypes used, which scored close to 1.0 by construction because it only measured whether
the answer reused words from its context. A CI gate then fails the build if faithfulness or
retrieval recall drops below threshold. The reasoning is in
[04-evaluation.md](./04-evaluation.md) and [ADR-0008](./adr/0008-claim-by-claim-judge.md).

## Results

Measured on the 41-item hand-verified golden set on 2026-07-11 (prompt v3; hybrid retrieval →
re-rank, local qwen2.5:7b generator, Anthropic Haiku judge at temperature 0):

| Metric | Target | Result | |
|--------|--------|--------|---|
| Faithfulness (LLM-judge) | ≥ 0.90 | **0.924** | pass |
| Recall@10 | ≥ 0.85 | **0.889** | pass |
| Out-of-corpus refusal | — | **5 / 5** | pass |
| Answer relevancy | tracked | **0.806** | recovered (see below) |

The CI gate is green, and a seeded regression fixture turns it red on demand to prove it
bites. Prompt v3 (2026-07-11) lifted faithfulness to 0.924 *and* recovered relevancy to 0.806
by making cite-or-refuse procedural — after a stale-scorecard refresh had surfaced that the
earlier v2 prompt had regressed to ~0.88 on the current generator build. The full story is in
[04-evaluation.md](./04-evaluation.md) and [ADR-0012](./adr/0012-prompt-versioning-tradeoff.md).

## What's included

The full pipeline runs end to end:

| Area | What it covers |
|-------|-------------|
| Fundamentals | ingest, chunk, dense retrieval, cited generation |
| Production retrieval | hybrid (BM25 + dense, RRF), cross-encoder re-rank, calibrated refusal threshold, versioned prompts |
| Eval and CI gate | 41-item golden set, IR metrics + claim-by-claim judge, Langfuse tracing, two-tier regression gate |
| Interface | FastAPI boundary + a React/Vite frontend (ask → cited answer → click through to the clause, or an honest refusal) |

## How this is built

Deliberately few moving parts. No LangChain or LlamaIndex; one
dependency per capability; immutable data and fail-fast validation throughout. It runs
local-first, so generation and retrieval cost effectively nothing. The single cloud call is
the faithfulness judge, and even that runs on a cadence rather than on every request. The
reasoning behind that posture is [ADR-0014](./adr/0014-no-frameworks.md).
