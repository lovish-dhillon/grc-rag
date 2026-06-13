"""Pipeline — the Phase 1 deliverable, end to end.

One call ties the whole loop together: retrieve the top-k chunks for a question,
then generate a cited answer (or an honest refusal) from them. This is the seam a
CLI or the Streamlit demo sits on top of.

Both collaborators are injected behind tiny contracts (:class:`Retriever`,
:class:`~grc_rag.generate.LLMClient`), so the pipeline is trivially testable with
stubs and indifferent to whether retrieval is dense-only (Phase 1) or hybrid +
re-ranked (Phase 2).
"""

from __future__ import annotations

from typing import Protocol

from grc_rag.generate import Answer, LLMClient, generate_answer
from grc_rag.retrieve import RetrievedChunk


class Retriever(Protocol):
    """Anything that can return the top-k chunks for a query."""

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]: ...


def answer_question(
    question: str,
    *,
    retriever: Retriever,
    client: LLMClient,
    k: int = 10,
) -> Answer:
    """Retrieve top-k chunks for ``question`` and answer under cite-or-refuse."""
    chunks = retriever.retrieve(question, k=k)
    return generate_answer(question, chunks, client=client)
