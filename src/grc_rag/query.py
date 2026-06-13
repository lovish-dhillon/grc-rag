"""Thin CLI for the cite-or-refuse loop — over the full Phase-2 retrieval stack.

    python -m grc_rag.query "What are the obligations for high-risk AI providers?"

Wires hybrid retrieval (BM25 + dense, RRF) → cross-encoder re-rank → threshold-based refusal
enforcement (applied only when a calibrated threshold has been persisted) → cite-or-refuse
generation, and prints the answer with every citation resolved to its human **clause label**
(e.g. ``EU AI Act — Article 5``) rather than an opaque chunk index. The Streamlit demo
(PRD-11) sits on the same calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from grc_rag.enforce import SupportThreshold, answer_with_enforcement
from grc_rag.hybrid import HybridRetriever
from grc_rag.ingest import load_chunks_jsonl
from grc_rag.llm import OllamaClient
from grc_rag.pipeline import answer_question
from grc_rag.rerank import CrossEncoderReranker, RerankingRetriever

_INDEX_FILE = "index.jsonl"
_THRESHOLD_FILE = "support-threshold.json"


def build_retriever(
    index_dir: Path, *, candidate_k: int = 50, top_k: int = 6
) -> RerankingRetriever:
    """Wire the Phase-2 retrieval stack: hybrid (BM25 + dense) → cross-encoder re-rank."""
    hybrid = HybridRetriever.from_index(index_dir, candidate_k=candidate_k)
    return RerankingRetriever(hybrid, CrossEncoderReranker(), candidate_k=candidate_k, top_k=top_k)


def load_labels(index_dir: Path) -> dict[str, str | None]:
    """``chunk_id → clause_label`` read from the built index, for resolving citations."""
    return {
        chunk.chunk_id: chunk.clause_label for chunk in load_chunks_jsonl(index_dir / _INDEX_FILE)
    }


def load_threshold(index_dir: Path) -> SupportThreshold | None:
    """The persisted calibrated support threshold, or ``None`` if none has been set yet."""
    path = index_dir / _THRESHOLD_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SupportThreshold(value=float(data["value"]), calibrated_on=str(data["calibrated_on"]))


def format_citations(citations: Sequence[str], labels: dict[str, str | None]) -> str:
    """Render each citation as ``chunk_id — clause_label`` (label omitted when unknown). Pure."""
    lines = [f"  {cid} — {labels[cid]}" if labels.get(cid) else f"  {cid}" for cid in citations]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask grc-rag a question (cite-or-refuse).")
    parser.add_argument("question", help="the question to answer from the corpus")
    parser.add_argument(
        "--index-dir", type=Path, default=Path("data/processed"), help="dir holding the built index"
    )
    parser.add_argument("-k", type=int, default=6, help="number of chunks to retrieve")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model name")
    args = parser.parse_args(argv)

    retriever = build_retriever(args.index_dir, top_k=args.k)
    client = OllamaClient(model=args.model)
    threshold = load_threshold(args.index_dir)

    if threshold is not None:
        answer = answer_with_enforcement(
            args.question, retriever=retriever, client=client, threshold=threshold, k=args.k
        )
    else:
        answer = answer_question(args.question, retriever=retriever, client=client, k=args.k)

    print(answer.text)
    if not answer.refused:
        print("\nCitations:")
        print(format_citations(answer.citations, load_labels(args.index_dir)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
