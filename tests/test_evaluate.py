"""Tests for the eval harness wiring.

Everything is stubbed: a retriever that returns one relevant chunk, a generation client that
answers in-corpus questions and refuses the out-of-corpus one, and a judge client that routes
faithfulness vs relevancy prompts. No model, no key, no index.
"""

from __future__ import annotations

import json
from pathlib import Path

from grc_rag.chunking import Chunk
from grc_rag.evaluate import format_report, run_eval
from grc_rag.generate import REFUSAL
from grc_rag.golden import GOLDEN_SCHEMA_VERSION
from grc_rag.retrieve import RetrievedChunk

_LABEL = "EU AI Act — Article 5"
_CHUNK_ID = "eu-ai-act::5"


class _StubRetriever:
    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        chunk = Chunk(
            chunk_id=_CHUNK_ID,
            doc_id="eu-ai-act",
            text="The following AI practices shall be prohibited ...",
            token_count=9,
            start_token=0,
            clause_label=_LABEL,
        )
        return (RetrievedChunk(chunk=chunk, score=5.0),)


class _GenClient:
    """Cites the retrieved chunk for in-corpus questions; refuses the out-of-corpus one (which
    we mark with the unique token 'Mars' in its question)."""

    def complete(self, prompt: str) -> str:
        if "Mars" in prompt:
            return REFUSAL
        return f"Prohibited practices are listed [{_CHUNK_ID}]."


class _JudgeClient:
    """Routes on the faithfulness prompt's unique 'SOURCE CHUNKS' marker."""

    def complete(self, prompt: str) -> str:
        if "SOURCE CHUNKS" in prompt:
            return json.dumps(
                {"claims": [{"claim": "prohibited list", "supported": True, "reason": "r"}]}
            )
        return json.dumps({"relevant": True, "reason": "addresses it"})


def _write_golden(path: Path) -> Path:
    rows = [
        {
            "id": "g-in-1",
            "question": "Which AI practices are prohibited?",
            "kind": "in_corpus",
            "expected_doc": "eu-ai-act",
            "expected_clause_labels": [_LABEL],
            "notes": "",
            "schema_version": GOLDEN_SCHEMA_VERSION,
        },
        {
            "id": "g-in-2",
            "question": "What practices may not be placed on the market?",
            "kind": "in_corpus",
            "expected_doc": "eu-ai-act",
            "expected_clause_labels": [_LABEL],
            "notes": "",
            "schema_version": GOLDEN_SCHEMA_VERSION,
        },
        {
            "id": "g-out-1",
            "question": "Who won the 2026 Mars marathon?",
            "kind": "out_of_corpus",
            "expected_doc": None,
            "expected_clause_labels": [],
            "notes": "",
            "schema_version": GOLDEN_SCHEMA_VERSION,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_run_eval_aggregates(tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.jsonl")
    report = run_eval(
        golden,
        retriever=_StubRetriever(),
        gen_client=_GenClient(),
        judge_client=_JudgeClient(),
        k=10,
    )
    # IR: relevant chunk at rank 1 for both in-corpus items.
    assert report.ir.recall_at_k == 1.0
    assert report.ir.mrr == 1.0
    assert report.ir.n_items == 2
    # judge: all claims supported, all relevant.
    assert report.faithfulness == 1.0
    assert report.answer_relevancy == 1.0
    # the out-of-corpus question refused → perfect refusal accuracy.
    assert report.refusal_accuracy == 1.0
    assert report.n_in_corpus == 2
    assert report.n_out_corpus == 1


def test_format_report_is_a_table(tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.jsonl")
    report = run_eval(
        golden,
        retriever=_StubRetriever(),
        gen_client=_GenClient(),
        judge_client=_JudgeClient(),
        k=10,
    )
    table = format_report(report)
    assert "Recall@10" in table
    assert "Faithfulness" in table
    assert table.count("\n") >= 7  # header + separator + rows
