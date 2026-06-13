"""Tests for the pure latency/cost aggregation — hand-computed expected values."""

from __future__ import annotations

import pytest

from grc_rag.percentiles import percentile, summarise
from grc_rag.tracing import QueryTrace


def _trace(latency_ms: float, cost_usd: float = 0.0) -> QueryTrace:
    return QueryTrace("q", (), (), "a", (), False, "v", latency_ms, cost_usd)


# --------------------------------------------------------------------------- #
# percentile
# --------------------------------------------------------------------------- #
def test_percentile_median_odd() -> None:
    assert percentile([10, 20, 30], 50) == 20.0


def test_percentile_endpoints() -> None:
    values = [10, 20, 30, 40]
    assert percentile(values, 100) == 40.0
    # P50 of [10,20,30,40] by linear interpolation on rank 1.5 → 25.0
    assert percentile(values, 50) == pytest.approx(25.0)


def test_percentile_p95_interpolates() -> None:
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # rank = 0.95 * 9 = 8.55 → between index 8 (9) and 9 (10): 9 + 0.55 = 9.55
    assert percentile(values, 95) == pytest.approx(9.55)


def test_percentile_single_value() -> None:
    assert percentile([42.0], 95) == 42.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


def test_percentile_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="p must be"):
        percentile([1, 2], 0)
    with pytest.raises(ValueError, match="p must be"):
        percentile([1, 2], 101)


# --------------------------------------------------------------------------- #
# summarise
# --------------------------------------------------------------------------- #
def test_summarise_latency_and_cost() -> None:
    traces = [_trace(10), _trace(20), _trace(30), _trace(40)]
    report = summarise(traces)
    assert report.n == 4
    assert report.p50_latency_ms == pytest.approx(25.0)
    assert report.mean_cost_usd == 0.0
    assert report.total_cost_usd == 0.0


def test_summarise_tracks_api_cost() -> None:
    traces = [_trace(10, cost_usd=0.002), _trace(20, cost_usd=0.004)]
    report = summarise(traces)
    assert report.total_cost_usd == pytest.approx(0.006)
    assert report.mean_cost_usd == pytest.approx(0.003)


def test_summarise_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        summarise([])
