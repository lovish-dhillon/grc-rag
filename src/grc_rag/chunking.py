"""Token-based chunking — turn a long source document into retrievable units.

A *chunk* is the atom of retrieval: the system can only ever cite, and answer
from, a whole chunk. So chunk size is a precision/recall tradeoff baked in before
a single query runs:

* Too LARGE  → the relevant sentence is buried in unrelated text. Retrieval still
  finds the chunk (recall holds), but the answer span is diluted by noise and
  precision drops. The LLM also pays for tokens it doesn't need.
* Too SMALL  → you slice a definition or a cross-reference in half and lose the
  context that made it answerable at all.

We target ~500-800 tokens with ~100 tokens of OVERLAP between neighbours. The
overlap is insurance: a sentence that straddles a boundary still survives intact
inside at least one chunk, so we never lose an answer to an unlucky cut point.

Why tokens, not characters or words? Because the two components that consume a
chunk — the embedding model and the LLM — both measure text in tokens. Sizing in
the same unit they bill and truncate in is the only honest way to reason about
"how big is this chunk".

Everything here is pure and immutable: ``chunk_document`` returns a NEW tuple of
frozen ``Chunk`` objects and never mutates its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

# cl100k_base is the tokenizer family used by current OpenAI + many embedding
# models; it is a reasonable, widely-compatible default for *sizing*. (The
# generator/embedder we plug in later may use a different exact vocabulary; for
# chunk sizing we only need a stable, representative token count.)
_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of a source document.

    ``chunk_id`` is globally unique and human-readable (``doc_id::index``) so a
    citation can point straight back here. ``start_token`` records where in the
    source this chunk began — provenance that makes debugging and de-duplication
    possible later. ``clause_label`` is an optional human label for the structural
    unit the chunk came from (e.g. ``"EU AI Act — Article 5"``), populated by the
    structure-aware splitter (:mod:`grc_rag.structure`); it is ``None`` for flat
    token-window chunks. It is the **last, defaulted** field so older
    ``chunks.jsonl`` lines written before it existed still load (missing key → ``None``)
    and new chunks round-trip it through ``asdict``.
    """

    chunk_id: str
    doc_id: str
    text: str
    token_count: int
    start_token: int
    clause_label: str | None = None


def count_tokens(text: str) -> int:
    """Number of tokens in ``text`` under the sizing tokenizer."""
    return len(_ENCODING.encode(text))


def chunk_document(
    doc_id: str,
    text: str,
    *,
    target_tokens: int = 700,
    overlap_tokens: int = 100,
) -> tuple[Chunk, ...]:
    """Split one document into overlapping, token-sized chunks.

    Slides a fixed window of ``target_tokens`` across the document, advancing by
    ``target_tokens - overlap_tokens`` each step so consecutive chunks share
    ``overlap_tokens`` of context.

    Returns a new tuple of :class:`Chunk`; the input is never mutated. An empty
    or whitespace-only document yields an empty tuple.
    """
    # Boundary validation — fail fast and loudly rather than emit silent garbage.
    if not doc_id or not doc_id.strip():
        raise ValueError("doc_id must be a non-empty string")
    if target_tokens <= 0:
        raise ValueError(f"target_tokens must be > 0, got {target_tokens}")
    if not 0 <= overlap_tokens < target_tokens:
        raise ValueError(
            f"overlap_tokens must be in [0, target_tokens); "
            f"got overlap={overlap_tokens}, target={target_tokens}"
        )

    token_ids = _ENCODING.encode(text)
    if not token_ids:
        return ()

    stride = target_tokens - overlap_tokens
    chunks: list[Chunk] = []
    index = 0
    for start in range(0, len(token_ids), stride):
        window = token_ids[start : start + target_tokens]
        chunk_text = _ENCODING.decode(window).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}::{index}",
                    doc_id=doc_id,
                    text=chunk_text,
                    token_count=len(window),
                    start_token=start,
                )
            )
            index += 1
        # The window already reached the end of the document — stop before the
        # stride creates a redundant, mostly-overlapping tail chunk.
        if start + target_tokens >= len(token_ids):
            break

    return tuple(chunks)
