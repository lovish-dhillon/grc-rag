"""Tests for reciprocal-rank fusion and the hybrid retriever.

The fusion core works on ranked *id lists*, so it is tested with hand-computed RRF
scores and no model at all. The retriever is tested with tiny stub dense/BM25 halves
that let us dictate exactly what each arm returns, then end-to-end through
``answer_question`` to prove it is a drop-in for the ``Retriever`` Protocol.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from conftest import StubLLMClient
from grc_rag.bm25 import BM25Index
from grc_rag.chunking import Chunk
from grc_rag.hybrid import FusedResult, HybridRetriever, reciprocal_rank_fusion
from grc_rag.pipeline import answer_question
from grc_rag.retrieve import RetrievedChunk


def _chunk(chunk_id: str, text: str = "text") -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id=chunk_id.split("::")[0], text=text, token_count=1, start_token=0
    )


# --------------------------------------------------------------------------- #
# reciprocal_rank_fusion — the pure core
# --------------------------------------------------------------------------- #
def test_rrf_fuses_orders_and_records_provenance() -> None:
    # dense: a(1) b(2) c(3) ; bm25: a(1) b(2) d(3)
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["a", "b", "d"]], k_rrf=60)
    by_id = {f.chunk_id: f for f in fused}

    # a in both lists at rank 1, b in both at rank 2, c dense-only, d bm25-only.
    assert by_id["a"].rrf_score == pytest.approx(1 / 61 + 1 / 61)
    assert by_id["b"].rrf_score == pytest.approx(1 / 62 + 1 / 62)
    assert by_id["c"].rrf_score == pytest.approx(1 / 63)
    assert by_id["d"].rrf_score == pytest.approx(1 / 63)

    # Provenance: which list each id came from (1-based rank, None if absent).
    assert (by_id["a"].dense_rank, by_id["a"].bm25_rank) == (1, 1)
    assert (by_id["c"].dense_rank, by_id["c"].bm25_rank) == (3, None)
    assert (by_id["d"].dense_rank, by_id["d"].bm25_rank) == (None, 3)

    # Ordered by score desc; ties (c, d) break deterministically by chunk_id.
    assert [f.chunk_id for f in fused] == ["a", "b", "c", "d"]


def test_rrf_rank_one_in_both_beats_rank_one_in_one() -> None:
    # a is rank 1 in both lists; e is rank 1 in dense only → a must outrank e.
    fused = reciprocal_rank_fusion([["a", "e"], ["a", "z"]], k_rrf=60)
    order = [f.chunk_id for f in fused]
    assert order[0] == "a"
    assert order.index("a") < order.index("e")


def test_rrf_empty_input_returns_empty() -> None:
    assert reciprocal_rank_fusion([[], []]) == ()
    assert reciprocal_rank_fusion([]) == ()


def test_rrf_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k_rrf must be"):
        reciprocal_rank_fusion([["a"]], k_rrf=0)


def test_fused_result_is_frozen() -> None:
    result = FusedResult(chunk_id="a", rrf_score=0.5, dense_rank=1, bm25_rank=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rrf_score = 0.9  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# HybridRetriever — drop-in for the Retriever Protocol, via stub halves
# --------------------------------------------------------------------------- #
class _StubDense:
    """Returns its chunks in a fixed dense rank order, score descending."""

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        self._chunks = chunks

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        return tuple(
            RetrievedChunk(chunk=c, score=1.0 - 0.01 * i) for i, c in enumerate(self._chunks[:k])
        )


class _StubBM25:
    """Returns its chunks in a fixed lexical rank order, score descending."""

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        self._chunks = chunks

    def search(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        n = len(self._chunks)
        return tuple(
            RetrievedChunk(chunk=c, score=float(n - i)) for i, c in enumerate(self._chunks[:k])
        )


def test_hybrid_orders_by_rrf_and_caps_at_k() -> None:
    c0, c1, c2 = _chunk("doc::0"), _chunk("doc::1"), _chunk("doc::2")
    dense = _StubDense((c0, c1, c2))  # dense order: 0, 1, 2
    bm25 = _StubBM25((c1, c0, c2))  # bm25 order:  1, 0, 2
    hybrid = HybridRetriever(dense, bm25, candidate_k=3, k_rrf=60)

    results = hybrid.retrieve("q", k=2)
    assert len(results) == 2
    # 0 (ranks 1,2) and 1 (ranks 2,1) tie on score; both beat 2 (ranks 3,3).
    assert {r.chunk.chunk_id for r in results} == {"doc::0", "doc::1"}
    assert results[0].score >= results[1].score
    # .score now carries the RRF score, not a cosine.
    assert results[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_hybrid_surfaces_a_bm25_only_hit() -> None:
    # 'extra' is outside the dense candidate set but #1 in BM25 → it must survive fusion.
    indexed = _chunk("doc::9", "prohibited practices")
    dense = _StubDense((_chunk("doc::0"), _chunk("doc::1")))
    bm25 = _StubBM25((indexed, _chunk("doc::0")))
    hybrid = HybridRetriever(dense, bm25, candidate_k=2, k_rrf=60)

    ids = {r.chunk.chunk_id for r in hybrid.retrieve("prohibited practices", k=3)}
    assert "doc::9" in ids


def test_from_index_roundtrip_wires_both_arms(tmp_path) -> None:
    # Build a real dense index (fake encoder) + let BM25 read the same index.jsonl, offline.
    import json
    from dataclasses import asdict

    from conftest import FakeEncoder, _deterministic_vector
    from grc_rag import embeddings

    chunks = (
        _chunk("doc::0", "alpha unrelated text"),
        _chunk("doc::1", "the target clause about prohibited practices"),
        _chunk("doc::2", "gamma unrelated text"),
    )
    chunks_path = tmp_path / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk)) + "\n")

    fake = FakeEncoder(
        {"find target": _deterministic_vector("the target clause about prohibited practices", 4)},
        dim=4,
    )
    out_dir = tmp_path / "index"
    embeddings.build_index(chunks_path, out_dir=out_dir, encoder=fake)

    hybrid = HybridRetriever.from_index(out_dir, encoder=fake)
    # Dense maps the query onto chunk 1's vector; BM25 agrees via "target"/"prohibited" →
    # fusion puts doc::1 on top.
    assert hybrid.retrieve("find target", k=1)[0].chunk.chunk_id == "doc::1"


def test_hybrid_is_drop_in_for_answer_question() -> None:
    chunk = _chunk("eu-ai-act::4", "Providers shall ensure compliance.")
    dense = _StubDense((chunk,))
    bm25 = _StubBM25((chunk,))
    hybrid = HybridRetriever(dense, bm25)
    client = StubLLMClient("Providers shall ensure compliance [eu-ai-act::4].")

    answer = answer_question("What must providers do?", retriever=hybrid, client=client, k=5)
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::4",)


# --------------------------------------------------------------------------- #
# Fail-fast
# --------------------------------------------------------------------------- #
def test_hybrid_rejects_blank_query() -> None:
    hybrid = HybridRetriever(_StubDense((_chunk("doc::0"),)), _StubBM25((_chunk("doc::0"),)))
    with pytest.raises(ValueError, match="non-empty"):
        hybrid.retrieve("  ")


def test_hybrid_rejects_non_positive_k() -> None:
    hybrid = HybridRetriever(_StubDense((_chunk("doc::0"),)), _StubBM25((_chunk("doc::0"),)))
    with pytest.raises(ValueError, match="k must be"):
        hybrid.retrieve("q", k=0)


def test_hybrid_rejects_bad_construction() -> None:
    dense, bm25 = _StubDense((_chunk("doc::0"),)), _StubBM25((_chunk("doc::0"),))
    with pytest.raises(ValueError, match="candidate_k"):
        HybridRetriever(dense, bm25, candidate_k=0)
    with pytest.raises(ValueError, match="k_rrf"):
        HybridRetriever(dense, bm25, k_rrf=0)


# --------------------------------------------------------------------------- #
# Integration: hybrid vs dense vs bm25 on the real corpus + probe set.
# Off by default — needs the real embedder + a built index in data/processed.
# --------------------------------------------------------------------------- #
# (question, expected_doc, expected_kw) — mirrors builddocs/phase-1/probe-set.md.
_IN_CORPUS_PROBES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "What are the obligations for providers of high-risk AI systems?",
        "eu-ai-act",
        ("high-risk", "provider"),
    ),
    ("Which AI practices are prohibited?", "eu-ai-act", ("prohibited",)),
    ("How is an AI system classified as high-risk?", "eu-ai-act", ("high-risk", "classif")),
    (
        "What transparency obligations apply to AI systems that interact with natural persons?",
        "eu-ai-act",
        ("transparency",),
    ),
    (
        "What are the core functions of the NIST AI Risk Management Framework?",
        "nist-ai-rmf",
        ("govern", "map", "measure", "manage"),
    ),
    (
        "What characteristics make an AI system trustworthy according to NIST?",
        "nist-ai-rmf",
        ("trustworth",),
    ),
    (
        "What is confabulation in the context of generative AI?",
        "nist-genai-profile",
        ("confabulat",),
    ),
    ("What risks does the NIST Generative AI Profile identify?", "nist-genai-profile", ("risk",)),
    (
        "What administrative fines can be imposed under the EU AI Act?",
        "eu-ai-act",
        ("fine", "penalt"),
    ),
    ("What does the GOVERN function of the AI RMF address?", "nist-ai-rmf", ("govern",)),
)


def _is_hit(results: tuple[RetrievedChunk, ...], doc: str, kws: tuple[str, ...]) -> bool:
    """Probe-set proxy: top-k holds a chunk from `doc` mentioning any keyword."""
    return any(
        r.chunk.doc_id == doc and any(kw.lower() in r.chunk.text.lower() for kw in kws)
        for r in results
    )


@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the real model + a built index; set RUN_INTEGRATION=1 to run",
)
def test_hybrid_recall_beats_either_alone_on_probe_set() -> None:
    from pathlib import Path

    from grc_rag.embeddings import _INDEX_FILE
    from grc_rag.retrieve import DenseRetriever

    index_dir = Path("data/processed")
    dense = DenseRetriever.from_index(index_dir)
    bm25 = BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE)
    hybrid = HybridRetriever(dense, bm25)

    dense_hits = sum(_is_hit(dense.retrieve(q, k=10), d, kw) for q, d, kw in _IN_CORPUS_PROBES)
    bm25_hits = sum(_is_hit(bm25.search(q, k=10), d, kw) for q, d, kw in _IN_CORPUS_PROBES)
    hybrid_hits = sum(_is_hit(hybrid.retrieve(q, k=10), d, kw) for q, d, kw in _IN_CORPUS_PROBES)

    print(f"\ndense={dense_hits}/10  bm25={bm25_hits}/10  hybrid={hybrid_hits}/10")
    assert hybrid_hits >= max(dense_hits, bm25_hits)


@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="needs the real model + a built index; set RUN_INTEGRATION=1 to run",
)
def test_hybrid_surfaces_art5_prohibited_practices() -> None:
    from pathlib import Path

    from grc_rag.embeddings import _INDEX_FILE
    from grc_rag.retrieve import DenseRetriever

    index_dir = Path("data/processed")
    hybrid = HybridRetriever(
        DenseRetriever.from_index(index_dir),
        BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE),
    )
    results = hybrid.retrieve("Which AI practices are prohibited?", k=10)
    assert _is_hit(results, "eu-ai-act", ("prohibited",))
