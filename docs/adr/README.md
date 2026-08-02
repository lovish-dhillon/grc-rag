# Architecture Decision Records

Each record captures one architecturally-significant decision: the context that forced it,
the decision taken, the alternatives weighed, and the consequences. They follow the
Michael Nygard format. Records are immutable once accepted; a later decision that changes
course gets its own record and supersedes the old one rather than editing it.

| # | Decision | Status | Date |
|---|----------|--------|------|
| [0001](./0001-cite-or-refuse-invariant.md) | Cite-or-refuse is a hard invariant | Accepted | 2026-06-11 |
| [0002](./0002-corpus-licensing-as-code.md) | Corpus licensing enforced as code | Accepted | 2026-06-12 |
| [0003](./0003-chunking.md) | Token-based chunking with structure-aware labelling | Accepted | 2026-06-11 |
| [0004](./0004-embeddings-no-vector-db.md) | Local MiniLM embeddings, no vector database | Accepted | 2026-06-12 |
| [0005](./0005-rrf-fusion.md) | Hybrid retrieval by reciprocal-rank fusion | Accepted | 2026-06-12 |
| [0006](./0006-rerank-threshold-enforcement.md) | Cross-encoder re-rank and calibrated refusal threshold | Accepted | 2026-06-12 |
| [0007](./0007-local-generator-citation-check.md) | Local generator with citation verification | Accepted | 2026-06-12 |
| [0008](./0008-claim-by-claim-judge.md) | Claim-by-claim LLM-judge for faithfulness | Accepted | 2026-06-13 |
| [0009](./0009-golden-set.md) | Golden set keyed on clause labels, adversarially verified | Accepted | 2026-06-13 |
| [0010](./0010-observability-tracer-seam.md) | Observability via a Tracer seam over Langfuse | Accepted | 2026-06-13 |
| [0011](./0011-two-tier-ci-gate.md) | Two-tier CI gate with a committed scorecard | Accepted | 2026-06-13 |
| [0012](./0012-prompt-versioning-tradeoff.md) | Versioned prompts; v2 accepted with a known tradeoff | Accepted | 2026-06-13 |
| [0013](./0013-drop-uncited-metric.md) | Drop the "zero uncited claims" gate metric | Accepted | 2026-06-13 |
| [0014](./0014-no-frameworks.md) | No RAG frameworks; build from scratch | Accepted | 2026-06-11 |
| [0015](./0015-fastapi-boundary.md) | Thin FastAPI boundary; refusal as HTTP 200 | Accepted | 2026-06-13 |
| [0016](./0016-react-ui.md) | React/Vite UI with first-class refusal | Accepted | 2026-06-13 |
| [0017](./0017-console-redesign-live-data.md) | Console redesign bound to live data | Accepted | 2026-06-13 |
| [0018](./0018-local-first-scorecard-refresh.md) | Local-first scorecard refresh; no nightly CI judge (supersedes the schedule half of 0011) | Accepted | 2026-07-11 |
| [0019](./0019-prompt-v3-procedural-grounding.md) | Prompt v3: procedural per-sentence grounding (faithfulness 0.879→0.924, relevancy 0.722→0.806) | Accepted | 2026-07-11 |
| [0020](./0020-container-deploy-pluggable-generator.md) | Container deployment with a config-selected generator (scorecard covers the local generator only) | Accepted | 2026-08-02 |
| [0021](./0021-mcp-boundary.md) | Expose the pipeline as an MCP tool (`ask_grc`), refusal as a successful result | Accepted | 2026-08-02 |
