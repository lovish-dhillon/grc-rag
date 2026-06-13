"""Tests for corpus ingestion.

The most important test in this file is the *deny guard* — proof that ISO/IEC
42001 (and any other paywalled standard) cannot enter the corpus through any
ingest entrypoint. The licensing boundary is an invariant, so it gets a test.

Unit tests never touch the network or a real PDF/model: PDF extraction is
exercised by monkeypatching the reader, HTML by a tiny inline fixture, and the
full pipeline by stubbing fetch + extract. A real end-to-end download lives behind
``RUN_INTEGRATION`` so the default suite stays fast and offline.
"""

from __future__ import annotations

import dataclasses
import json
import os

import pytest

from grc_rag import ingest


# --------------------------------------------------------------------------- #
# The deny guard — the licensing invariant, as a test
# --------------------------------------------------------------------------- #
def test_assert_allowed_rejects_iso() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        ingest._assert_allowed("iso-42001")


def test_assert_allowed_accepts_every_known_source() -> None:
    for spec in ingest.ALLOWED_SOURCES:
        ingest._assert_allowed(spec.doc_id)  # must not raise


def test_allowlist_excludes_iso() -> None:
    assert "iso-42001" not in {s.doc_id for s in ingest.ALLOWED_SOURCES}
    assert len(ingest.ALLOWED_SOURCES) == 3


def test_fetch_raw_rejects_denied_source(tmp_path) -> None:
    denied = ingest.SourceSpec(
        doc_id="iso-42001",
        title="ISO/IEC 42001",
        url="https://example.invalid/iso",
        fmt="pdf",
        license="paywalled",
    )
    with pytest.raises(ValueError):
        ingest.fetch_raw(denied, cache_dir=tmp_path)


# --------------------------------------------------------------------------- #
# clean_text — pure, and the heuristics it promises
# --------------------------------------------------------------------------- #
def test_clean_text_dehyphenates_line_wrapped_words() -> None:
    assert ingest.clean_text("compli-\nance") == "compliance"


def test_clean_text_collapses_whitespace_runs() -> None:
    assert ingest.clean_text("a    b\t\tc") == "a b c"


def test_clean_text_strips_page_furniture() -> None:
    raw = "Real clause text.\nPage 12 of 40\n42\nMore text."
    out = ingest.clean_text(raw)
    assert "Page 12 of 40" not in out
    assert "Real clause text." in out
    assert "More text." in out


def test_clean_text_is_pure() -> None:
    raw = "compli-\nance  x"
    _ = ingest.clean_text(raw)
    assert raw == "compli-\nance  x"


def test_clean_text_empty() -> None:
    assert ingest.clean_text("   \n  \n") == ""


# --------------------------------------------------------------------------- #
# extract_text — PDF via a stubbed reader, HTML via a tiny fixture
# --------------------------------------------------------------------------- #
def test_extract_text_pdf_joins_pages(tmp_path, monkeypatch) -> None:
    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_FakePage("Page one text."), _FakePage("Page two text.")]

    monkeypatch.setattr(ingest, "PdfReader", _FakeReader)
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 not-a-real-pdf")

    out = ingest.extract_text(pdf_path, "pdf")
    assert "Page one text." in out
    assert "Page two text." in out


def test_extract_text_html_drops_scripts(tmp_path) -> None:
    html = (
        "<html><body><h1>Article 1</h1><p>High-risk systems shall comply.</p>"
        "<script>var x = 1;</script><style>.a{color:red}</style></body></html>"
    )
    html_path = tmp_path / "x.html"
    html_path.write_text(html, encoding="utf-8")

    out = ingest.extract_text(html_path, "html")
    assert "High-risk systems shall comply." in out
    assert "var x = 1" not in out
    assert "color:red" not in out


def test_extract_text_rejects_unknown_format(tmp_path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest.extract_text(p, "txt")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Provenance + immutability
# --------------------------------------------------------------------------- #
def test_source_document_is_frozen() -> None:
    doc = ingest.SourceDocument(
        doc_id="d",
        title="t",
        source_url="u",
        license="l",
        retrieved_date="2026-06-12",
        text="text",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.text = "mutated"  # type: ignore[misc]


def test_source_spec_is_frozen() -> None:
    spec = ingest.ALLOWED_SOURCES[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.url = "mutated"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# fetch_raw — cache reuse means no network on a warm cache
# --------------------------------------------------------------------------- #
def test_fetch_raw_returns_cache_without_network(tmp_path) -> None:
    spec = ingest.ALLOWED_SOURCES[0]
    ext = "pdf" if spec.fmt == "pdf" else "html"
    cached = tmp_path / f"{spec.doc_id}.{ext}"
    cached.write_bytes(b"already cached")

    # No httpx stub installed: if this tried the network it would fail. It must not.
    out = ingest.fetch_raw(spec, cache_dir=tmp_path)
    assert out == cached
    assert out.read_bytes() == b"already cached"


# --------------------------------------------------------------------------- #
# ingest_corpus — the full wiring, fetch + extract stubbed to fixtures
# --------------------------------------------------------------------------- #
def test_ingest_corpus_chunks_and_persists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        ingest, "fetch_raw", lambda spec, *, cache_dir: cache_dir / f"{spec.doc_id}.raw"
    )
    # Enough text that each doc yields multiple chunks.
    monkeypatch.setattr(
        ingest, "extract_text", lambda _path, _fmt: "Governance obligations apply. " * 300
    )

    out_path = tmp_path / "processed" / "chunks.jsonl"
    chunks = ingest.ingest_corpus(
        cache_dir=tmp_path / "raw", out_path=out_path, retrieved_date="2026-06-12"
    )

    # Every allowed source is represented, and chunk ids carry their provenance prefix.
    doc_ids = {c.doc_id for c in chunks}
    assert doc_ids == {s.doc_id for s in ingest.ALLOWED_SOURCES}
    assert all(c.chunk_id.startswith(c.doc_id + "::") for c in chunks)

    # Persisted as valid, round-trippable jsonl with one chunk per line.
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(chunks)
    first = json.loads(lines[0])
    assert {"chunk_id", "doc_id", "text", "token_count", "start_token"} <= first.keys()


def test_load_chunks_jsonl_roundtrips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        ingest, "fetch_raw", lambda spec, *, cache_dir: cache_dir / f"{spec.doc_id}.raw"
    )
    monkeypatch.setattr(ingest, "extract_text", lambda _path, _fmt: "Some text here. " * 300)

    out_path = tmp_path / "chunks.jsonl"
    written = ingest.ingest_corpus(
        cache_dir=tmp_path, out_path=out_path, retrieved_date="2026-06-12"
    )
    loaded = ingest.load_chunks_jsonl(out_path)
    assert loaded == written  # frozen Chunks compare by value


# --------------------------------------------------------------------------- #
# Integration: a real download + extract. Off by default.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="network/real-source test; set RUN_INTEGRATION=1 to run",
)
def test_real_corpus_ingests_and_excludes_iso(tmp_path) -> None:
    out_path = tmp_path / "chunks.jsonl"
    chunks = ingest.ingest_corpus(cache_dir=tmp_path, out_path=out_path)
    assert len(chunks) > 0
    assert {c.doc_id for c in chunks} == {s.doc_id for s in ingest.ALLOWED_SOURCES}
