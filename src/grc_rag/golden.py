"""The golden set — a hand-verified answer key, and the evaluation harness's measuring instrument.

Every number the eval reports (recall@10, faithfulness, the CI gate) is only as honest as
the data it is measured against. A metric computed against a sloppy or self-referential
answer key is theatre: "measuring" faithfulness against an answer copied from the context
yields ≈1.0 by construction and proves nothing. The golden set is the antidote — a small set
of questions where a *human* has verified, by reading the actual standard, which clause(s)
answer each one.

Two design choices make it trustworthy:

* **Relevance is keyed on the stable ``clause_label``, not the ``chunk_id``.** A
  ``chunk_id`` (``eu-ai-act::79``) is an *ephemeral* index — it already shifted once when
  re-ingestion went 283 → 450 chunks. Pinning the answer key to chunk ids would silently
  rot on the next re-chunk. We pin it instead to the human ``clause_label`` the
  structure-aware splitter attaches (``"EU AI Act — Article 5"``) — that is what a citation
  *resolves to* and what a human can re-verify. A retrieved chunk is "relevant" to an item
  iff its ``clause_label`` is one of the item's ``expected_clause_labels`` (guarded by
  ``expected_doc``).

* **Out-of-corpus items are first-class.** An item's ``kind`` is ``in_corpus`` (must answer,
  citing an expected clause) or ``out_of_corpus`` (must *refuse*). The harness scores the
  latter by refusal correctness, so they carry **zero** expected clauses by construction —
  and validation enforces that, because an out-of-corpus item that named a clause would be a
  contradiction in the answer key.

Everything here is pure and immutable, and validation fails fast: a malformed line raises
``ValueError`` loudly (naming the offending line) rather than being skipped, because a
silently-dropped bad line is a silently-wrong metric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from grc_rag.chunking import Chunk

# Bump on any field change; the loader rejects an unknown version rather than mis-parsing an
# old line against a new shape. The id (not just an int) makes a stale file obvious at a glance.
GOLDEN_SCHEMA_VERSION = "golden/v1"

GoldenKind = Literal["in_corpus", "out_of_corpus"]
_KINDS: frozenset[str] = frozenset(("in_corpus", "out_of_corpus"))


@dataclass(frozen=True)
class GoldenItem:
    """One hand-verified evaluation question. Immutable.

    ``expected_clause_labels`` are the **stable human labels** (e.g. ``"EU AI Act — Article
    5"``) a correct answer must cite — verified by a human reading the source, never scraped.
    They are empty for ``out_of_corpus`` items, whose correct behaviour is refusal.
    ``expected_doc`` (``"eu-ai-act"`` / ``"nist-ai-rmf"`` / ``"nist-genai-profile"``) guards
    the relevance join so a label can't match a chunk from the wrong document. ``notes`` may
    record provenance or an ISO/IEC 42001 clause-*ID* cross-reference (lawful) but **never**
    ISO text.
    """

    id: str
    question: str
    kind: GoldenKind
    expected_doc: str | None
    expected_clause_labels: tuple[str, ...]
    notes: str = ""
    schema_version: str = GOLDEN_SCHEMA_VERSION


def is_relevant(chunk: Chunk, item: GoldenItem) -> bool:
    """True iff ``chunk`` satisfies ``item``.

    A chunk is relevant when its ``clause_label`` is one of the item's
    ``expected_clause_labels`` *and* (when the item sets ``expected_doc``) its ``doc_id``
    matches. An unlabelled chunk (``clause_label is None``) is never relevant — it carries no
    clause to verify against. ``out_of_corpus`` items have no expected clauses, so nothing is
    ever relevant to them. Pure.
    """
    if chunk.clause_label is None:
        return False
    if item.expected_doc is not None and chunk.doc_id != item.expected_doc:
        return False
    return chunk.clause_label in item.expected_clause_labels


def validate_item(raw: dict) -> GoldenItem:
    """Build a :class:`GoldenItem` from a parsed JSON object, validating at the boundary.

    Never trusts the file contents. Raises ``ValueError`` on: an unknown ``schema_version``;
    a blank ``id`` or ``question``; an unknown ``kind``; a non-list ``expected_clause_labels``
    or non-string labels; an ``in_corpus`` item missing ``expected_doc`` or with no expected
    clauses; or an ``out_of_corpus`` item that carries an ``expected_doc`` or any expected
    clause (a contradiction — a refusal question has no citing clause).
    """
    version = raw.get("schema_version")
    if version != GOLDEN_SCHEMA_VERSION:
        raise ValueError(f"unknown schema_version {version!r}: expected {GOLDEN_SCHEMA_VERSION!r}")

    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError(f"item id must be a non-empty string, got {item_id!r}")

    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"[{item_id}] question must be a non-empty string")

    kind = raw.get("kind")
    if kind not in _KINDS:
        raise ValueError(f"[{item_id}] unknown kind {kind!r}: expected one of {sorted(_KINDS)}")

    labels_raw = raw.get("expected_clause_labels", [])
    if not isinstance(labels_raw, list) or not all(isinstance(label, str) for label in labels_raw):
        raise ValueError(f"[{item_id}] expected_clause_labels must be a list of strings")
    labels = tuple(labels_raw)

    expected_doc = raw.get("expected_doc")
    if expected_doc is not None and not isinstance(expected_doc, str):
        raise ValueError(f"[{item_id}] expected_doc must be a string or null")

    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise ValueError(f"[{item_id}] notes must be a string")

    if kind == "in_corpus":
        if not expected_doc:
            raise ValueError(f"[{item_id}] in_corpus item must set expected_doc")
        if not labels:
            raise ValueError(f"[{item_id}] in_corpus item must list ≥1 expected_clause_labels")
    else:  # out_of_corpus
        if expected_doc is not None:
            raise ValueError(f"[{item_id}] out_of_corpus item must not set expected_doc")
        if labels:
            raise ValueError(
                f"[{item_id}] out_of_corpus item must have no expected_clause_labels "
                f"(its correct behaviour is refusal), got {labels}"
            )

    return GoldenItem(
        id=item_id,
        question=question,
        kind=kind,  # type: ignore[arg-type]  # narrowed by the membership check above
        expected_doc=expected_doc,
        expected_clause_labels=labels,
        notes=notes,
        schema_version=version,
    )


def load_golden_set(path: Path) -> tuple[GoldenItem, ...]:
    """Read a JSONL golden file, validate every line, return the frozen tuple.

    Blank lines are ignored. Raises ``ValueError`` — naming the **1-based line number** — on
    the first line that is invalid JSON or fails :func:`validate_item`, and on a duplicate
    item ``id``. A bad answer key must fail the build, never skew a metric silently.
    """
    items: list[GoldenItem] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {error}") from error
            try:
                item = validate_item(raw)
            except ValueError as error:
                raise ValueError(f"{path}:{line_no}: {error}") from error
            if item.id in seen_ids:
                raise ValueError(f"{path}:{line_no}: duplicate item id {item.id!r}")
            seen_ids.add(item.id)
            items.append(item)
    return tuple(items)


def count_by_kind(items: Sequence[GoldenItem]) -> dict[GoldenKind, int]:
    """Tally items by kind — surfaced in the eval report header. Pure."""
    counts: dict[GoldenKind, int] = {"in_corpus": 0, "out_of_corpus": 0}
    for item in items:
        counts[item.kind] += 1
    return counts
