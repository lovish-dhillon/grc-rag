"""Tests for the query CLI — wiring + output formatting, with the heavy parts stubbed.

The CLI builds the Phase-2 retrieval stack and an Ollama client internally, so we monkeypatch
those seams (and the pipeline calls) to assert the print behaviour — a cited answer with
clause labels, a refusal, and that a persisted threshold routes through enforcement — all
without a model or a built index.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from grc_rag import query
from grc_rag.chunking import Chunk
from grc_rag.enforce import SupportThreshold
from grc_rag.generate import REFUSAL, Answer


@pytest.fixture
def stub_main(monkeypatch):
    """Stub the CLI's heavy seams for the main() wiring tests (not the pure/IO unit tests)."""
    monkeypatch.setattr(query, "build_retriever", lambda d, **kw: object())
    monkeypatch.setattr(query, "OllamaClient", lambda model: object())
    monkeypatch.setattr(query, "load_threshold", lambda d: None)
    monkeypatch.setattr(query, "load_labels", lambda d: {"eu-ai-act::4": "EU AI Act — Article 16"})


# --------------------------------------------------------------------------- #
# format_citations / load_* — pure + IO, tested against the real functions
# --------------------------------------------------------------------------- #
def test_format_citations_renders_label_when_known() -> None:
    out = query.format_citations(("eu-ai-act::4",), {"eu-ai-act::4": "EU AI Act — Article 5"})
    assert out == "  eu-ai-act::4 — EU AI Act — Article 5"


def test_format_citations_omits_missing_label() -> None:
    out = query.format_citations(("doc::9",), {"doc::9": None})
    assert out == "  doc::9"


def test_load_threshold_absent_returns_none(tmp_path) -> None:
    assert query.load_threshold(tmp_path) is None


def test_load_threshold_reads_persisted_json(tmp_path) -> None:
    (tmp_path / "support-threshold.json").write_text(
        json.dumps({"value": 1.25, "calibrated_on": "probe-set/2026-06-12"}), encoding="utf-8"
    )
    threshold = query.load_threshold(tmp_path)
    assert threshold is not None
    assert threshold.value == 1.25 and threshold.calibrated_on == "probe-set/2026-06-12"


def test_load_labels_reads_index(tmp_path) -> None:
    chunk = Chunk("eu-ai-act::4", "eu-ai-act", "t", 1, 0, clause_label="EU AI Act — Article 5")
    (tmp_path / "index.jsonl").write_text(json.dumps(asdict(chunk)) + "\n", encoding="utf-8")
    assert query.load_labels(tmp_path) == {"eu-ai-act::4": "EU AI Act — Article 5"}


# --------------------------------------------------------------------------- #
# main — wiring + output (heavy seams stubbed)
# --------------------------------------------------------------------------- #
def test_cli_prints_cited_answer_with_clause_label(stub_main, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        query,
        "answer_question",
        lambda q, **kw: Answer(
            "Providers must comply [eu-ai-act::4].", ("eu-ai-act::4",), False, "v"
        ),
    )
    rc = query.main(["What must providers do?"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Providers must comply [eu-ai-act::4]." in out
    assert "eu-ai-act::4 — EU AI Act — Article 16" in out  # citation resolved to a named clause


def test_cli_prints_refusal_without_citations(stub_main, monkeypatch, capsys) -> None:
    monkeypatch.setattr(query, "answer_question", lambda q, **kw: Answer(REFUSAL, (), True, "v"))
    rc = query.main(["Who won the 2026 Australian Open?"])
    out = capsys.readouterr().out
    assert rc == 0
    assert REFUSAL in out
    assert "Citations:" not in out


def test_cli_uses_enforcement_when_threshold_present(stub_main, monkeypatch, capsys) -> None:
    # A persisted threshold must route through answer_with_enforcement, not plain answer_question.
    monkeypatch.setattr(query, "load_threshold", lambda d: SupportThreshold(0.5, "test"))
    monkeypatch.setattr(
        query, "answer_question", lambda *a, **k: pytest.fail("should use enforcement path")
    )
    monkeypatch.setattr(
        query,
        "answer_with_enforcement",
        lambda q, **kw: Answer("Grounded [eu-ai-act::4].", ("eu-ai-act::4",), False, "v"),
    )
    rc = query.main(["What must providers do?"])
    assert rc == 0
    assert "eu-ai-act::4 — EU AI Act — Article 16" in capsys.readouterr().out
