"""Structure-aware chunking — split along the document's own clauses, and label them.

Phase-1 chunking slides a fixed token window over the raw text, so a citation resolves to
``eu-ai-act::137`` — an index no compliance reader can act on — and a window can cut straight
across an Article boundary, severing an obligation from the conditions that qualify it. This
module splits along the document's *real* structure instead: Articles and Annexes for the EU
AI Act, the GOVERN / MAP / MEASURE / MANAGE subcategories for the NIST AI RMF, the
``GV/MP/MS/MG-x.y`` subcategories for the NIST Generative AI Profile. Each resulting chunk is a
coherent unit *and* carries a human ``clause_label`` (e.g. ``"EU AI Act — Article 5"``), which
is what turns a citation into an auditable click-through.

Detection is deliberately heuristic and transparent — anchored regexes over the *form* of a
heading line (``Article 5``, ``ANNEX III``, ``GOVERN 1.1``), not a legal-grammar parser. A
heading starts a new segment only when its label *changes*, so consecutive same-subcategory
lines (``GV-1.1-001``, ``GV-1.1-002`` …) group naturally. When a document has no detectable
structure — or is one we don't have a labeller for — the whole text becomes a single
unlabelled segment, so unstructured input still chunks: this path **fails safe**, not loud.

A segment longer than the token budget is sub-split by the Phase-1 :func:`grc_rag.chunking.
chunk_document` (overlap and all), but never *across* a boundary — every sub-chunk keeps its
segment's label. Everything here is pure and immutable, with the same fail-fast boundary
checks as ``chunking.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from grc_rag.chunking import Chunk, chunk_document

# --------------------------------------------------------------------------- #
# Heading detection — one labeller per source. A labeller maps a single line to a clause label
# if (and only if) that line is a heading of the expected form, else None. `\s` matches the
# EUR-Lex non-breaking space (U+00A0) seen between "Article"/"ANNEX" and the number.
# --------------------------------------------------------------------------- #
_EU_ARTICLE = re.compile(r"^Article\s+(\d+[a-z]?)\b")
_EU_ANNEX = re.compile(r"^ANNEX\s+([IVXLCDM]+)\b")
_RMF_SUBCATEGORY = re.compile(r"^(GOVERN|MAP|MEASURE|MANAGE)\s+(\d+(?:\.\d+)?)\b")
_GENAI_SUBCATEGORY = re.compile(r"^(GV|MP|MS|MG)-(\d+\.\d+)-\d+\b")


def _eu_ai_act_label(line: str) -> str | None:
    article = _EU_ARTICLE.match(line)
    if article:
        return f"EU AI Act — Article {article.group(1)}"
    annex = _EU_ANNEX.match(line)
    if annex:
        return f"EU AI Act — Annex {annex.group(1)}"
    return None


def _nist_ai_rmf_label(line: str) -> str | None:
    match = _RMF_SUBCATEGORY.match(line)
    return f"NIST AI RMF — {match.group(1)} {match.group(2)}" if match else None


def _nist_genai_label(line: str) -> str | None:
    match = _GENAI_SUBCATEGORY.match(line)
    return f"NIST GenAI Profile — {match.group(1)}-{match.group(2)}" if match else None


# doc_id → labeller. A doc_id absent here has no known structure → single unlabelled segment.
_LABELLERS: dict[str, Callable[[str], str | None]] = {
    "eu-ai-act": _eu_ai_act_label,
    "nist-ai-rmf": _nist_ai_rmf_label,
    "nist-genai-profile": _nist_genai_label,
}


@dataclass(frozen=True)
class Segment:
    """A labelled structural region of a document, before token-windowing.

    ``clause_label`` is ``None`` for text outside any recognised structure (a preamble, or a
    whole document with no detectable headings).
    """

    clause_label: str | None
    text: str


def detect_segments(doc_id: str, text: str) -> tuple[Segment, ...]:
    """Split ``text`` into labelled segments at heading-label changes. Pure.

    A line is a boundary when the source's labeller returns a label *different* from the
    current segment's — so each Article starts a new segment, while consecutive lines under one
    NIST subcategory stay together. Text before the first heading (or an entire document with no
    headings, or an unknown ``doc_id``) becomes a single ``clause_label=None`` segment.
    """
    label_of = _LABELLERS.get(doc_id)
    if label_of is None:
        stripped = text.strip()
        return (Segment(clause_label=None, text=stripped),) if stripped else ()

    segments: list[Segment] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            segments.append(Segment(clause_label=current_label, text=body))

    for line in text.splitlines():
        label = label_of(line.lstrip())
        if label is not None and label != current_label:
            flush()
            current_label = label
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return tuple(segments)


def split_structured(
    doc_id: str,
    text: str,
    *,
    target_tokens: int = 700,
    overlap_tokens: int = 100,
) -> tuple[Chunk, ...]:
    """Structure-aware replacement for :func:`grc_rag.chunking.chunk_document`.

    Detects clause segments, then token-windows each one independently (so a long Article is
    still split with overlap, but a window never spans two Articles). Every emitted chunk is
    tagged with its segment's ``clause_label``; ``chunk_id`` stays the globally-sequential
    ``doc_id::index``. ``start_token`` is the offset *within its segment*. Pure; returns a new
    tuple. Fails fast on the same bad boundaries as the flat chunker.
    """
    # Fail fast at the boundary — these mirror chunk_document, and must hold even when the text
    # is empty (so no segment ever reaches the chunker to validate them for us).
    if not doc_id or not doc_id.strip():
        raise ValueError("doc_id must be a non-empty string")
    if target_tokens <= 0:
        raise ValueError(f"target_tokens must be > 0, got {target_tokens}")
    if not 0 <= overlap_tokens < target_tokens:
        raise ValueError(
            f"overlap_tokens must be in [0, target_tokens); "
            f"got overlap={overlap_tokens}, target={target_tokens}"
        )

    chunks: list[Chunk] = []
    index = 0
    for segment in detect_segments(doc_id, text):
        for piece in chunk_document(
            doc_id, segment.text, target_tokens=target_tokens, overlap_tokens=overlap_tokens
        ):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}::{index}",
                    doc_id=doc_id,
                    text=piece.text,
                    token_count=piece.token_count,
                    start_token=piece.start_token,
                    clause_label=segment.clause_label,
                )
            )
            index += 1
    return tuple(chunks)
