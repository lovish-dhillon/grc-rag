"""Corpus ingestion — turn published standards into clean, chunked, cited-able text.

Retrieval can only ever surface text that was ingested correctly. A mis-extracted
PDF column, a page header glued into the middle of a sentence, or a lost
``doc_id`` caps the quality of *everything* downstream — no embedder or LLM
recovers an answer that ingestion mangled. So this module's job is unglamorous but
load-bearing: fetch the source, pull clean text out of it, attach provenance, and
hand whole documents to the chunker.

This is also where the project's **licensing invariant becomes code**. The corpus
is freely-redistributable standards only (NIST AI RMF, NIST Generative AI Profile,
EU AI Act). ISO/IEC 42001 is copyrighted and paywalled — mapping to its *clause
IDs* is lawful, shipping its *text* is not. We don't enforce that by being careful;
we enforce it with an allowlist and a deny guard (:func:`_assert_allowed`) that
every ingest entrypoint must pass through. There is no code path that ingests an
arbitrary URL.

Everything here follows the same discipline as :mod:`grc_rag.chunking`: frozen
dataclasses, pure functions, and boundary checks that raise ``ValueError`` loudly
rather than emit silent garbage.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from pypdf import PdfReader
from selectolax.parser import HTMLParser

from grc_rag.chunking import Chunk
from grc_rag.structure import split_structured

SourceFormat = Literal["pdf", "html"]


@dataclass(frozen=True)
class SourceSpec:
    """How to obtain one source document — the input to ingestion.

    ``doc_id`` is the stable identity of the source: it prefixes every
    ``chunk_id`` (``doc_id::index``) so a citation traces straight back here, and
    it is the key the deny guard checks against the allowlist.
    """

    doc_id: str
    title: str
    url: str
    fmt: SourceFormat
    license: str


@dataclass(frozen=True)
class SourceDocument:
    """A fetched, cleaned source with the provenance a citation needs.

    ``retrieved_date`` records *when* the text was pulled — standards are revised,
    and "which version did this answer come from" is a real GRC question.
    """

    doc_id: str
    title: str
    source_url: str
    license: str
    retrieved_date: str
    text: str


# --------------------------------------------------------------------------- #
# The allowlist — freely-redistributable standards only. ISO/IEC 42001 is absent
# BY DESIGN (copyrighted, paywalled). See 03-decisions.md.
# --------------------------------------------------------------------------- #
ALLOWED_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        doc_id="nist-ai-rmf",
        title="NIST AI Risk Management Framework (AI 100-1)",
        url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        fmt="pdf",
        license="U.S. Government work — not subject to domestic copyright (17 U.S.C. §105); freely redistributable",
    ),
    SourceSpec(
        doc_id="nist-genai-profile",
        title="NIST Generative AI Profile (AI 600-1)",
        url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
        fmt="pdf",
        license="U.S. Government work — not subject to domestic copyright (17 U.S.C. §105); freely redistributable",
    ),
    SourceSpec(
        doc_id="eu-ai-act",
        title="Regulation (EU) 2024/1689 (Artificial Intelligence Act)",
        url="https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32024R1689",
        fmt="html",
        license="© European Union, https://eur-lex.europa.eu — reuse permitted with source acknowledgement",
    ),
)

_ALLOWED_IDS = frozenset(spec.doc_id for spec in ALLOWED_SOURCES)


def _assert_allowed(doc_id: str) -> None:
    """Gate every ingest entrypoint. Raise unless ``doc_id`` is on the allowlist.

    This is the licensing invariant expressed as code: a source not explicitly
    listed cannot be ingested, so ISO/IEC 42001 and other paywalled standards are
    excluded *structurally*, not by convention.
    """
    if doc_id not in _ALLOWED_IDS:
        raise ValueError(
            f"Refusing to ingest '{doc_id}': not in the freely-redistributable "
            f"allowlist {sorted(_ALLOWED_IDS)}. ISO/IEC 42001 and other paywalled "
            f"standards are excluded by policy (see 03-decisions.md)."
        )


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def fetch_raw(spec: SourceSpec, *, cache_dir: Path, timeout: float = 30.0) -> Path:
    """Download ``spec`` into ``cache_dir`` and return the local path.

    The download is cached on ``doc_id``: a warm cache means a build is
    reproducible and runs offline, and re-ingesting doesn't re-hit the source.
    Raises for a denied source (before any network call) and for a non-2xx
    response (fail fast rather than cache an error page).
    """
    _assert_allowed(spec.doc_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ext = "pdf" if spec.fmt == "pdf" else "html"
    dest = cache_dir / f"{spec.doc_id}.{ext}"
    if dest.exists():
        return dest

    response = httpx.get(spec.url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #
def extract_text(raw_path: Path, fmt: SourceFormat) -> str:
    """Pull raw (uncleaned) text out of a downloaded source by format."""
    if fmt == "pdf":
        return _extract_pdf(raw_path)
    if fmt == "html":
        return _extract_html(raw_path)
    raise ValueError(f"Unsupported source format: {fmt!r} (expected 'pdf' or 'html')")


def _extract_pdf(raw_path: Path) -> str:
    """Concatenate the text layer of every page. (No OCR — our sources have one.)"""
    reader = PdfReader(str(raw_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_html(raw_path: Path) -> str:
    """Take the visible body text, dropping script/style noise.

    selectolax parses the real DOM (robust on EUR-Lex's deeply-nested markup),
    we strip non-content nodes, then read the body's text. Chosen over a
    hand-rolled ``html.parser`` for robustness, and over trafilatura for size.
    """
    html = raw_path.read_text(encoding="utf-8", errors="replace")
    tree = HTMLParser(html)
    for node in tree.css("script, style"):
        node.decompose()
    body = tree.body or tree.root
    return body.text(separator="\n") if body is not None else ""


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
# A line that is nothing but a page number ("12") or a footer ("Page 12 of 40").
# Heuristic: in extracted regulation text a bare-number line is almost always page
# furniture, not content. Numbered headings keep their heading text on the line.
_PAGE_FURNITURE = re.compile(r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+)\s*$", re.IGNORECASE)
_HYPHEN_LINEBREAK = re.compile(r"-\n\s*")
_HORIZONTAL_WS = re.compile(r"[ \t]+")
_AROUND_NEWLINE = re.compile(r"\s*\n\s*")
_BLANK_RUN = re.compile(r"\n{3,}")


def clean_text(raw: str) -> str:
    """Normalise extracted text for chunking. Pure — returns a new string.

    Order matters:

    1. Drop page furniture line-by-line (page numbers, "Page x of y") before any
       reflow, while line structure still identifies them.
    2. Re-join words split across a line break (``"compli-\\nance"`` →
       ``"compliance"``) — PDF extraction leaves these everywhere.
    3. Collapse horizontal whitespace runs, trim around newlines, and cap blank
       runs so token sizing isn't thrown off by extraction artefacts.
    """
    kept_lines = [ln for ln in raw.splitlines() if not _PAGE_FURNITURE.match(ln)]
    text = "\n".join(kept_lines)
    text = _HYPHEN_LINEBREAK.sub("", text)
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _AROUND_NEWLINE.sub("\n", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Compose: load one source, ingest the whole corpus
# --------------------------------------------------------------------------- #
def load_source(
    spec: SourceSpec, *, cache_dir: Path, retrieved_date: str | None = None
) -> SourceDocument:
    """Fetch → extract → clean → wrap one source with provenance.

    ``retrieved_date`` defaults to today (ISO ``YYYY-MM-DD``); pass it explicitly
    for reproducible runs and tests.
    """
    _assert_allowed(spec.doc_id)
    raw_path = fetch_raw(spec, cache_dir=cache_dir)
    text = clean_text(extract_text(raw_path, spec.fmt))
    return SourceDocument(
        doc_id=spec.doc_id,
        title=spec.title,
        source_url=spec.url,
        license=spec.license,
        retrieved_date=retrieved_date or date.today().isoformat(),
        text=text,
    )


def ingest_corpus(
    *,
    cache_dir: Path,
    out_path: Path,
    sources: tuple[SourceSpec, ...] = ALLOWED_SOURCES,
    retrieved_date: str | None = None,
) -> tuple[Chunk, ...]:
    """Ingest every source in ``sources``, chunk it, and persist all chunks.

    Returns the full tuple of chunks and writes them to ``out_path`` as JSON Lines
    (one :class:`~grc_rag.chunking.Chunk` per line) for the retrieval stage to load.
    """
    all_chunks: list[Chunk] = []
    for spec in sources:
        document = load_source(spec, cache_dir=cache_dir, retrieved_date=retrieved_date)
        # Structure-aware split (PRD-P2-07): chunks carry a human clause_label and never span
        # an Article/subcategory boundary; unstructured text falls back to flat token windows.
        all_chunks.extend(split_structured(document.doc_id, document.text))

    chunks = tuple(all_chunks)
    _write_chunks_jsonl(out_path, chunks)
    return chunks


# --------------------------------------------------------------------------- #
# Persistence — the contract with the retrieval stage (PRD-P1-02)
# --------------------------------------------------------------------------- #
def _write_chunks_jsonl(out_path: Path, chunks: tuple[Chunk, ...]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")


def load_chunks_jsonl(path: Path) -> tuple[Chunk, ...]:
    """Read chunks back from a JSON Lines file written by :func:`ingest_corpus`."""
    with path.open(encoding="utf-8") as handle:
        return tuple(Chunk(**json.loads(line)) for line in handle if line.strip())
