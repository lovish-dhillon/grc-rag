# ADR-0004 — Local MiniLM embeddings, no vector database

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

Dense retrieval needs an embedder and a place to keep the vectors. A common shortcut is a
hashing trick that produces vectors with no semantic meaning. The constraints here are
local-first (near-zero cost, no key) and explainable: the retrieval path should be
inspectable rather than hidden behind a managed service.

## Decision

Embed with `sentence-transformers/all-MiniLM-L6-v2`: 384-dimensional, about 90 MB, runs on
CPU, no API key. Unit-normalise every vector in our own code so cosine similarity reduces to
a plain dot product. Store the vectors as a numpy matrix (`embeddings.npz`) with a
row-aligned `index.jsonl`, so row *i* is chunk *i*. Retrieval is a brute-force scan.

## Alternatives considered

- **A vector database** (Chroma, Pinecone, FAISS). Rejected for this scale: ~450 chunks make
  approximate nearest-neighbour search pointless. Brute force is exact, fast enough, and adds
  no dependency or service to run. Revisit if the corpus grows past ~10k chunks.
- **Library-flag normalisation.** Rejected in favour of normalising explicitly, so the
  guarantee is visible in our code and unit-testable rather than implied by a flag.

## Consequences

- Retrieval is exact and deterministic, which makes recall@k a stable CI signal.
- No managed service, no key, no per-query cost on the embedding side.
- The numpy matrix is committed, so a fresh checkout retrieves without re-embedding.
- Scaling beyond in-memory brute force is a known future decision, not a present need.
