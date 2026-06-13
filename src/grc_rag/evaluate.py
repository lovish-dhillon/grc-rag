"""The eval harness — run the golden set end to end and report the trust numbers.

This ties the two halves together: deterministic IR metrics (:mod:`grc_rag.ir_metrics`) that
ask *did retrieval find the right clauses?*, and the LLM-judge (:mod:`grc_rag.judge`) that asks
*is the generated answer actually supported by what it cited, and does it answer the question?*
Out-of-corpus items are scored on a third axis the others can't see: did the system **refuse**,
as cite-or-refuse demands, instead of improvising?

The result is one :class:`EvalReport` — the numbers that fill ``04-results.md`` and that the
CI gate (PRD-P3-11) thresholds. ``run_eval`` is pure given its injected collaborators (a
retriever, a generation client, a judge client), so it is unit-tested end to end with stubs —
no model, no key. The ``python -m grc_rag.evaluate`` CLI wires the real local retriever + Ollama
generator + Anthropic judge and prints the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grc_rag.generate import Answer, LLMClient, generate_answer
from grc_rag.golden import GoldenItem, count_by_kind, load_golden_set
from grc_rag.ir_metrics import IRReport, evaluate_retrieval
from grc_rag.judge import judge_answer_relevancy, judge_faithfulness
from grc_rag.retrieve import RetrievedChunk


class _Retriever:  # structural-typing alias for readability
    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


@dataclass(frozen=True)
class EvalReport:
    """Every Phase-3 trust number in one immutable record.

    ``faithfulness`` (semantic grounding, judge) and ``answer_relevancy`` are means over the
    in-corpus answers; ``refusal_accuracy`` is the fraction of out-of-corpus questions correctly
    refused. There is deliberately **no separate "uncited claims" field**: the structural
    cite-or-refuse invariant — every shipped answer is cited or refused, no dangling citations —
    is guaranteed by construction in :mod:`grc_rag.generate`, and the *semantic* "is a cited
    claim actually supported" question is exactly what ``faithfulness`` measures. A separate
    0-threshold either double-counts faithfulness or (measured per-segment) is dominated by
    list-formatting noise. See ``03-decisions.md``.
    """

    ir: IRReport
    faithfulness: float
    answer_relevancy: float
    refusal_accuracy: float
    n_in_corpus: int
    n_out_corpus: int
    judge_errors: int = (
        0  # in-corpus items whose judge verdict could not be parsed (excluded from means)
    )


def _answer_for(
    item: GoldenItem, retriever: _Retriever, gen_client: LLMClient, *, k: int
) -> tuple[Answer, tuple[RetrievedChunk, ...]]:
    """Retrieve once, generate, and return the answer plus the chunks it actually cited."""
    ranked = retriever.retrieve(item.question, k=k)
    answer = generate_answer(item.question, ranked, client=gen_client)
    cited = tuple(rc for rc in ranked if rc.chunk.chunk_id in answer.citations)
    return answer, cited


def run_eval(
    golden_path: Path,
    *,
    retriever: _Retriever,
    gen_client: LLMClient,
    judge_client: LLMClient,
    k: int = 10,
) -> EvalReport:
    """Score the whole golden set: IR over retrieval, judge over generation, refusal over
    out-of-corpus. Raises ``ValueError`` (via the loader) on a malformed golden file."""
    items = load_golden_set(golden_path)
    counts = count_by_kind(items)
    in_corpus = [i for i in items if i.kind == "in_corpus"]
    out_corpus = [i for i in items if i.kind == "out_of_corpus"]

    ir = evaluate_retrieval(items, retriever, k=k)

    faiths: list[float] = []
    rels: list[float] = []
    judge_errors = 0
    for item in in_corpus:
        answer, cited = _answer_for(item, retriever, gen_client, k=k)
        # The judge functions are fail-fast (a malformed/truncated verdict raises). At the
        # harness level, batching 50–200 items, one bad verdict must not discard the whole run:
        # record it and carry on, so the error count is visible instead of an aborted eval.
        try:
            verdict = judge_faithfulness(answer, cited, client=judge_client)
            relevancy = judge_answer_relevancy(item.question, answer, client=judge_client)
        except ValueError:
            judge_errors += 1
            continue
        faiths.append(verdict.faithfulness)
        rels.append(relevancy)

    refused = 0
    for item in out_corpus:
        answer, _ = _answer_for(item, retriever, gen_client, k=k)
        if answer.refused:
            refused += 1

    n_judged = len(faiths)
    n_out = len(out_corpus)
    return EvalReport(
        ir=ir,
        faithfulness=(sum(faiths) / n_judged) if n_judged else 0.0,
        answer_relevancy=(sum(rels) / n_judged) if n_judged else 0.0,
        refusal_accuracy=(refused / n_out) if n_out else 1.0,
        n_in_corpus=counts["in_corpus"],
        n_out_corpus=counts["out_of_corpus"],
        judge_errors=judge_errors,
    )


def format_report(report: EvalReport) -> str:
    """Render an :class:`EvalReport` as the ``04-results.md`` markdown table. Pure."""
    n_judged = report.n_in_corpus - report.judge_errors
    rows = [
        ("Metric", "Value"),
        (
            f"Faithfulness (LLM-judge, mean over {n_judged} judged in-corpus)",
            f"{report.faithfulness:.3f}",
        ),
        (f"Recall@{report.ir.k}", f"{report.ir.recall_at_k:.3f}"),
        ("MRR", f"{report.ir.mrr:.3f}"),
        (f"nDCG@{report.ir.k}", f"{report.ir.ndcg_at_k:.3f}"),
        ("Answer relevancy (mean)", f"{report.answer_relevancy:.3f}"),
        (
            f"Refusal accuracy ({report.n_out_corpus} out-of-corpus)",
            f"{report.refusal_accuracy:.3f}",
        ),
        ("Judge parse errors (excluded)", str(report.judge_errors)),
    ]
    width = max(len(name) for name, _ in rows)
    lines = [f"| {name.ljust(width)} | {value} |" for name, value in rows]
    lines.insert(1, f"| {'-' * width} | {'-' * 5} |")
    return "\n".join(lines)


def _build_live_retriever(index_dir: Path) -> _Retriever:
    """Construct the deployed retriever stack (hybrid → cross-encoder re-rank) from the index."""
    from grc_rag.bm25 import BM25Index
    from grc_rag.embeddings import _INDEX_FILE
    from grc_rag.hybrid import HybridRetriever
    from grc_rag.rerank import CrossEncoderReranker, RerankingRetriever
    from grc_rag.retrieve import DenseRetriever

    hybrid = HybridRetriever(
        DenseRetriever.from_index(index_dir),
        BM25Index.from_chunks_jsonl(index_dir / _INDEX_FILE),
    )
    return RerankingRetriever(hybrid, CrossEncoderReranker(), candidate_k=50, top_k=6)


def main() -> None:
    """CLI: run the golden set through the live local retriever + Ollama generator + Anthropic
    judge and print the results table. Needs the built index and ``ANTHROPIC_API_KEY``."""
    import argparse

    from grc_rag.llm import AnthropicClient, OllamaClient

    parser = argparse.ArgumentParser(
        description="Run the grc-rag eval harness over the golden set."
    )
    parser.add_argument("--golden", type=Path, default=Path("data/golden/golden-set.jsonl"))
    parser.add_argument("--index-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    retriever = _build_live_retriever(args.index_dir)
    report = run_eval(
        args.golden,
        retriever=retriever,
        gen_client=OllamaClient(),
        # A faithfulness verdict decomposes the whole answer into claims + reasons, so it needs
        # generous output room — 1024 tokens truncates the JSON on long, many-claim answers.
        judge_client=AnthropicClient(max_tokens=4096),
        k=args.k,
    )
    print(format_report(report))


if __name__ == "__main__":
    main()
