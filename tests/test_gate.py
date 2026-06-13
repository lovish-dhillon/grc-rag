"""Tests for the CI regression gate — pure decision logic, scorecard I/O, staleness.

No model, no key, no live index: ``evaluate_gate`` is pure over an ``EvalReport``, and the
scorecard helpers read/write tiny fixtures in ``tmp_path``. The gate has two thresholds —
faithfulness + recall (the "0 uncited claims" target is covered structurally-by-construction and
semantically by faithfulness; see ``03-decisions.md``).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest

from grc_rag.evaluate import EvalReport
from grc_rag.gate import (
    GateThresholds,
    MetricCheck,
    Scorecard,
    evaluate_gate,
    evaluate_recall_gate,
    evaluate_scorecard_gate,
    golden_hash,
    is_stale,
    load_scorecard,
    save_scorecard,
)
from grc_rag.ir_metrics import IRReport


def _report(*, faithfulness: float, recall: float, k: int = 10) -> EvalReport:
    return EvalReport(
        ir=IRReport(recall_at_k=recall, mrr=0.7, ndcg_at_k=0.7, k=k, n_items=36),
        faithfulness=faithfulness,
        answer_relevancy=0.9,
        refusal_accuracy=1.0,
        n_in_corpus=36,
        n_out_corpus=5,
    )


def _card(
    faithfulness: float, run_date: str, golden_h: str, model: str = "m", version: str = "v"
) -> Scorecard:
    return Scorecard(
        faithfulness=faithfulness,
        run_date=run_date,
        golden_hash=golden_h,
        judge_model=model,
        prompt_version=version,
    )


# --------------------------------------------------------------------------- #
# evaluate_gate
# --------------------------------------------------------------------------- #
def test_gate_passes_when_all_clear() -> None:
    result = evaluate_gate(_report(faithfulness=0.95, recall=0.90))
    assert result.passed is True
    assert all(c.passed for c in result.checks)
    assert "PASS" in result.summary


def test_gate_fails_on_faithfulness() -> None:
    result = evaluate_gate(_report(faithfulness=0.89, recall=0.90))
    assert result.passed is False
    assert "faithfulness" in result.summary


def test_gate_fails_on_recall() -> None:
    result = evaluate_gate(_report(faithfulness=0.95, recall=0.84))
    assert result.passed is False
    assert "recall@10" in result.summary


def test_gate_boundary_is_inclusive() -> None:
    # exactly at both thresholds → passes (>=)
    result = evaluate_gate(_report(faithfulness=0.90, recall=0.85))
    assert result.passed is True


def test_recall_gate_only() -> None:
    ir_ok = IRReport(recall_at_k=0.85, mrr=0.7, ndcg_at_k=0.7, k=10, n_items=36)
    ir_bad = IRReport(recall_at_k=0.10, mrr=0.1, ndcg_at_k=0.1, k=10, n_items=36)
    assert evaluate_recall_gate(ir_ok).passed is True
    assert evaluate_recall_gate(ir_bad).passed is False


# --------------------------------------------------------------------------- #
# frozen config
# --------------------------------------------------------------------------- #
def test_dataclasses_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        GateThresholds().min_faithfulness = 0.5  # type: ignore[misc]
    card = _card(0.9, "2026-06-13", "h")
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.faithfulness = 0.1  # type: ignore[misc]
    mc = MetricCheck("x", 1.0, 0.5, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mc.passed = False  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# scorecard I/O
# --------------------------------------------------------------------------- #
def _golden(tmp_path: Path, body: str = '{"x":1}\n') -> Path:
    path = tmp_path / "golden.jsonl"
    path.write_text(body, encoding="utf-8")
    return path


def test_scorecard_roundtrip(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(
        0.91, "2026-06-13", golden_hash(golden), "claude-haiku-4-5-20251001", "cite-or-refuse/v2"
    )
    path = tmp_path / "eval" / "scorecard.json"
    save_scorecard(card, path)
    assert load_scorecard(path) == card


def test_load_scorecard_missing_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no scorecard"):
        load_scorecard(tmp_path / "nope.json")


def test_load_scorecard_malformed_json_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_scorecard(path)


def test_load_scorecard_missing_field_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"faithfulness": 0.9}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        load_scorecard(path)


# --------------------------------------------------------------------------- #
# staleness
# --------------------------------------------------------------------------- #
def test_is_stale_by_age(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(0.9, "2026-06-13", golden_hash(golden))
    assert is_stale(card, golden_path=golden, max_age_days=7, today=date(2026, 6, 20)) is False
    assert is_stale(card, golden_path=golden, max_age_days=7, today=date(2026, 6, 21)) is True


def test_is_stale_by_golden_change(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(0.9, "2026-06-13", "a-different-hash")
    assert is_stale(card, golden_path=golden, max_age_days=3650, today=date(2026, 6, 13)) is True


# --------------------------------------------------------------------------- #
# scorecard gate
# --------------------------------------------------------------------------- #
def test_scorecard_gate_passes_when_fresh_and_good(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(0.92, "2026-06-13", golden_hash(golden))
    result = evaluate_scorecard_gate(
        card, golden_path=golden, max_age_days=7, today=date(2026, 6, 14)
    )
    assert result.passed is True


def test_scorecard_gate_fails_when_stale(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(0.92, "2026-06-13", golden_hash(golden))
    result = evaluate_scorecard_gate(
        card, golden_path=golden, max_age_days=7, today=date(2026, 7, 1)
    )
    assert result.passed is False
    assert "scorecard_fresh" in result.summary


def test_scorecard_gate_fails_on_low_faithfulness(tmp_path: Path) -> None:
    golden = _golden(tmp_path)
    card = _card(0.885, "2026-06-13", golden_hash(golden))
    result = evaluate_scorecard_gate(
        card, golden_path=golden, max_age_days=7, today=date(2026, 6, 14)
    )
    assert result.passed is False
    assert "faithfulness" in result.summary


# --------------------------------------------------------------------------- #
# CLI: the keyless --check-scorecard path (the most-run CI path; no models)
# --------------------------------------------------------------------------- #
def test_run_check_scorecard_pass_and_fail(tmp_path: Path) -> None:
    from datetime import date as _date

    from grc_rag.gate import DEFAULT_GOLDEN_PATH, _run_check_scorecard

    real_hash = golden_hash(DEFAULT_GOLDEN_PATH)  # the committed golden set
    today = _date.today().isoformat()

    good = tmp_path / "good.json"
    save_scorecard(_card(0.92, today, real_hash, "haiku", "cite-or-refuse/v2"), good)
    assert _run_check_scorecard(good, max_age_days=3650) == 0

    bad = tmp_path / "bad.json"
    save_scorecard(_card(0.80, today, real_hash, "haiku", "cite-or-refuse/v2"), bad)
    assert _run_check_scorecard(bad, max_age_days=3650) == 1


def test_main_check_scorecard_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date as _date

    from grc_rag import gate
    from grc_rag.gate import DEFAULT_GOLDEN_PATH

    card_path = tmp_path / "scorecard.json"
    save_scorecard(
        _card(0.92, _date.today().isoformat(), golden_hash(DEFAULT_GOLDEN_PATH)), card_path
    )
    monkeypatch.setattr(
        "sys.argv",
        ["gate", "--check-scorecard", "--scorecard", str(card_path), "--max-age-days", "3650"],
    )
    assert gate.main() == 0
