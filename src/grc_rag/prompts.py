"""Prompts as versioned, on-disk config — diff them, review them, roll them back.

A prompt is part of the system's behaviour, so it deserves the same treatment as code: live in
a file, carry a version, change under review. Phase 1 kept the cite-or-refuse prompt as a
string constant inside :mod:`grc_rag.generate`; here it moves to ``prompts/<id>.txt``, loaded
by id. The payoff is that you can revise the wording without touching Python, an ``Answer``
still records exactly which prompt produced it (``prompt_version``), and Phase 3 can attribute
a faithfulness change to a specific prompt revision.

Files are packaged *inside* the ``grc_rag`` package and read via stdlib
:mod:`importlib.resources`, so loading works the same whether the package is run from source or
installed as a wheel — no ``__file__`` path-guessing. One trailing newline (the editor's
convention) is stripped on load so a template file ends cleanly without forcing a trailing
blank into the rendered prompt.
"""

from __future__ import annotations

from importlib.resources import files

_PROMPTS_DIR = "prompts"


def load_prompt(prompt_id: str) -> str:
    """Return the text of ``prompts/<prompt_id>.txt`` (one trailing newline stripped).

    Raises ``ValueError`` if no such prompt file exists — a missing/typo'd prompt id is a
    fail-fast error, never a silently empty prompt.
    """
    resource = files("grc_rag").joinpath(_PROMPTS_DIR, f"{prompt_id}.txt")
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as error:
        raise ValueError(
            f"unknown prompt id '{prompt_id}': no file at {_PROMPTS_DIR}/{prompt_id}.txt"
        ) from error
    return text[:-1] if text.endswith("\n") else text
