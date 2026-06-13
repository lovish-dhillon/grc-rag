"""BM25 lexical retrieval — find chunks that share the query's actual *words*.

Dense retrieval (:mod:`grc_rag.retrieve`) matches *meaning*, but it is blind to exact
tokens. Ask "which AI practices are prohibited" and the embedder can rank the EU AI Act
Art. 5 list low even though that chunk literally contains the word *prohibited* — the very
failure logged as the Phase-1 over-refusal. BM25 is the complement: a classic lexical ranker
that scores a chunk by how many query terms it contains, weighted by how *rare* those terms
are across the corpus (so "prohibited" counts for far more than "the"). Exact clause numbers,
acronyms, and rare legal terms — where dense is weakest — are exactly where BM25 is strongest.

We don't reimplement BM25; we wrap the tiny, single-purpose ``rank-bm25`` library so every
line stays explainable (no LangChain retriever magic). The only judgement we own is
**tokenisation** — deliberately the simplest thing that works: lowercase, split on
non-alphanumerics. No stemmer or stopword list yet; ``rank-bm25``'s IDF term already
down-weights common words, and a stemmer is a capability to add only if recall demands it.

Same discipline as the rest of the package: the index is built once over the chunks, row ``i``
maps to chunk ``i`` (so a result is directly citable), and bad input fails fast with
``ValueError`` rather than returning silent garbage.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from grc_rag.chunking import Chunk
from grc_rag.ingest import load_chunks_jsonl
from grc_rag.retrieve import RetrievedChunk

# Split on runs of non-alphanumerics. Keeps digits (clause numbers matter) and drops the
# punctuation that would otherwise glue onto tokens. "Article 5(1)" → ["article", "5", "1"].
_NON_ALNUM = re.compile(r"\W+")


def tokenize(text: str) -> list[str]:
    """Lowercase ``text`` and split into alphanumeric tokens, dropping empties. Pure."""
    return [token for token in _NON_ALNUM.split(text.lower()) if token]


class BM25Index:
    """A BM25 index over the corpus chunks, answering top-k lexical queries.

    Build it from the persisted chunks with :meth:`from_chunks_jsonl`, or directly from a
    chunk tuple (tests). Row ``i`` of the BM25 corpus is chunk ``i``, so a score maps straight
    back to a citable :class:`~grc_rag.chunking.Chunk`.
    """

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        # An empty index can't answer anything — fail fast rather than build a useless one.
        if not chunks:
            raise ValueError("cannot build a BM25 index over an empty chunk set")
        self._chunks = tuple(chunks)
        self._bm25 = BM25Okapi([tokenize(chunk.text) for chunk in self._chunks])

    @classmethod
    def from_chunks_jsonl(cls, chunks_path: Path) -> BM25Index:
        """Build the index from a JSON Lines chunk file (e.g. the dense index's
        ``index.jsonl``, so both retrievers index the exact same chunk set)."""
        return cls(load_chunks_jsonl(chunks_path))

    def __len__(self) -> int:
        return len(self._chunks)

    def search(self, query: str, *, k: int = 10) -> tuple[RetrievedChunk, ...]:
        """Return the ``k`` chunks with the highest BM25 score, highest first.

        ``RetrievedChunk.score`` here is the raw BM25 score (an unbounded relevance score on
        its own scale; higher = more lexically relevant). Raises ``ValueError`` on a blank
        query or non-positive ``k``.
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if k <= 0:
            raise ValueError(f"k must be > 0, got {k}")

        scores = np.asarray(self._bm25.get_scores(tokenize(query)), dtype=np.float64)
        top_k = min(k, scores.shape[0])
        # Stable sort so the many zero-score ties (chunks with no query-term overlap) keep a
        # deterministic, corpus-order ranking instead of an arbitrary one.
        ranked = np.argsort(-scores, kind="stable")[:top_k]
        return tuple(
            RetrievedChunk(chunk=self._chunks[int(i)], score=float(scores[int(i)])) for i in ranked
        )
