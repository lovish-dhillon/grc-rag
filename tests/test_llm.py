"""Tests for the LLM client seam — specifically the env-configurable generator timeout.

The Ollama generator timeout defaults to a value tuned for a local GPU, but a slow CPU runner
(the manual CI ``judge-refresh`` path) needs a longer per-call budget. It is overridable via
``GRC_RAG_OLLAMA_TIMEOUT`` — config, not code (ADR-0018 / EVAL-002). These tests pin that
contract: default when unset, honoured when set, fail-fast on garbage. No network is touched —
we only construct the frozen dataclass and read its resolved ``timeout``.
"""

from __future__ import annotations

import pytest

from grc_rag.llm import _DEFAULT_OLLAMA_TIMEOUT, _OLLAMA_TIMEOUT_ENV, OllamaClient


def test_timeout_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_OLLAMA_TIMEOUT_ENV, raising=False)
    assert OllamaClient().timeout == _DEFAULT_OLLAMA_TIMEOUT


def test_timeout_reads_env_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_OLLAMA_TIMEOUT_ENV, "300")
    assert OllamaClient().timeout == 300.0


def test_explicit_timeout_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_OLLAMA_TIMEOUT_ENV, "300")
    # A caller passing the field explicitly is never overridden by the env default_factory.
    assert OllamaClient(timeout=45.0).timeout == 45.0


def test_non_numeric_env_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_OLLAMA_TIMEOUT_ENV, "not-a-number")
    with pytest.raises(ValueError, match=_OLLAMA_TIMEOUT_ENV):
        OllamaClient()
