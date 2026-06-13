"""Latency/cost aggregation — computed in our own code, not read off someone's dashboard.

Langfuse will happily show percentiles in its UI, but the numbers we put in ``04-results.md``
should be ones we can derive and defend, and a demo should work before the dashboard is even
open. So the aggregation is a few lines of pure arithmetic over recorded
:class:`~grc_rag.tracing.QueryTrace` records.

One deliberate choice: we report **percentiles, not averages**. A mean latency hides the tail —
the P95 is what a user actually feels on a bad query, and it's the number worth defending. P50
(the median) and P95 together say "typical" and "near-worst" without a single average smearing
them into one misleading figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from grc_rag.tracing import QueryTrace


def percentile(values: Sequence[float], p: float) -> float:
    """The ``p``-th percentile (``0 < p <= 100``) by linear interpolation between closest ranks.

    Raises ``ValueError`` on an empty input or a ``p`` outside ``(0, 100]``. Pure.
    """
    if not values:
        raise ValueError("cannot take a percentile of an empty sequence")
    if not 0 < p <= 100:
        raise ValueError(f"p must be in (0, 100], got {p}")

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    # Linear interpolation on the (n-1)-scaled rank — the common "exclusive of 0" definition.
    rank = (p / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * fraction)


@dataclass(frozen=True)
class OpsReport:
    """Operational summary over a set of recorded traces. Immutable."""

    n: int
    p50_latency_ms: float
    p95_latency_ms: float
    mean_cost_usd: float
    total_cost_usd: float


def summarise(traces: Sequence[QueryTrace]) -> OpsReport:
    """P50/P95 latency and mean & total cost per request from recorded traces.

    Raises ``ValueError`` on an empty trace set (there is nothing to summarise). Pure.
    """
    if not traces:
        raise ValueError("cannot summarise an empty trace set")

    latencies = [t.latency_ms for t in traces]
    costs = [t.cost_usd for t in traces]
    total_cost = sum(costs)
    return OpsReport(
        n=len(traces),
        p50_latency_ms=percentile(latencies, 50),
        p95_latency_ms=percentile(latencies, 95),
        mean_cost_usd=total_cost / len(traces),
        total_cost_usd=total_cost,
    )
