# grc-rag — grounded Q&A over AI-governance regulation

> Ask a question across NIST AI RMF, the EU AI Act, and the NIST Generative AI
> Profile and get an answer that **cites the exact clause — or refuses to answer.**
> A RAG system built for a setting where a confident wrong answer is a compliance
> incident, not just bad UX — with a real eval harness, a faithfulness judge, and a
> CI gate that fails the build on a quality regression.

## The problem (why this exists)

Any organisation deploying AI now has to map its systems against frameworks like
NIST AI RMF, ISO/IEC 42001, and the EU AI Act. Those source texts are long, densely
cross-referential, and written in legal register. A compliance analyst asking *"does
the EU AI Act class this system as high-risk?"* gets one of two things today: a
lawyer's billable hours, or a generic chatbot that confidently invents a
plausible-but-wrong article number. In compliance, the second is worse than no answer.

## Use cases

- First-pass regulatory research for AI-governance and GRC work.
- A grounded reference for in-house compliance and legal teams mapping AI systems to
  NIST AI RMF and the EU AI Act.
- A reference implementation of cite-or-refuse RAG with a measured faithfulness gate.

## The differentiator: cite-or-refuse, *measured*

Every claim in an answer carries an inline citation to the source clause. When
retrieval can't ground a claim, the system **says so** instead of fabricating one.
And the trust claim isn't a vibe — it's a number: a real LLM-as-judge scores
faithfulness **claim-by-claim against the cited chunks** (not a circular token-overlap
metric), and a CI gate fails the build if faithfulness or retrieval recall drops below
threshold.

## How it works

```
ingest → chunk → embed (hybrid: BM25 + dense) → rerank (cross-encoder)
       → generate (LLM, cite-or-refuse) → eval (LLM-judge faithfulness + IR metrics)
       → observability (traces · P50/P95 latency · cost/req) → CI regression gate → UI
```

Built from scratch — no LangChain/LlamaIndex, one dependency per capability, every
module immutable + fail-fast. Local-first (sentence-transformers + a local Ollama
generator) so it runs at near-zero cost; the one cloud call is the faithfulness judge.

## Features

- **Hybrid retrieval** — BM25 + dense (sentence-transformers), fused by reciprocal-rank
  fusion, then a cross-encoder re-rank.
- **Cite-or-refuse generation** — every claim cites a source clause; weak retrieval is
  refused at a calibrated support threshold instead of answered.
- **Measured faithfulness** — a claim-by-claim LLM-judge over a 41-item hand-verified
  golden set, with IR metrics (recall@k, MRR, nDCG).
- **CI regression gate** — recall@10 on every push, the paid judge on a cadence; a
  quality drop fails the build.
- **Observability** — per-query traces (Langfuse seam) with P50/P95 latency and cost.
- **HTTP + UI** — a thin FastAPI boundary (refusal as HTTP 200) and a React/Vite
  console: ask → cited answer → click through to the clause.

## Results (measured, 2026-07-11 — prompt v3)

On the 41-item hand-verified golden set, live (hybrid→re-rank · local qwen2.5:7b ·
Anthropic Haiku judge, temperature 0):

| Metric | Target | Actual | |
|--------|--------|--------|---|
| Faithfulness (LLM-judge) | ≥ 0.90 | **0.924** | ✅ |
| Recall@10 | ≥ 0.85 | **0.889** | ✅ |
| Out-of-corpus refusal | — | **5/5** | ✅ |
| Answer relevancy | — | **0.806** | — |

**CI gate: green**, with 254 tests passing. A deliberately-seeded regression turns it red on
demand. Full numbers, the honest tradeoffs, and every design decision are in the
[evaluation doc](./docs/04-evaluation.md) and the [decision records](./docs/adr/).

> **What these numbers cover.** They were measured with the **local Ollama generator**. Recall@10
> is generator-independent; faithfulness and relevancy are properties of the generated text, so a
> deployment running a hosted model is *not* covered by this scorecard until the harness is re-run
> against it ([ADR-0020](./docs/adr/0020-container-deploy-pluggable-generator.md)). Stated here
> rather than buried, because a project whose thesis is "measure it, don't assert it" cannot
> quietly extend a measurement to a configuration it never measured.

## Deploy it, or plug it into an assistant

```bash
# Container (FastAPI boundary; models + index baked in) — full walkthrough in deploy/README.md
docker build -t grc-rag . && docker run -p 8000:8000 \
  -e GRC_RAG_LLM=anthropic -e ANTHROPIC_API_KEY=… grc-rag

# MCP server — gives an assistant one tool, `ask_grc`, that cites clauses or refuses
pip install -e ".[mcp]" && python -m grc_rag.mcp_server
```

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m grc_rag.query "Which AI practices are prohibited under the EU AI Act?"
# eval + gate (needs ANTHROPIC_API_KEY for the judge; local Ollama for generation):
.venv/bin/python -m grc_rag.evaluate
.venv/bin/python -m grc_rag.gate --check-scorecard --max-age-days 30
```

**Refreshing the scorecard.** The faithfulness scorecard is refreshed **locally**, not by a
nightly CI job — a 7B generator on a free CPU runner is too slow and flaky to trust ([ADR-0018](./docs/adr/0018-local-first-scorecard-refresh.md)).
When the committed card ages past 30 days (or the golden set changes), regenerate and commit it
where Ollama and the key already work:

```bash
export ANTHROPIC_API_KEY=…                 # your key (the judge is the only paid call)
ollama serve & ; ollama pull qwen2.5:7b    # if not already running
.venv/bin/python -m grc_rag.gate --judge   # rewrites data/eval/scorecard.json with today's date
git add data/eval/scorecard.json && git commit -m "chore(eval): refresh scorecard"
```

## Corpus & licensing (a real decision, not an afterthought)

This system indexes only **freely-redistributable** source standards:

- **NIST AI RMF 1.0** + **NIST Generative AI Profile** (US Government work, public).
- **EU AI Act** (Regulation (EU) 2024/1689, via EUR-Lex, redistributable with attribution).

**ISO/IEC 42001 is copyrighted and paywalled.** We do **not** ingest or ship its
text — the exclusion is enforced in code (an allowlist + deny-guard, with a test).
Where useful we map answers to its *clause identifiers* (factual references, not the
standard's content). Respecting that boundary is part of doing AI governance properly.

## Documentation

Full docs are in **[docs/](./docs/)**:

- **[Overview](./docs/01-overview.md)** — problem, audience, what it does, headline results.
- **[Architecture](./docs/02-architecture.md)** — boundary, components, principles, quality attributes (with diagrams).
- **[Data flow](./docs/03-data-flow.md)** — ingest → index → query, with the concrete data structures.
- **[Evaluation](./docs/04-evaluation.md)** — golden set, faithfulness judge, measured results, the CI gate.
- **[Demo](./docs/05-demo.md)** — real transcripts, how to run it, the web UI.
- **[Decision records](./docs/adr/)** — one ADR per significant choice, with the alternatives weighed.
