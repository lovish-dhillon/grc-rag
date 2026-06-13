"""The CI regression gate — turn the eval scores into a build that goes red on regression.

A metric you can read but never enforce is a vibe. This module is the difference between "we
wrote an eval" and "a quality drop cannot silently ship." It thresholds the Phase-3 numbers
(faithfulness ≥ 0.90, recall@10 ≥ 0.85, 0 uncited claims) and exits non-zero below any of them.

The load-bearing real-world constraint is **cost and secrets in CI**. The metrics split cleanly
by how they're produced:

* **recall@10 is deterministic and keyless** — pure IR over the local index. It runs on *every*
  PR/push (``--tier1``) and can fail a build with no API call.
* **faithfulness + uncited-claims are judge-derived** — they need ``ANTHROPIC_API_KEY`` and cost
  money, so running them on every push would burn cost and expose a secret (including on forks).
  They run on a **controlled cadence** (``--judge`` on a nightly schedule / manual dispatch),
  which writes a committed :class:`Scorecard`; the per-PR gate then reads that card
  (``--check-scorecard``) and **fails if it's stale** — older than N days, or measured against a
  different golden set. Honest tradeoff: a PR's faithfulness is the *last committed* judge score,
  not a fresh one; the staleness guard + nightly refresh bound how old it can be.

The gate decision itself (:func:`evaluate_gate`) is **pure** — ``(EvalReport, GateThresholds) →
GateResult`` — so it is fully unit-tested without a model. Thresholds are frozen config, one
source of truth matching ``04-results.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from grc_rag.evaluate import EvalReport
from grc_rag.ir_metrics import IRReport

# Where the committed judge scorecard and the seeded-regression fixture live.
DEFAULT_GOLDEN_PATH = Path("data/golden/golden-set.jsonl")
REGRESSION_GOLDEN_PATH = Path("data/golden/regression-set.jsonl")
DEFAULT_SCORECARD_PATH = Path("data/eval/scorecard.json")
_SEED_REGRESSION_ENV = "GRC_RAG_SEED_REGRESSION"


@dataclass(frozen=True)
class GateThresholds:
    """The CI quality bar — frozen config, one source of truth (matches ``04-results.md``).

    Two thresholds, by design. The onboarding "zero uncited factual claims" target is **not** a
    third number here: the structural cite-or-refuse invariant (every shipped answer cited or
    refused) holds by construction in :mod:`grc_rag.generate`, and the *semantic* "is a cited
    claim supported" property is exactly ``faithfulness`` — so a separate uncited threshold would
    double-count it (a per-segment structural count proved to be list-formatting noise). See
    ``03-decisions.md``.
    """

    min_faithfulness: float = 0.90
    min_recall_at_10: float = 0.85


@dataclass(frozen=True)
class MetricCheck:
    """One threshold check. ``passed`` is inclusive at the boundary (``>=`` / ``<=``)."""

    name: str
    value: float
    threshold: float
    passed: bool


@dataclass(frozen=True)
class GateResult:
    """The gate's verdict: did every check clear? Plus a per-metric breakdown and a one-liner."""

    passed: bool
    checks: tuple[MetricCheck, ...]
    summary: str


def _summarise(checks: tuple[MetricCheck, ...]) -> GateResult:
    failures = [c for c in checks if not c.passed]
    if failures:
        detail = "; ".join(f"{c.name} {c.value:g} vs {c.threshold:g}" for c in failures)
        return GateResult(passed=False, checks=checks, summary=f"FAIL: {detail}")
    return GateResult(passed=True, checks=checks, summary="PASS: all thresholds met")


def _faithfulness_check(value: float, thr: GateThresholds) -> MetricCheck:
    return MetricCheck("faithfulness", value, thr.min_faithfulness, value >= thr.min_faithfulness)


def _recall_check(value: float, k: int, thr: GateThresholds) -> MetricCheck:
    return MetricCheck(f"recall@{k}", value, thr.min_recall_at_10, value >= thr.min_recall_at_10)


def evaluate_gate(report: EvalReport, thresholds: GateThresholds = GateThresholds()) -> GateResult:
    """The full gate over a fresh :class:`EvalReport` — faithfulness + recall. Pure."""
    checks = (
        _faithfulness_check(report.faithfulness, thresholds),
        _recall_check(report.ir.recall_at_k, report.ir.k, thresholds),
    )
    return _summarise(checks)


def evaluate_recall_gate(ir: IRReport, thresholds: GateThresholds = GateThresholds()) -> GateResult:
    """The deterministic, keyless tier — recall@k only (no judge). Pure."""
    return _summarise((_recall_check(ir.recall_at_k, ir.k, thresholds),))


# --------------------------------------------------------------------------- #
# Scorecard — the committed judge result the per-PR gate reads
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Scorecard:
    """The judge metric, committed so the per-PR gate need not pay for the judge every push."""

    faithfulness: float
    run_date: str  # ISO YYYY-MM-DD — staleness is measured against this
    golden_hash: str  # sha256 of the golden file the score was measured on
    judge_model: str
    prompt_version: str


def golden_hash(golden_path: Path) -> str:
    """SHA-256 of the golden file's bytes — ties a scorecard to the exact set it was scored on."""
    return hashlib.sha256(golden_path.read_bytes()).hexdigest()


def save_scorecard(card: Scorecard, path: Path) -> None:
    """Persist a scorecard as JSON, creating the parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "faithfulness": card.faithfulness,
        "run_date": card.run_date,
        "golden_hash": card.golden_hash,
        "judge_model": card.judge_model,
        "prompt_version": card.prompt_version,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_scorecard(path: Path) -> Scorecard:
    """Load + validate a committed scorecard. Raises ``ValueError`` on a missing or malformed file."""
    if not path.exists():
        raise ValueError(f"no scorecard at {path} — run `python -m grc_rag.gate --judge` first")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: invalid JSON — {error}") from error
    required = ("faithfulness", "run_date", "golden_hash", "judge_model", "prompt_version")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"{path}: scorecard missing fields {missing}")
    return Scorecard(
        faithfulness=float(raw["faithfulness"]),
        run_date=str(raw["run_date"]),
        golden_hash=str(raw["golden_hash"]),
        judge_model=str(raw["judge_model"]),
        prompt_version=str(raw["prompt_version"]),
    )


def is_stale(
    card: Scorecard, *, golden_path: Path, max_age_days: int, today: date | None = None
) -> bool:
    """A scorecard is stale if it's older than ``max_age_days`` **or** was measured against a
    different golden set than the one on disk now. ``today`` is injectable for testing."""
    if card.golden_hash != golden_hash(golden_path):
        return True
    today = today or date.today()
    measured = date.fromisoformat(card.run_date)
    return (today - measured).days > max_age_days


def evaluate_scorecard_gate(
    card: Scorecard,
    *,
    golden_path: Path,
    max_age_days: int,
    thresholds: GateThresholds = GateThresholds(),
    today: date | None = None,
) -> GateResult:
    """Gate on the committed judge scorecard: faithfulness + uncited claims, plus a staleness check
    (a stale card is itself a failure — a PR can't pass on a number from a long-gone pipeline)."""
    fresh = not is_stale(card, golden_path=golden_path, max_age_days=max_age_days, today=today)
    checks = (
        MetricCheck("scorecard_fresh", 1.0 if fresh else 0.0, 1.0, fresh),
        _faithfulness_check(card.faithfulness, thresholds),
    )
    return _summarise(checks)


def active_golden_path() -> Path:
    """The golden set the run should use — the seeded **regression** fixture when
    ``GRC_RAG_SEED_REGRESSION`` is set (the reversible proof that the gate bites), else the real
    set. Logged loudly so a seeded run is never mistaken for a real one."""
    if os.environ.get(_SEED_REGRESSION_ENV):
        print(
            f"[gate] {_SEED_REGRESSION_ENV} set — using regression fixture {REGRESSION_GOLDEN_PATH}"
        )
        return REGRESSION_GOLDEN_PATH
    return DEFAULT_GOLDEN_PATH


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _run_tier1(index_dir: Path, k: int) -> int:
    """Deterministic, keyless: compute recall@k over the live index and gate on it."""
    from grc_rag.evaluate import _build_live_retriever
    from grc_rag.golden import load_golden_set
    from grc_rag.ir_metrics import evaluate_retrieval

    golden = active_golden_path()
    items = load_golden_set(golden)
    ir = evaluate_retrieval(items, _build_live_retriever(index_dir), k=k)
    result = evaluate_recall_gate(ir)
    print(result.summary)
    return 0 if result.passed else 1


def _run_judge(index_dir: Path, k: int, scorecard_path: Path) -> int:
    """Paid tier: run the full eval (judge included) and write a committed scorecard."""
    from grc_rag.evaluate import _build_live_retriever, run_eval
    from grc_rag.generate import PROMPT_VERSION
    from grc_rag.llm import AnthropicClient, OllamaClient

    golden = active_golden_path()
    judge = AnthropicClient(max_tokens=4096)
    report = run_eval(
        golden,
        retriever=_build_live_retriever(index_dir),
        gen_client=OllamaClient(),
        judge_client=judge,
        k=k,
    )
    card = Scorecard(
        faithfulness=report.faithfulness,
        run_date=date.today().isoformat(),
        golden_hash=golden_hash(golden),
        judge_model=judge.model,
        prompt_version=PROMPT_VERSION,
    )
    save_scorecard(card, scorecard_path)
    result = evaluate_gate(report)
    print(f"{result.summary}\nscorecard written to {scorecard_path}")
    return 0 if result.passed else 1


def _run_check_scorecard(scorecard_path: Path, max_age_days: int) -> int:
    """Per-PR gate: read the committed scorecard and gate on faithfulness + uncited + freshness."""
    card = load_scorecard(scorecard_path)
    result = evaluate_scorecard_gate(
        card, golden_path=active_golden_path(), max_age_days=max_age_days
    )
    print(result.summary)
    return 0 if result.passed else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="grc-rag CI regression gate.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tier1", action="store_true", help="deterministic recall@k gate (no key)")
    mode.add_argument("--judge", action="store_true", help="run the judge, write a scorecard")
    mode.add_argument(
        "--check-scorecard", action="store_true", help="gate on the committed scorecard"
    )
    parser.add_argument("--index-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD_PATH)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=7)
    args = parser.parse_args()

    if args.tier1:
        return _run_tier1(args.index_dir, args.k)
    if args.judge:
        return _run_judge(args.index_dir, args.k, args.scorecard)
    return _run_check_scorecard(args.scorecard, args.max_age_days)


if __name__ == "__main__":
    raise SystemExit(main())
