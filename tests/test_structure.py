"""Tests for structure-aware chunking.

Small hand-built fixtures make the segmentation predictable, and the token sub-splitting is
exercised with a tiny ``target_tokens`` so a short fixture still crosses the budget. The key
properties: headings are detected by *form* (not loose substring), each clause becomes its own
labelled segment, a long clause sub-splits without leaking into its neighbour, and unstructured
text still chunks (the graceful fallback).
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from grc_rag.chunking import Chunk
from grc_rag.structure import Segment, detect_segments, split_structured


# --------------------------------------------------------------------------- #
# detect_segments — heading detection + labelling
# --------------------------------------------------------------------------- #
def test_detects_eu_articles_as_separate_segments() -> None:
    text = "Article 1\nScope of this Regulation.\nArticle 2\nDefinitions apply."
    segments = detect_segments("eu-ai-act", text)
    assert [s.clause_label for s in segments] == ["EU AI Act — Article 1", "EU AI Act — Article 2"]
    assert "Scope" in segments[0].text and "Definitions" in segments[1].text


def test_detects_eu_annex_and_nbsp_headings() -> None:
    # EUR-Lex glues a non-breaking space between the word and the number; \s must match it.
    segments = detect_segments(
        "eu-ai-act", "Article\xa05\nProhibited practices.\nANNEX\xa0III\nList."
    )
    assert [s.clause_label for s in segments] == ["EU AI Act — Article 5", "EU AI Act — Annex III"]


def test_detects_nist_rmf_subcategory() -> None:
    segments = detect_segments("nist-ai-rmf", "GOVERN 1.1: Legal requirements\nare understood.")
    assert segments[0].clause_label == "NIST AI RMF — GOVERN 1.1"


def test_genai_groups_consecutive_actions_under_one_subcategory() -> None:
    text = "GV-1.1-001 Align development.\nGV-1.1-002 Document choices.\nGV-1.2-001 Other thing."
    labels = [s.clause_label for s in detect_segments("nist-genai-profile", text)]
    # GV-1.1-001 and GV-1.1-002 share a subcategory → one segment; GV-1.2 starts a new one.
    assert labels == ["NIST GenAI Profile — GV-1.1", "NIST GenAI Profile — GV-1.2"]


def test_preamble_before_first_heading_is_an_unlabelled_segment() -> None:
    segments = detect_segments("eu-ai-act", "Some preamble text.\nArticle 1\nThe body.")
    assert segments[0].clause_label is None and "preamble" in segments[0].text
    assert segments[1].clause_label == "EU AI Act — Article 1"


def test_heading_regex_is_anchored_not_loose() -> None:
    # A mid-sentence reference to an article must NOT be treated as a heading.
    segments = detect_segments("eu-ai-act", "as set out in Article 6 of this Regulation")
    assert len(segments) == 1 and segments[0].clause_label is None


def test_no_structure_falls_back_to_single_segment() -> None:
    assert detect_segments("eu-ai-act", "plain text, no headings at all") == (
        Segment(clause_label=None, text="plain text, no headings at all"),
    )


def test_unknown_doc_id_is_single_unlabelled_segment() -> None:
    segments = detect_segments("some-other-doc", "Article 1\nbody")
    assert len(segments) == 1 and segments[0].clause_label is None


def test_empty_text_yields_no_segments() -> None:
    assert detect_segments("eu-ai-act", "   ") == ()


# --------------------------------------------------------------------------- #
# split_structured — labelled chunks, no boundary crossing
# --------------------------------------------------------------------------- #
def test_split_tags_every_chunk_with_its_clause_label() -> None:
    chunks = split_structured("eu-ai-act", "Article 1\nScope.\nArticle 2\nDefinitions.")
    labels = {c.clause_label for c in chunks}
    assert labels == {"EU AI Act — Article 1", "EU AI Act — Article 2"}


def test_long_segment_subsplits_without_crossing_boundary() -> None:
    # A long Article 1, then a tiny Article 2; force sub-splitting with a small token budget.
    text = "Article 1\n" + "alpha " * 40 + "\nArticle 2\nbeta gamma delta"
    chunks = split_structured("eu-ai-act", text, target_tokens=8, overlap_tokens=2)

    art1 = [c for c in chunks if c.clause_label == "EU AI Act — Article 1"]
    art2 = [c for c in chunks if c.clause_label == "EU AI Act — Article 2"]
    assert len(art1) > 1  # the long Article actually sub-split
    # No Article-1 chunk leaked Article-2 content, and vice-versa.
    assert all("beta" not in c.text for c in art1)
    assert all("alpha" not in c.text for c in art2)
    # chunk_ids stay globally sequential across segments.
    assert [c.chunk_id for c in chunks] == [f"eu-ai-act::{i}" for i in range(len(chunks))]


def test_split_fails_fast_on_bad_boundaries() -> None:
    with pytest.raises(ValueError, match="doc_id"):
        split_structured("  ", "Article 1\nx")
    with pytest.raises(ValueError, match="target_tokens"):
        split_structured("eu-ai-act", "x", target_tokens=0)
    with pytest.raises(ValueError, match="overlap_tokens"):
        split_structured("eu-ai-act", "x", target_tokens=10, overlap_tokens=10)


# --------------------------------------------------------------------------- #
# Chunk backward-compatibility with the new clause_label field
# --------------------------------------------------------------------------- #
def test_old_chunk_jsonl_without_label_loads_as_none() -> None:
    # A line written before clause_label existed has no such key.
    legacy = {
        "chunk_id": "doc::0",
        "doc_id": "doc",
        "text": "x",
        "token_count": 1,
        "start_token": 0,
    }
    chunk = Chunk(**legacy)
    assert chunk.clause_label is None


def test_new_chunk_roundtrips_label_through_asdict() -> None:
    original = Chunk("d::0", "d", "t", 1, 0, clause_label="EU AI Act — Article 5")
    restored = Chunk(**json.loads(json.dumps(asdict(original))))
    assert restored == original and restored.clause_label == "EU AI Act — Article 5"
