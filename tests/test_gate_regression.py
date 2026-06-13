"""The seeded-regression proof — the gate must bite.

A gate that can't fail is theatre. These tests prove the gate turns red on a regressed report,
and that the ``GRC_RAG_SEED_REGRESSION`` flag routes the run to the committed regression fixture
(the reversible, demoable way to make a live CI run go red).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grc_rag.evaluate import EvalReport
from grc_rag.gate import (
    DEFAULT_GOLDEN_PATH,
    REGRESSION_GOLDEN_PATH,
    active_golden_path,
    evaluate_gate,
)
from grc_rag.ir_metrics import IRReport


def _regressed_report() -> EvalReport:
    # Retrieval collapses (recall 0.1) — exactly what a seeded regression causes.
    return EvalReport(
        ir=IRReport(recall_at_k=0.10, mrr=0.05, ndcg_at_k=0.05, k=10, n_items=36),
        faithfulness=0.95,
        answer_relevancy=0.9,
        refusal_accuracy=1.0,
        n_in_corpus=36,
        n_out_corpus=5,
    )


def test_seeded_regression_turns_gate_red() -> None:
    result = evaluate_gate(_regressed_report())
    assert result.passed is False  # the gate would exit non-zero → CI red
    assert "recall@10" in result.summary


def test_seed_flag_routes_to_regression_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRC_RAG_SEED_REGRESSION", "1")
    assert active_golden_path() == REGRESSION_GOLDEN_PATH


def test_no_seed_flag_uses_real_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRC_RAG_SEED_REGRESSION", raising=False)
    assert active_golden_path() == DEFAULT_GOLDEN_PATH


def test_regression_fixture_is_committed_and_loadable() -> None:
    """The regression fixture must exist and load (it's how the live demo turns CI red)."""
    from grc_rag.golden import load_golden_set

    path = Path(__file__).resolve().parents[1] / REGRESSION_GOLDEN_PATH
    assert path.exists(), "regression-set.jsonl must be committed for the seeded-regression demo"
    items = load_golden_set(path)
    assert len(items) >= 1
