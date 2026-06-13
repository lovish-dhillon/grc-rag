# ADR-0003 — Token-based chunking with structure-aware labelling

- **Status:** Accepted
- **Date:** 2026-06-11 (chunking), extended 2026-06-12 (structure-aware labelling)

## Context

Chunk size has to be fixed before any query runs, and it shapes everything downstream. Two
separate problems: how big a chunk is, and how a chunk knows which clause it came from so a
citation can name "EU AI Act — Article 5" instead of an opaque index.

## Decision

Chunk in tokens, not characters: a 700-token window with 100-token overlap, using `tiktoken`
(the same unit the embedder and LLMs bill in). Overlap means a sentence at a boundary
survives intact in at least one chunk. Each `Chunk` is a frozen dataclass carrying full
provenance (`chunk_id`, `doc_id`, `start_token`, `clause_label`).

Before chunking, split each document along its real structure (`structure.py`): detect
Articles, Annexes, and RMF subcategories from heading form with heuristic regex anchors, and
label each segment. Every sub-chunk inherits its segment's label. This is heuristics on
heading shape, not a document parser.

## Alternatives considered

- **Character-based chunking.** Rejected: misaligns with how the embedder and generator
  actually tokenise, so sizes drift.
- **A full document parser.** Rejected as over-engineering for three documents of known
  shape; brittle, and more to defend than heuristic anchors with a labelled fallback.

## Consequences

- Citations resolve to human clause labels, which is what makes the output usable for
  compliance work and what the golden set keys on ([ADR-0009](./0009-golden-set.md)).
- Unlabelled preamble and any unrecognised document fall back to a single segment, so nothing
  is dropped.
- The current index is 450 chunks, 76% clause-labelled.
