# EVAL-008 — Faithfulness mean silently drops an item when the *relevancy* judge errors

**Priority:** P2 · **Type:** correctness / eval-harness · **Opened:** 2026-07-11
(surfaced while reconciling why the scorecard mean differed from a per-item diagnostic)

## Symptom
The committed faithfulness number can be **biased by an unrelated failure**: if the *answer
relevancy* judge call throws for an item, that item is excluded from the *faithfulness* mean too —
even though its faithfulness verdict parsed fine.

## Root cause
In `run_eval` (`src/grc_rag/evaluate.py`), the faithfulness and relevancy judge calls share one
`try/except`:

```python
try:
    verdict = judge_faithfulness(answer, cited, client=judge_client)
    relevancy = judge_answer_relevancy(item.question, answer, client=judge_client)
except ValueError:
    judge_errors += 1
    continue          # <-- skips BOTH metrics for this item
faiths.append(verdict.faithfulness)
rels.append(relevancy)
```

A relevancy parse error (the second call) discards a perfectly good faithfulness verdict (the
first). Faithfulness is then a mean over a *different* subset than "all in-corpus items", and the
`judge_errors` count conflates faithfulness and relevancy failures. In the 2026-07-11 refresh
`judge_errors == 0`, so the committed 0.924 is unaffected — but the coupling is a latent
correctness bug that will bite a future refresh.

## Fix
Score the two metrics independently so one judge's failure can't drop the other's good verdict:

- Wrap each judge call in its own `try/except`; append to `faiths` / `rels` independently.
- Track `faithfulness_judge_errors` and `relevancy_judge_errors` separately (or a per-metric
  denominator), so the scorecard/report can state each mean's true `n`.
- Keep fail-fast semantics inside each judge; only the harness-level batching tolerates a single
  bad verdict.

## Acceptance criteria
- [ ] A relevancy judge error no longer removes an item from the faithfulness mean (add a unit test
      with a stub judge that raises on relevancy only).
- [ ] The report/scorecard denominators reflect each metric's actual judged count.
- [ ] Existing tests still pass; the 2026-07-11 numbers are unchanged (0 judge errors that run).

## Related
[[EVAL-001]] (the refresh during which this was noticed). Low blast radius today, but it silently
distorts faithfulness whenever the judge has any parse errors.
