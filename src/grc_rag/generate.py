"""Cited generation — answer from retrieved chunks, or refuse. The headline invariant.

This is the module that makes grc-rag trustworthy rather than merely fluent. It
enforces two properties a compliance reader depends on:

1. **Grounded + cited.** The answer is synthesised only from the retrieved chunks,
   and every claim carries an inline ``[chunk_id]`` that resolves to a real
   retrieved chunk — so the reader can click straight through to the source clause.
2. **Cite-or-refuse.** When the chunks don't support an answer, the system returns
   the exact sentinel ``"Not supported by the corpus."`` instead of inventing a
   plausible clause number. In GRC a confident wrong citation is *worse* than
   silence: it manufactures false assurance.

It also avoids a common hollow shortcut — *extractive fake generation*, where the
"answer" is the context copied back, which makes a token-overlap faithfulness metric
circular. Here a real LLM generates, and grounding is **verified** against the
retrieved set, not assumed: a citation the model invents (an id we never retrieved)
is dropped, and an answer that survives with zero valid citations is downgraded to a
refusal. That structural verification is the baseline guarantee; threshold-based
refusal and judge-scored faithfulness build on top of it.

The LLM sits behind a one-method :class:`LLMClient` seam, so the local zero-cost
Ollama default and any future API model are interchangeable without touching this
logic — and tests drive it with a deterministic stub, never a live model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from grc_rag.prompts import load_prompt
from grc_rag.retrieve import RetrievedChunk

# The exact refusal. It is a sentinel — compared and emitted verbatim — so keep it
# stable; changing the wording is a (logged) decision, not a casual edit.
REFUSAL = "Not supported by the corpus."

# Bump when the prompt contract changes, so an Answer records which prompt produced it. The
# prompt text lives in a versioned file (``prompts/<id>.txt``, loaded by id — see
# :mod:`grc_rag.prompts`); this version id names that prompt and survives a future re-version.
# v2 (2026-06-13) tightens cite-or-refuse to curb the v1 over-claiming the Phase-3 judge surfaced
# (faithfulness 0.885 / 22 uncited claims): every sentence must be fully grounded in the chunk it
# cites, no scope-generalising, no cross-chunk merging. v1 is kept on disk as frozen history.
PROMPT_VERSION = "cite-or-refuse/v2"

# The on-disk template id. ``cite-or-refuse/v2`` (PROMPT_VERSION) and ``cite-or-refuse.v2``
# (file id) are the same prompt — a filename just can't carry a slash.
_PROMPT_ID = "cite-or-refuse.v2"

# A citation is any [token] that isn't itself nested brackets. We validate the
# captured token against the retrieved ids; this regex only has to find candidates.
_CITATION_RE = re.compile(r"\[([^\[\]]+)\]")


class LLMClient(Protocol):
    """The single seam to the language model. One method, easy to stub or swap."""

    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class Answer:
    """The result of a query. Immutable.

    ``citations`` contains only chunk ids that were actually retrieved — a verified,
    click-through-able set. ``refused`` is ``True`` exactly when ``text`` is the
    refusal sentinel.
    """

    text: str
    citations: tuple[str, ...]
    refused: bool
    prompt_version: str


def build_prompt(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    """Pack the question and the retrieved chunks into the cite-or-refuse template.

    Each chunk is labelled with its ``chunk_id`` so the model can cite it exactly.
    Pure — returns a new string and mutates nothing.
    """
    blocks = "\n\n".join(f"[{rc.chunk.chunk_id}]\n{rc.chunk.text}" for rc in chunks)
    return load_prompt(_PROMPT_ID).format(refusal=REFUSAL, chunks=blocks, question=question)


def parse_citations(text: str, allowed_ids: frozenset[str]) -> tuple[str, ...]:
    """Extract the citations the model actually grounded in.

    Returns only ``[chunk_id]`` tokens present in ``allowed_ids`` (the retrieved
    set), de-duplicated with first-seen order preserved. A citation to an id we
    never retrieved is *dropped* — that's how a fabricated citation is caught. Pure.
    """
    kept: list[str] = []
    for candidate in _CITATION_RE.findall(text):
        if candidate in allowed_ids and candidate not in kept:
            kept.append(candidate)
    return tuple(kept)


def _refuse() -> Answer:
    return Answer(text=REFUSAL, citations=(), refused=True, prompt_version=PROMPT_VERSION)


def generate_answer(
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    client: LLMClient,
) -> Answer:
    """Answer ``question`` from ``chunks`` under the cite-or-refuse contract.

    Refuses (returns the sentinel) when there is nothing to ground an answer in,
    when the model returns the refusal sentinel, or when the model's answer resolves
    to **zero** valid citations (an uncited claim is, by contract, unsupported).
    Raises ``ValueError`` on an empty question.
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not chunks:
        # Nothing retrieved → nothing can be grounded. Refuse without an LLM call.
        return _refuse()

    allowed_ids = frozenset(rc.chunk.chunk_id for rc in chunks)
    text = client.complete(build_prompt(question, chunks)).strip()

    if text == REFUSAL:
        return _refuse()

    citations = parse_citations(text, allowed_ids)
    if not citations:
        # The model answered but cited nothing real (or only fabricated ids).
        # Under cite-or-refuse, an uncited answer is not trustworthy → refuse.
        return _refuse()

    return Answer(text=text, citations=citations, refused=False, prompt_version=PROMPT_VERSION)
