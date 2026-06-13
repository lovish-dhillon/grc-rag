"""Tests for the end-to-end query pipeline.

A stub retriever and a stub LLM let us assert the wiring (retrieve → generate)
without a model or a built index.
"""

from __future__ import annotations

from conftest import StubLLMClient
from grc_rag.chunking import Chunk
from grc_rag.pipeline import answer_question
from grc_rag.retrieve import RetrievedChunk


class StubRetriever:
    """Returns a fixed set of chunks (top-k capped) for any query."""

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        self._chunks = chunks

    def retrieve(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        return tuple(RetrievedChunk(chunk=c, score=1.0) for c in self._chunks[:k])


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id=chunk_id.split("::")[0], text=text, token_count=5, start_token=0
    )


def test_answer_question_grounded_end_to_end() -> None:
    retriever = StubRetriever((_chunk("eu-ai-act::4", "Providers shall ensure compliance."),))
    client = StubLLMClient("Providers shall ensure compliance [eu-ai-act::4].")
    answer = answer_question("What must providers do?", retriever=retriever, client=client)
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::4",)


def test_answer_question_refuses_when_model_refuses() -> None:
    retriever = StubRetriever((_chunk("eu-ai-act::4", "irrelevant"),))
    client = StubLLMClient("Not supported by the corpus.")
    answer = answer_question("Out of scope?", retriever=retriever, client=client)
    assert answer.refused is True
    assert answer.citations == ()


def test_answer_question_passes_k_through() -> None:
    retriever = StubRetriever(tuple(_chunk(f"eu-ai-act::{i}", f"text {i}") for i in range(20)))
    client = StubLLMClient("Answer [eu-ai-act::0].")
    # k is forwarded to the retriever; a grounded citation still resolves.
    answer = answer_question("q?", retriever=retriever, client=client, k=3)
    assert answer.refused is False
    assert answer.citations == ("eu-ai-act::0",)
