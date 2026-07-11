# Demo

What the system does at the command line and in the browser. The transcripts below are real
output from the built pipeline, not mock-ups.

## Cite-or-refuse at the CLI

A prohibited-practices question against the EU AI Act. The answer carries an inline citation
on every claim, and the citations resolve to a named clause:

```
$ python -m grc_rag.query "Which AI practices are prohibited?"

The following AI practices are prohibited:

1. An AI system that deploys subliminal techniques beyond a person's consciousness or
   purposefully manipulative or deceptive techniques, causing significant harm [eu-ai-act::79].
2. AI systems that exploit any of the vulnerabilities of a natural person or a specific
   group of persons [eu-ai-act::79].
3. AI systems for the evaluation or classification of natural persons based on their social
   behaviour [eu-ai-act::79].

Citations:
  eu-ai-act::79 — EU AI Act — Article 5
```

A NIST AI RMF question, answered from the right subcategory:

```
$ python -m grc_rag.query "What does GOVERN 1.1 of the AI RMF require?"

GOVERN 1.1 of the AI RMF requires that legal and regulatory requirements involving AI are
understood, managed, and documented [nist-ai-rmf::20].

Citations:
  nist-ai-rmf::20 — NIST AI RMF — GOVERN 1.1
```

An out-of-corpus question. ISO/IEC 42001 is not in the index by design, so the system
refuses rather than inventing a clause:

```
$ python -m grc_rag.query "What does ISO/IEC 42001 clause 6.1.2 require?"

Not supported by the corpus.
```

## Run it locally

The processed index is committed, so you do not need to re-ingest to ask a question. You do
need a local Ollama generator for the answer step.

```bash
# install
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

# generator (one-time)
ollama serve &
ollama pull qwen2.5:7b

# ask
.venv/bin/python -m grc_rag.query "Which AI practices are prohibited under the EU AI Act?"
```

To rebuild the index from the source standards instead of using the committed one:

```bash
.venv/bin/python -c "from pathlib import Path; \
from grc_rag.ingest import ingest_corpus; from grc_rag.embeddings import build_index; \
ingest_corpus(cache_dir=Path('data/raw'), out_path=Path('data/processed/chunks.jsonl')); \
build_index(Path('data/processed/chunks.jsonl'), out_dir=Path('data/processed'))"
```

## Evaluate and gate

```bash
# full eval over the golden set (needs ANTHROPIC_API_KEY for the judge; local Ollama for generation)
.venv/bin/python -m grc_rag.evaluate

# the keyless tiers the CI gate runs on every PR
.venv/bin/python -m grc_rag.gate --tier1
.venv/bin/python -m grc_rag.gate --check-scorecard --max-age-days 30
```

## The web UI

The frontend makes cite-or-refuse visible. It is a standalone Vite + React + TypeScript
package that talks to the FastAPI boundary over HTTP and owns no cite-or-refuse logic of its
own. It wears a governed type + token system (Source Serif 4 for the answer and quoted clauses,
Public Sans for UI, IBM Plex Mono for ids and scores), bound throughout to live `AskResponse`
data ([ADR-0017](./adr/0017-console-redesign-live-data.md)).

```bash
# 1. the API (from the repo root) — needs the built index + a local Ollama generator
uvicorn grc_rag.api:app --port 8000

# 2. the UI (from ui/)
cp .env.example .env.local      # set VITE_API_BASE if the API isn't on :8000
npm install
npm run dev                     # http://localhost:5173
```

What you see:

1. **Ask, and watch it retrieve.** While the request is in flight, a six-stage pipeline
   (Embed → Hybrid → Fuse → Re-rank → Gate → Generate) animates with a real elapsed-time
   ticker — the actual stages the backend runs, shown as the loading state rather than a
   spinner. It claims no per-query scores it cannot prove.
2. **Read a grounded answer.** Each claim ends in a citation chip labelled with its clause
   ("EU AI Act — Article 5"). Click a chip and the exact clause text expands inline — no second
   request, because the API resolves citations at the edge and ships the text in the response.
3. **Open "How it answered."** A panel, collapsed by default, shows the ranked clauses, their
   real scores, and the query latency from `AskResponse`. Honest disclosure rather than a black
   box.
4. **See the eval scorecard.** A collapsible strip carries the project's measured golden-set
   numbers (faithfulness 0.924, recall@10 0.889, refusal 5/5), labelled "Measured on the golden
   set" — system-level trust evidence, not per-answer telemetry.
5. **Ask something out of corpus.** The refusal is a first-class, calm state (`role="status"`),
   visually distinct from a network error (`role="alert"`), and carries no fabricated citation.

The frontend models the response as one discriminated state — `idle | answer | refusal |
error` — so each case renders unambiguously. The design decisions behind it are in
[ADR-0015](./adr/0015-fastapi-boundary.md), [ADR-0016](./adr/0016-react-ui.md), and
[ADR-0017](./adr/0017-console-redesign-live-data.md).

A static production bundle builds with `npm run build` into `ui/dist/`, deployable to any
static host with `VITE_API_BASE` pointed at the deployed API.
