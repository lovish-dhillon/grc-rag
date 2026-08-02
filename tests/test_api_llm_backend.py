"""Tests for the generator-backend selector used by the deployed app.

The generator is the one component that changes between a laptop and a container (ADR-0020), so
the selection is config-driven. These tests pin the two properties that matter: the default stays
the keyless local path, and an unrecognised name raises instead of silently falling back — a quiet
fallback would mean generating with a model nobody chose, invalidating the measured faithfulness
the CI gate depends on.

No client is ever *called* here, only constructed, so no model, key or network is involved.
"""

from __future__ import annotations

import pytest

from grc_rag.api import build_llm_client
from grc_rag.llm import OllamaClient

_BACKEND_ENV = "GRC_RAG_LLM"
_MODEL_ENV = "GRC_RAG_LLM_MODEL"


def test_defaults_to_the_keyless_local_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_BACKEND_ENV, raising=False)

    assert isinstance(build_llm_client(), OllamaClient)


def test_environment_selects_the_hosted_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container sets GRC_RAG_LLM=anthropic; the app must honour it without a code change."""
    pytest.importorskip("anthropic")
    from grc_rag.llm import AnthropicClient

    monkeypatch.setenv(_BACKEND_ENV, "anthropic")
    monkeypatch.delenv(_MODEL_ENV, raising=False)

    assert isinstance(build_llm_client(), AnthropicClient)


def test_model_override_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generator model is explicit config, so a deployment can pin one deliberately rather
    than inheriting the judge's default model by accident."""
    pytest.importorskip("anthropic")

    monkeypatch.setenv(_BACKEND_ENV, "anthropic")
    monkeypatch.setenv(_MODEL_ENV, "claude-sonnet-4-5")

    assert build_llm_client().model == "claude-sonnet-4-5"


@pytest.mark.parametrize("name", ["gpt4", "openai", "llama", ""])
def test_unknown_backend_raises_rather_than_falling_back(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_BACKEND_ENV, raising=False)

    with pytest.raises(ValueError, match="unknown GRC_RAG_LLM"):
        build_llm_client(name or "nonsense")


def test_explicit_argument_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_BACKEND_ENV, "anthropic")

    assert isinstance(build_llm_client("ollama"), OllamaClient)
