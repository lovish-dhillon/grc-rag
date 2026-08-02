# EVAL-007 — Retrieval misses the grounding clause for some in-corpus questions → v3 false refusals

**Priority:** P2 · **Type:** quality / retrieval · **Opened:** 2026-07-11
(surfaced during the EVAL-001 / prompt-v3 investigation)

## Symptom
Under prompt v3, ~4 of 36 in-corpus golden questions **refuse** ("Not supported by the corpus.")
even though the golden set asserts they are answerable from the corpus. This is the *correct*
cite-or-refuse behaviour given what retrieval returned — but it points at retrieval, not the
prompt, as the next quality limit.

## Evidence
From the v3 measurement (`_answer_for` at k=10, judge over cited chunks):

- Refused in-corpus items (softened v3): `[04] [09] [12] [15]`.
- Two others (`[25] [34]`) were *mis-citing* under v2 (grounding clause absent from the cited
  chunk) and v3 now correctly refuses them instead of fabricating a citation.

For these, the hybrid→rerank stack did not surface the specific clause the answer needed within
the returned set, so the grounded procedure in v3 had nothing to write and refused.

## Root cause (hypothesis to confirm)
Retrieval recall is the limit for these items: the grounding clause is either (a) ranked below the
generation cutoff (see [[EVAL-006]] — deployed k=6 vs eval k=10), or (b) not surfaced at all by
BM25+dense→cross-encoder for these particular queries (a genuine recall miss). recall@10 is 0.889
overall, so ~11% of expected clauses are already missed at 10.

## Fix — investigate the levers, don't paper over
- Per-item retrieval trace for the refusing items: is the expected clause in the candidate pool
  (candidate_k=50) at all? At what rank after rerank? This separates "ranked too low" (raise k /
  improve rerank) from "never retrieved" (improve base retrieval).
- Levers to weigh: raise generation `k` (ties to EVAL-006), tune RRF weighting, increase
  `candidate_k`, revisit chunking so the grounding sentence isn't split across chunks, or a
  stronger embedding model.
- Keep the invariant: a refusal on a genuine retrieval miss is **correct** — the goal is to raise
  recall so fewer answerable questions miss, not to coax the generator into ungrounded answers.

## Acceptance criteria
- [ ] A per-item retrieval diagnostic classifies each false refusal as "ranked too low" vs
      "never retrieved".
- [ ] At least one measured lever (k, RRF weights, candidate_k, chunking, embeddings) is applied
      and re-measured; in-corpus false-refusals drop without lowering faithfulness below 0.90.
- [ ] Any residual refusals are confirmed as genuine retrieval misses and noted honestly.

## Related
[[EVAL-006]] (k skew), [[EVAL-001]] (the v3 fix that surfaced this). A stronger generator is the
other acknowledged ceiling (ADR-0012 / ADR-0019) but does not fix a retrieval miss.
