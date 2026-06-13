# ADR-0012 — Versioned prompts; v2 accepted with a known tradeoff

- **Status:** Accepted (with a recorded tradeoff)
- **Date:** 2026-06-13

## Context

Prompts are where a lot of behaviour lives, and they change often. They should be revisable
under review without touching Python, and every answer should record which prompt produced
it. Separately, the v1 cite-or-refuse prompt scored faithfulness at 0.885, just under the
0.90 gate, with the 7B generator over-claiming on scope.

## Decision

Load prompts from files in `prompts/<id>.txt` as versioned config, and stamp each `Answer`
with its `prompt_version`. Author a stricter `cite-or-refuse.v2`: every sentence must be
fully grounded in a single cited chunk, no generalising beyond the text, no merging claims
across chunks, omit anything uncertain. Bump `PROMPT_VERSION` to `cite-or-refuse/v2` and keep
v1 frozen on disk.

## Consequences

- Faithfulness rose from 0.885 to 0.905, clearing the gate. Unsupported claims fell from 22
  to 12.
- Answer relevancy regressed from 0.917 to 0.722. The stricter "leave it out if unsure"
  instruction makes the generator answer less fully, so more answers read as partly
  non-responsive. The faithfulness gain (+0.02) is small next to the relevancy loss (−0.20).
- The conclusion is recorded honestly: prompt-tuning alone cannot push both metrics high on a
  local 7B model. A stronger generator is the real fix for both. v2 is kept because it meets
  the explicit faithfulness gate; v1 is one line away if relevancy is later weighted higher.
- Because prompts are versioned config, this whole change is a file swap plus a version
  string, not a code change, and the answer provenance records which prompt ran.

See [04-evaluation.md](../04-evaluation.md) for the full numbers.
