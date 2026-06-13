# Documentation

The full documentation for grc-rag, a cite-or-refuse RAG system over AI-governance
regulation. Start at the overview and read down; the architecture and data-flow docs go
deeper, the evaluation doc holds the numbers, and the ADRs record why each significant choice
was made.

## Reading order

| Doc | What it covers |
|---|---|
| [01-overview.md](./01-overview.md) | The problem, who it's for, what the system does, headline results. A five-minute read. |
| [02-architecture.md](./02-architecture.md) | System boundary, components, principles, and quality attributes, with diagrams. |
| [03-data-flow.md](./03-data-flow.md) | How data moves through ingest, index, and query, with the concrete data structures. |
| [04-evaluation.md](./04-evaluation.md) | The golden set, the faithfulness judge, the measured results, and the CI gate. |
| [05-demo.md](./05-demo.md) | Real transcripts, how to run it locally, and the web UI. |
| [adr/](./adr/) | Architecture Decision Records — one per significant decision, with the alternatives weighed. |

## Where things live

- Code: `src/grc_rag/` (one module per capability) and `ui/` (the React frontend).
- Tests: `tests/` (offline; every model and key is stubbed).
- Data: `data/processed/` (the committed index), `data/golden/` (the eval set),
  `data/eval/scorecard.json` (the committed judge result the gate reads).
- CI: `.github/workflows/eval-gate.yml`.

The private learning log that ran alongside this build is kept out of the repo. The two
project-level guides for working in the code are the root [README](../README.md) and
[CLAUDE.md](../CLAUDE.md).
