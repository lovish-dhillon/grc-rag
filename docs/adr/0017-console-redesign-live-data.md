# ADR-0017 — Console redesign bound to live data

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

The [React UI](./0016-react-ui.md) was functionally honest but visually plain. A design system
defined a richer console: a governed type system, a token palette, a six-stage retrieval
**motion graphic**, ¶ citation chips, and a collapsible **eval scorecard**. Its prototypes,
however, ran on offline *fixtures* — fabricated per-query retrieval lanes and a scorecard shown
under every answer. Importing those wholesale would reintroduce exactly the false assurance this
project exists to prevent ([ADR-0001](./0001-cite-or-refuse-invariant.md)).

## Decision

Adopt the full **visual** system but bind every rendered value to the live `AskResponse`, never to
fixtures.

1. **Type + tokens.** Source Serif 4 (display + quoted clause text), Public Sans (UI), IBM Plex
   Mono (ids/scores), the warm-paper + regulatory-blue palette, 8px buttons, a search-glyph ask
   field, and a header with wordmark, corpus tags, and the CI-gate badge — all in one `styles.css`.
   The webfonts are flagged in-file as a substitution for the original system stack.
2. **Retrieval pipeline = honest loading state.** The six real stages (Embed → Hybrid → Fuse →
   Re-rank → Gate → Generate) animate while the request is in flight, with a **real elapsed-time
   ticker**. The fixture's fabricated per-query candidate scores were dropped — the API returns no
   lane breakdown, and inventing one is the precise dishonesty the project forbids. The real ranked
   clauses and scores appear afterward in "How it answered", from `AskResponse.retrieved`.
3. **Eval scorecard = system-level, labelled.** It shows the committed golden-set numbers
   (faithfulness 0.905, recall@10 0.889, refusal 5/5, relevancy 0.722) from a typed `scorecard.ts`
   that mirrors `data/eval/scorecard.json` and the evaluation doc, headed "Measured on the golden
   set" and collapsed by default — not presented as per-answer telemetry. MRR/nDCG are omitted (no
   published values to cite).
4. **Citation chips show the real corpus labels** (e.g. "EU AI Act — Article 5"), not the fixture's
   reworded form.

## Alternatives considered

- **Port the design's offline fixtures for a richer demo.** Rejected: it renders invented
  per-query retrieval scores as if measured — the false assurance [ADR-0001](./0001-cite-or-refuse-invariant.md)
  forbids.
- **Scorecard under each answer as per-answer metrics.** Rejected: it is a golden-set aggregate;
  showing it as per-answer would mislead. Kept, but labelled as system-level evidence.
- **Keep system fonts.** Rejected: the governed serif/Public Sans voice is the redesign's point;
  the substitution is flagged rather than hidden.

## Consequences

- The console now reads as a considered product, while every number on screen is real: the answer
  and citations from the live pipeline, the retrieval scores from `AskResponse`, the scorecard from
  the committed eval run.
- The M13 component tests still pass (12) after scoping the now-shared `role="status"` (header gate
  badge and refusal) by accessible name and updating the in-flight copy to "Retrieving…".
- No new runtime dependency; `pyproject.toml` untouched; the static bundle still builds to
  `ui/dist/`. Verified end to end against the live API: a cited Article 5 answer (~30 s), an
  out-of-corpus refusal (222 ms, gate short-circuit), clause click-through, and the expanded
  scorecard.
