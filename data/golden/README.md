# Golden set — the hand-verified answer key

`golden-set.jsonl` is the measuring instrument for Phase 3: a set of questions where the
**correct citing clause(s)** have been verified against the actual source text. Every Phase-3
number (recall@10, faithfulness, the CI gate) is computed against this file, so it is held to
the same standard as the system itself — **cite-or-refuse**: an item claims only what the
source actually says.

Schema + loader + relevance predicate: [`src/grc_rag/golden.py`](../../src/grc_rag/golden.py).
Spec: [`builddocs/phase-3/PRD-P3-08-golden-set.md`](../../docs/build/phase-3/PRD-P3-08-golden-set.md).

## Schema (`golden/v1`)

One JSON object per line:

| field | meaning |
|---|---|
| `id` | stable, unique item id (e.g. `g-eu-art5-1`) |
| `question` | a self-contained question a compliance professional would ask |
| `kind` | `in_corpus` (must answer, citing a clause) or `out_of_corpus` (must refuse) |
| `expected_doc` | `eu-ai-act` / `nist-ai-rmf` / `nist-genai-profile`; `null` for out-of-corpus |
| `expected_clause_labels` | the **stable clause label(s)** a correct answer must cite; `[]` for out-of-corpus |
| `notes` | provenance / what in the clause grounds the answer (an ISO clause-*ID* ref is lawful; **never** ISO text) |
| `schema_version` | `golden/v1` |

**Relevance is keyed on `clause_label`, not `chunk_id`** — a `chunk_id` is an ephemeral index
that shifts on every re-chunk, whereas the human `clause_label` (`"EU AI Act — Article 5"`) is
what a citation resolves to and what a human can re-verify. `is_relevant(chunk, item)` is the
join the IR metrics use.

## Current tranche (seed)

This is a **living tranche**, growing toward 50–200. It is **not** blocked on full curation —
the schema, loader, and metrics work at any size.

- **41 items**: **36 in-corpus** + **5 out-of-corpus**.
- **20 distinct clauses**: 13 EU AI Act articles/annexes (24 items), 5 NIST GenAI Profile
  subcategories (10 items), 2 NIST AI RMF subcategories (2 items).
- The 5 out-of-corpus items (ISO/IEC 42001 clause, SOC 2, GPT-4 pricing, HIPAA, 2026 Australian
  Open) are inherited verbatim from the [Phase-1 probe set](../../docs/build/phase-1/probe-set.md);
  the in-corpus items **evolve** that probe set's `expected_kw` proxy into verified clause labels.

### How this tranche was built

Curated by a **multi-agent workflow** (2026-06-13), then **adversarially verified**:

1. Per-clause **curator** agents drafted questions grounded *only* in each clause's real corpus
   text (cite-or-refuse discipline — no question the text doesn't answer).
2. A **strict adversarial verifier** agent audited each candidate against *only* its cited
   clause and rejected any that were generic, deictic ("this article"), answer-leaking, or not
   actually answered by the clause. 37 proposed → 36 kept → 1 rejected (an answer-leaking item).

Every kept label is checked to resolve to a real `clause_label` in the corpus
(`RUN_INTEGRATION=1 pytest tests/test_golden.py::test_seed_tranche_labels_exist_in_corpus`).

## Adding an item (the rubric)

An item earns its place only if:

- **Verified, not guessed.** Read the clause; confirm it actually answers the question. If you
  can't point at the clause, the item doesn't go in.
- **Self-contained + discriminating.** No "what does Article 5 say" crutches — ask about the
  substance, and make the cited clause the *right* answer, not one of many.
- **Stable label.** `expected_clause_labels` must be a real `clause_label` the corpus produces.
- **No ISO text.** Clause-ID references in `notes` are fine; ISO/IEC 42001 text is never stored.

### Coverage still open (growth path toward 50–200)

NIST AI RMF is under-represented (most subcategories are one-line headers, too thin to ground a
discriminating question — only the substantive `MANAGE 4.3` / `GOVERN 6.2` are in so far). Widen
with more GenAI Profile actions (`MS-*`, `MG-*`) and EU AI Act Articles 1–2, 17–25, 40–49
(notified bodies / conformity), 51–55 (GPAI models), and the remaining Annexes.
