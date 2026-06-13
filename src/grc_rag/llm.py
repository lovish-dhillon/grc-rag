"""LLM clients — concrete implementations of the :class:`~grc_rag.generate.LLMClient` seam.

Phase 1 ships a thin wrapper over a **local Ollama** server. That keeps generation at zero
marginal cost, needs no API key, and stays local-first like the rest of the pipeline. Ollama
itself is an external binary (``brew install ollama``; ``ollama pull llama3.1:8b``), not a
Python dependency — so that client only needs ``httpx``, which we already use for ingestion.

Phase 3 adds a second client, :class:`AnthropicClient` — the **first** place a cloud/frontier
model + API key enters the project. It exists for the LLM-judge (faithfulness / relevancy):
a local 7B model is too weak to be a trustworthy arbiter of the very property the project
rests on, so the judge is the one capability where an API call is justified. It sits behind
the **same** one-method contract — the cite-or-refuse logic in :mod:`grc_rag.generate` and the
judge in :mod:`grc_rag.judge` neither know nor care which client they hold. The key is read
from the environment (never hardcoded) and a missing key fails fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class OllamaClient:
    """Generate completions from a locally-running Ollama model.

    Two options matter for cite-or-refuse:

    * **temperature 0** — we want the most deterministic, grounded output, not
      creative paraphrase.
    * **num_ctx** — the context window must be large enough to hold the packed
      chunks (~700 tokens each, several at a time) *plus* the instructions. Ollama's
      default (2048) would silently truncate the chunks, starving the model of the
      very text it must cite, so we set it explicitly.
    """

    # qwen2.5:7b is the locally-installed, end-to-end-verified default; llama3.1:8b
    # (or any Ollama model) is a drop-in alternative behind the same seam.
    model: str = "qwen2.5:7b"
    host: str = "http://localhost:11434"
    timeout: float = 120.0
    num_ctx: int = 8192

    def complete(self, prompt: str) -> str:
        response = httpx.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["response"]


# The cheapest adequate Claude tier for a constrained entails/doesn't-entail judgement; pinned
# to a snapshot (not a floating alias) so the gate's arbiter is reproducible. Confirm against
# the Anthropic docs if re-pinning. See PRD-P3-09.
_DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_API_KEY_ENV = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class AnthropicClient:
    """Generate completions from a hosted Claude model — the LLM-judge's arbiter.

    Determinism is the priority, exactly as for :class:`OllamaClient`: **temperature 0** so a
    judge verdict doesn't flap run-to-run (the load-bearing risk for a CI gate). The key is
    read from ``ANTHROPIC_API_KEY`` at call time and a missing key raises immediately with a
    clear message — never a hardcoded secret, never a silent skip. The ``anthropic`` SDK is
    imported lazily so merely importing this module (e.g. for the local Ollama path) doesn't
    require the package to be installed.
    """

    model: str = _DEFAULT_JUDGE_MODEL
    temperature: float = 0.0
    max_tokens: int = 1024

    def complete(self, prompt: str) -> str:
        api_key = os.environ.get(_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                f"{_API_KEY_ENV} is not set — the Anthropic LLM-judge needs an API key in the "
                f"environment (never hardcode it). Export {_API_KEY_ENV} or run the keyless "
                f"local path instead."
            )
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate the text blocks; a judge prompt yields a single text block in practice.
        return "".join(block.text for block in message.content if block.type == "text")
