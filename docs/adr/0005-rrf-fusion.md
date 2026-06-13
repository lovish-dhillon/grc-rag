# ADR-0005 — Hybrid retrieval by reciprocal-rank fusion

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

Dense retrieval matches meaning but is blind to exact tokens. In Phase 1 it over-refused the
EU AI Act Article 5 question because the chunk that literally contains "prohibited" ranked
too low to enter the generator's window. BM25 is the natural complement, but dense and BM25
scores live on incomparable scales (cosine in `[-1, 1]` versus an unbounded BM25 sum), so
they cannot simply be added or averaged.

## Decision

Run both retrievers and fuse their results by reciprocal-rank fusion:
`score(id) = Σ 1 / (k_rrf + rank)` across the two ranked lists, with `k_rrf = 60`. Fusion
uses rank positions, not raw magnitudes. Per-retriever provenance (`dense_rank`, `bm25_rank`)
is kept on the result so the fusion is inspectable.

## Alternatives considered

- **Weighted score averaging.** Rejected: requires per-retriever, per-corpus normalisation to
  make the scales comparable, which is exactly the kind of tuning knob this project avoids.
- **Dense-only.** Rejected: it is the cause of the Article 5 over-refusal.

## Consequences

- RRF is distribution-free with a single constant (the literature default 60), so there is
  nothing per-corpus to calibrate.
- Concrete fix: the Article 5 "prohibited" chunk rises from dense rank 4 to hybrid rank 1
  (BM25 ranks it first; RRF carries it up), which puts it inside the generator's window and
  removes the over-refusal.
- The fused result is a drop-in for the retriever Protocol, so nothing downstream changes.
