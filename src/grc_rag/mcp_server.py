"""MCP boundary — the cite-or-refuse pipeline exposed as a Model Context Protocol tool.

Why this exists at all. The FastAPI boundary (ADR-0015) serves a *human* through the React
console. An assistant is a different consumer with the same need: when Claude is asked about the
EU AI Act it will answer from parametric memory, confidently and sometimes wrongly. Pointing it at
this corpus over MCP replaces that guess with a grounded answer plus the exact clause — and, more
importantly, lets it **refuse**. A model that can say "the corpus does not support this" is worth
more in GRC than one that always produces prose.

The same three commitments as :mod:`grc_rag.api` apply, for the same reasons:

* **Reuse the seams, never fork the pipeline.** The tool calls the deployed
  :func:`~grc_rag.enforce.answer_with_enforcement` over the injected retriever. All the logic that
  makes the system trustworthy stays where it already lives; this module adds a *transport*.

* **A refusal is a successful result, not an error.** The tool returns
  ``{"refused": true, "citations": []}`` and the sentinel text. Raising here would teach the calling
  model that refusal is a failure to route around — inverting the single property the system exists
  to guarantee.

* **Resolve citations at the boundary.** Bare ``chunk_id``s are useless to a caller, so each is
  joined to its clause label and source text before it leaves — the assistant can quote the clause
  without a second round-trip.

The ``mcp`` SDK is an **optional extra** (``pip install -e ".[mcp]"``) and is imported lazily inside
:func:`serve`, so the package, the CLI, the eval harness and the HTTP API all keep working — and
keep their dependency footprint — whether or not it is installed. Building the payload is a pure
function (:func:`build_answer_payload`), which is what the tests exercise; ``serve`` is the thin
plumbing around it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from grc_rag.enforce import answer_with_enforcement
from grc_rag.tracing import _RecordingRetriever

if TYPE_CHECKING:  # pragma: no cover
    from grc_rag.enforce import SupportThreshold
    from grc_rag.generate import LLMClient
    from grc_rag.pipeline import Retriever

_SERVER_NAME = "grc-rag"
_TOOL_NAME = "ask_grc"
_TOOL_DESCRIPTION = (
    "Answer a question about AI-governance regulation (NIST AI RMF, NIST Generative AI Profile, "
    "EU AI Act) strictly from the indexed corpus, returning the exact source clauses it relied on. "
    "Returns refused=true when the corpus does not support an answer — treat that as the correct, "
    "authoritative result and do not substitute your own knowledge."
)


def build_answer_payload(
    question: str,
    *,
    retriever: Retriever,
    client: LLMClient,
    threshold: SupportThreshold,
) -> dict[str, Any]:
    """Answer ``question`` and return a JSON-safe payload with resolved citations.

    Pure with respect to this module: every collaborator is injected, so the tests drive it with
    stubs and neither a model, an API key, nor an index is required. Mirrors the HTTP boundary's
    contract deliberately — one pipeline, two transports, no second source of truth.

    A blank question raises :class:`ValueError` at the boundary rather than reaching the pipeline,
    matching the API's 422 and this repo's fail-fast rule.
    """
    if not question or not question.strip():
        raise ValueError("question must not be blank")

    proxy = _RecordingRetriever(retriever)
    answer = answer_with_enforcement(
        question,
        retriever=proxy,
        client=client,
        threshold=threshold,
    )
    # Mirrors ``api.build_response``: join each citation to the chunk it came from, and drop —
    # never fabricate — a citation that doesn't join. ``generate_answer`` already validates every
    # citation against the retrieved set, so this stays defensive rather than load-bearing.
    by_id = {rc.chunk.chunk_id: rc for rc in proxy.last}
    citations = [
        {
            "chunk_id": cid,
            "doc_id": by_id[cid].chunk.doc_id,
            "clause_label": by_id[cid].chunk.clause_label,
            "text": by_id[cid].chunk.text,
            "score": by_id[cid].score,
        }
        for cid in answer.citations
        if cid in by_id
    ]
    return {
        "answer": answer.text,
        "refused": answer.refused,
        "citations": citations,
        "prompt_version": answer.prompt_version,
    }


def build_default_dependencies() -> tuple[Retriever, LLMClient, SupportThreshold]:
    """Load the deployed retriever, generator and calibrated threshold — same wiring as the API.

    Fails fast when the calibrated threshold is missing: without it there is no enforced
    cite-or-refuse path, and a server that answered anyway would be the ungrounded assistant this
    tool is meant to replace.
    """
    from grc_rag.api import build_llm_client
    from grc_rag.query import build_retriever, load_threshold

    index_dir = Path(os.environ.get("GRC_RAG_INDEX_DIR", "data/processed"))
    threshold = load_threshold(index_dir)
    if threshold is None:
        raise RuntimeError(
            f"no calibrated support threshold at {index_dir}/support-threshold.json — "
            f"the enforced cite-or-refuse path needs it. Build the index + calibrate first."
        )
    return build_retriever(index_dir), build_llm_client(), threshold


def serve() -> None:  # pragma: no cover - transport plumbing (integration-only)
    """Run the MCP server over stdio, exposing :data:`_TOOL_NAME`.

    Stdio is the transport every MCP client supports and needs no port, no CORS and no auth story —
    the right default for a tool a developer wires into their own assistant. The heavy objects load
    once, before the loop starts, so the first tool call is not penalised.
    """
    from mcp.server.fastmcp import FastMCP

    retriever, client, threshold = build_default_dependencies()
    server = FastMCP(_SERVER_NAME)

    @server.tool(name=_TOOL_NAME, description=_TOOL_DESCRIPTION)
    def ask_grc(question: str) -> dict[str, Any]:
        return build_answer_payload(
            question, retriever=retriever, client=client, threshold=threshold
        )

    server.run()


if __name__ == "__main__":  # pragma: no cover
    serve()
