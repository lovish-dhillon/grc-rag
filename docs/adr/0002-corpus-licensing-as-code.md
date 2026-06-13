# ADR-0002 — Corpus licensing enforced as code

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

The corpus should cover the standards an AI-governance question is likely to touch, which
includes ISO/IEC 42001. But 42001 is copyrighted and paywalled. Ingesting or shipping its
text would be a licensing breach, and doing AI governance work while breaching a standards
licence is not a good look for a tool meant to demonstrate exactly that competence. "We were
careful" is not a control; conventions get violated under time pressure.

## Decision

Index only freely-redistributable standards: NIST AI RMF, the NIST GenAI Profile, and the EU
AI Act. Encode the boundary as an allowlist (`ALLOWED_SOURCES`) with a deny-guard
(`_assert_allowed(doc_id)`) that every ingestion entrypoint routes through and that raises
unless the source is explicitly cleared. ISO/IEC 42001 may still be referenced by its clause
identifiers, since a clause number is a factual pointer, not the standard's content.

## Alternatives considered

- **Policy in a doc.** A written rule with no code enforcement. Rejected: it fails open under
  pressure and leaves no evidence it held.
- **Best-effort filtering.** Strip ISO content if detected. Rejected: detection is fuzzy and
  fails open. An allowlist fails closed — anything not cleared is rejected by default.

## Consequences

- Shipping paywalled text is not possible through the normal ingestion path; it would take
  deliberately editing the allowlist. A test asserts ISO is rejected, and the built index
  contains zero lines of ISO text.
- This is a stronger and more honest talking point in a GRC conversation than a promise.
- The crosswalk capability (mapping answers to 42001 clause IDs) is unaffected, because it
  references identifiers rather than reproducing text.
