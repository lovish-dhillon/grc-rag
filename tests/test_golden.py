"""Tests for the golden-set schema, loader, and relevance predicate.

All pure and offline: the loader reads tiny fixture JSONL files written to ``tmp_path``, and
``is_relevant`` is exercised against hand-built ``Chunk``s. The one test that touches the real
corpus (every seed label resolves to a real ``clause_label``) is marked ``integration`` and
skipped unless ``RUN_INTEGRATION`` is set.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from grc_rag.chunking import Chunk
from grc_rag.golden import (
    GOLDEN_SCHEMA_VERSION,
    count_by_kind,
    is_relevant,
    load_golden_set,
    validate_item,
)

# A repo-root-relative path to the committed seed tranche.
_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "data" / "golden" / "golden-set.jsonl"


def _in_corpus_raw(**overrides: object) -> dict:
    base = {
        "id": "g-eu-art5",
        "question": "Which AI practices are prohibited?",
        "kind": "in_corpus",
        "expected_doc": "eu-ai-act",
        "expected_clause_labels": ["EU AI Act — Article 5"],
        "notes": "",
        "schema_version": GOLDEN_SCHEMA_VERSION,
    }
    base.update(overrides)
    return base


def _out_of_corpus_raw(**overrides: object) -> dict:
    base = {
        "id": "g-out-iso",
        "question": "What does ISO/IEC 42001 clause 6.1.2 require?",
        "kind": "out_of_corpus",
        "expected_doc": None,
        "expected_clause_labels": [],
        "notes": "ISO text excluded by licence; clause IDs only.",
        "schema_version": GOLDEN_SCHEMA_VERSION,
    }
    base.update(overrides)
    return base


def _chunk(*, label: str | None, doc_id: str = "eu-ai-act") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}::1",
        doc_id=doc_id,
        text="...",
        token_count=1,
        start_token=0,
        clause_label=label,
    )


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def test_golden_item_is_frozen() -> None:
    item = validate_item(_in_corpus_raw())
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.question = "changed"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# validate_item — happy paths
# --------------------------------------------------------------------------- #
def test_validate_in_corpus_happy() -> None:
    item = validate_item(_in_corpus_raw())
    assert item.kind == "in_corpus"
    assert item.expected_doc == "eu-ai-act"
    assert item.expected_clause_labels == ("EU AI Act — Article 5",)


def test_validate_out_of_corpus_happy() -> None:
    item = validate_item(_out_of_corpus_raw())
    assert item.kind == "out_of_corpus"
    assert item.expected_doc is None
    assert item.expected_clause_labels == ()


# --------------------------------------------------------------------------- #
# validate_item — fail-fast (one rule per test)
# --------------------------------------------------------------------------- #
def test_validate_blank_question_raises() -> None:
    with pytest.raises(ValueError, match="question"):
        validate_item(_in_corpus_raw(question="   "))


def test_validate_blank_id_raises() -> None:
    with pytest.raises(ValueError, match="id"):
        validate_item(_in_corpus_raw(id=""))


def test_validate_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        validate_item(_in_corpus_raw(kind="maybe"))


def test_validate_unknown_schema_version_raises() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        validate_item(_in_corpus_raw(schema_version="golden/v99"))


def test_validate_in_corpus_without_labels_raises() -> None:
    with pytest.raises(ValueError, match="expected_clause_labels"):
        validate_item(_in_corpus_raw(expected_clause_labels=[]))


def test_validate_in_corpus_without_doc_raises() -> None:
    with pytest.raises(ValueError, match="expected_doc"):
        validate_item(_in_corpus_raw(expected_doc=None))


def test_validate_out_of_corpus_with_labels_raises() -> None:
    with pytest.raises(ValueError, match="out_of_corpus"):
        validate_item(_out_of_corpus_raw(expected_clause_labels=["EU AI Act — Article 5"]))


def test_validate_out_of_corpus_with_doc_raises() -> None:
    with pytest.raises(ValueError, match="out_of_corpus"):
        validate_item(_out_of_corpus_raw(expected_doc="eu-ai-act"))


def test_validate_non_list_labels_raises() -> None:
    with pytest.raises(ValueError, match="list of strings"):
        validate_item(_in_corpus_raw(expected_clause_labels="EU AI Act — Article 5"))


# --------------------------------------------------------------------------- #
# load_golden_set
# --------------------------------------------------------------------------- #
def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_load_golden_set_happy(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "g.jsonl", [_in_corpus_raw(), _out_of_corpus_raw()])
    items = load_golden_set(path)
    assert len(items) == 2
    assert {i.id for i in items} == {"g-eu-art5", "g-out-iso"}


def test_load_golden_set_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(_in_corpus_raw()) + "\n\n   \n", encoding="utf-8")
    assert len(load_golden_set(path)) == 1


def test_load_golden_set_reports_line_number_on_bad_item(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "g.jsonl",
        [_in_corpus_raw(), _in_corpus_raw(id="g2", question="")],  # line 2 is invalid
    )
    with pytest.raises(ValueError, match=r":2:"):
        load_golden_set(path)


def test_load_golden_set_reports_line_number_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(_in_corpus_raw()) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2:.*invalid JSON"):
        load_golden_set(path)


def test_load_golden_set_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "g.jsonl", [_in_corpus_raw(), _in_corpus_raw()])
    with pytest.raises(ValueError, match="duplicate item id"):
        load_golden_set(path)


# --------------------------------------------------------------------------- #
# is_relevant
# --------------------------------------------------------------------------- #
def test_is_relevant_matching_label_and_doc() -> None:
    item = validate_item(_in_corpus_raw())
    assert is_relevant(_chunk(label="EU AI Act — Article 5"), item) is True


def test_is_relevant_matching_label_wrong_doc() -> None:
    item = validate_item(_in_corpus_raw())
    assert is_relevant(_chunk(label="EU AI Act — Article 5", doc_id="nist-ai-rmf"), item) is False


def test_is_relevant_unlabelled_chunk() -> None:
    item = validate_item(_in_corpus_raw())
    assert is_relevant(_chunk(label=None), item) is False


def test_is_relevant_out_of_corpus_never_matches() -> None:
    item = validate_item(_out_of_corpus_raw())
    assert is_relevant(_chunk(label="EU AI Act — Article 5"), item) is False


# --------------------------------------------------------------------------- #
# count_by_kind
# --------------------------------------------------------------------------- #
def test_count_by_kind() -> None:
    items = (
        validate_item(_in_corpus_raw()),
        validate_item(_in_corpus_raw(id="g2")),
        validate_item(_out_of_corpus_raw()),
    )
    assert count_by_kind(items) == {"in_corpus": 2, "out_of_corpus": 1}


# --------------------------------------------------------------------------- #
# Seed-tranche integrity
# --------------------------------------------------------------------------- #
def test_seed_tranche_loads_and_is_balanced() -> None:
    items = load_golden_set(_GOLDEN_PATH)
    counts = count_by_kind(items)
    assert counts["in_corpus"] >= 15, counts
    assert counts["out_of_corpus"] >= 5, counts
    assert len({i.id for i in items}) == len(items)  # ids unique


@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the built corpus index; set RUN_INTEGRATION=1 to run",
)
def test_seed_tranche_labels_exist_in_corpus() -> None:
    """Every in_corpus expected label must be a real ``clause_label`` in the corpus — a typo'd
    or stale label would make a clause unreachable and quietly depress recall."""
    from grc_rag.ingest import load_chunks_jsonl

    chunks = load_chunks_jsonl(Path("data/processed/chunks.jsonl"))
    real_labels = {c.clause_label for c in chunks if c.clause_label}
    items = load_golden_set(_GOLDEN_PATH)
    missing = {
        label
        for item in items
        if item.kind == "in_corpus"
        for label in item.expected_clause_labels
        if label not in real_labels
    }
    assert not missing, f"golden labels absent from corpus: {sorted(missing)}"
