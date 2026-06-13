"""Shared test helpers.

Unit tests must stay fast and offline, so they inject deterministic stand-ins for
the two heavy dependencies: a *fake encoder* in place of the ~90 MB
sentence-transformer, and a *stub LLM client* in place of a live model. Both honour
the real contracts (``embeddings.Encoder`` / ``generate.LLMClient``), so retrieval
and cite-or-refuse logic are fully asserted without any download or network.
"""

from __future__ import annotations

import numpy as np


class StubLLMClient:
    """A canned :class:`~grc_rag.generate.LLMClient`.

    Returns a fixed ``response`` and records the last prompt it was given, so tests
    can both control the model's output and assert on what the prompt contained.
    """

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def _deterministic_vector(text: str, dim: int) -> list[float]:
    """A stable pseudo-vector for ``text`` — same input, same output, every run."""
    acc = [0.0] * dim
    for i, byte in enumerate(text.encode("utf-8")):
        acc[i % dim] += float(byte)
    return acc


class FakeEncoder:
    """A stand-in for SentenceTransformer with controllable outputs.

    Texts present in ``vectors_by_text`` return their mapped vector; everything
    else gets a deterministic pseudo-vector of width ``dim``.
    """

    def __init__(
        self, vectors_by_text: dict[str, list[float]] | None = None, *, dim: int = 4
    ) -> None:
        self._map = dict(vectors_by_text or {})
        self._dim = dim

    def encode(
        self, texts: list[str], convert_to_numpy: bool = True, **_kwargs: object
    ) -> np.ndarray:
        rows = [self._map.get(t, _deterministic_vector(t, self._dim)) for t in texts]
        return np.array(rows, dtype=np.float32)
