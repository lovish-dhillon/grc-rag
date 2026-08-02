# EVAL-006 — Eval measures at k=10 but the deployed API/CLI generate at k=6 (scorecard is optimistic)

**Priority:** P1 · **Type:** correctness / measurement-honesty · **Opened:** 2026-07-11
(surfaced during the EVAL-001 / prompt-v3 investigation)

## Symptom
The committed scorecard's faithfulness (0.924) and recall@10 (0.889) are measured with **more
retrieved context than the live system ever sees**. For a project whose thesis is "the scorecard
reflects the deployed system", the headline numbers are measured under a more generous setting
than production.

## Root cause
The retrieval `k` differs between the eval harness and the deployed request path:

- **Eval** — `run_eval` defaults to `k=10` and `gate --judge` passes `k=10`
  (`src/grc_rag/evaluate.py`), so both faithfulness *and* recall are measured over the top-**10**
  reranked chunks.
- **Deployment** — `answer_with_enforcement(k=6)` (`src/grc_rag/enforce.py:91`) and
  `create_app(k=6)` (`src/grc_rag/api.py:156`) generate from the top-**6** reranked chunks. The
  `query` CLI and `build_default_app` inherit the same default.

`RerankingRetriever.retrieve(k=…)` honours the passed `k` and overrides its `top_k`
(`rerank.py:132-147`), so a grounding clause ranked 7–10 is:
- retrieved and countable in recall@10, **and** available to the *eval* generator (k=10), but
- **not** passed to the *deployed* generator (k=6) → the live system may refuse or mis-cite a
  question the scorecard counts as answered/faithful.

This eval↔production skew (10 vs 6) partly explains why the live demo refuses a bit more than the
eval implies.

## Fix — pick one k and use it everywhere (record as an ADR)
- **A. Measure at the deployed k (k=6).** Most honest: change the eval/gate default to `k=6` so
  the scorecard reflects what users get. Re-run the judge; expect faithfulness/recall to move
  (possibly down) — commit the real numbers.
- **B. Deploy at the eval k (k=10).** Give the deployed generator the same 10 chunks the eval
  scores. Costs a little latency and prompt length; re-check faithfulness (more context can help
  or hurt grounding).
- **C. Decouple deliberately** and document why (e.g. recall is an IR diagnostic at 10, generation
  is gated at 6) — but then the scorecard must state the generation-k it was measured at.

Recommendation: **A** — align the measured number to the deployed number; it is the cleanest fit
with the "scorecard reflects the deployed system" claim.

## Acceptance criteria
- [ ] Eval, gate, API, CLI, and enforcement use a single, explicit retrieval `k` (or the scorecard
      explicitly records the generation-k it was measured at).
- [ ] The committed scorecard is re-measured under the reconciled `k` and docs updated.
- [ ] An ADR records the chosen `k` and the tradeoff.

## Related
[[EVAL-007]] (some grounding clauses aren't in the top-k at all — a retrieval-recall problem, not
just a k-alignment one).
