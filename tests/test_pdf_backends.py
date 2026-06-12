# -*- coding: utf-8 -*-
"""Tests for literature_assistant/core/pdf_backends/ (marker-rag-pipeline §2).

Locks the byte-level identity contract for PyMuPDFBackend (default,
must mirror legacy _document_extraction PDF branch) and the contract
shape of MarkerBackend's exception when marker-pdf is not installed.

Placeholder strings are byte-level locked here — any change is a
contract break and should fail this test.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Ensure the core path is importable for direct module access.
_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import (  # noqa: E402
    ENV_VAR,
    MarkerUnavailable,
    StructuredBlock,
    get_pdf_backend,
)
from pdf_backends.marker_backend import (  # noqa: E402
    MARKER_BLOCK_TYPE_MAPPING,
    MarkerBackend,
    map_marker_block_type,
)
from pdf_backends.pymupdf_backend import PyMuPDFBackend  # noqa: E402


# --------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------- #


def test_get_pdf_backend_default_pymupdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    backend = get_pdf_backend()
    assert backend.name == "pymupdf"
    assert backend.supports_blocks is False


def test_get_pdf_backend_marker_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "marker")
    backend = get_pdf_backend()
    assert backend.name == "marker"
    assert backend.supports_blocks is True


@pytest.mark.parametrize(
    "raw_value",
    ["", "auto", "pymupdf", "pdfminer", "AUTO", "invalid_value", " marker "],
)
def test_get_pdf_backend_non_marker_values_yield_pymupdf(
    raw_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # " marker " (whitespace-padded) is still marker after strip().
    monkeypatch.setenv(ENV_VAR, raw_value)
    backend = get_pdf_backend()
    if raw_value.strip().lower() == "marker":
        assert backend.name == "marker"
    else:
        assert backend.name == "pymupdf"


# --------------------------------------------------------------------- #
# PyMuPDFBackend — byte-level identity contract
# --------------------------------------------------------------------- #


def test_pymupdf_backend_returns_text_no_blocks_no_md(tmp_path: Path) -> None:
    """parse() returns 3-tuple; blocks and markdown_full always None."""
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    backend = PyMuPDFBackend()
    # We don't assert text here (depends on lib availability); only shape.
    text, blocks, md = backend.parse(pdf)
    assert isinstance(text, str)
    assert blocks is None
    assert md is None


def test_pymupdf_backend_returns_placeholder_when_both_libs_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both pymupdf and PyPDF2 missing → exact Chinese placeholder string.

    Placeholder is byte-level locked. Note the CHINESE comma ``，`` (U+FF0C),
    not ASCII ``,``.
    """
    # Block pymupdf import
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    # Block PyPDF2 import by raising ImportError when the module is loaded.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("pymupdf blocked for test")
        if name == "PyPDF2":
            raise ImportError("PyPDF2 blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    pdf = tmp_path / "missing-libs.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    backend = PyMuPDFBackend()
    text, blocks, md = backend.parse(pdf)
    expected = "[PDF 文件: missing-libs.pdf，需安装 pymupdf 或 PyPDF2 才能提取文本]"
    assert text == expected, repr(text)
    assert blocks is None
    assert md is None


def test_pymupdf_backend_returns_parse_failure_placeholder_on_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parse exception → ``[PDF 解析失败: {exc}]`` placeholder (byte-locked)."""
    fake_pymupdf = types.ModuleType("pymupdf")

    def fake_open(*_args, **_kwargs):
        raise RuntimeError("synthetic parse failure")

    fake_pymupdf.open = fake_open
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)

    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a real pdf")
    backend = PyMuPDFBackend()
    text, blocks, md = backend.parse(pdf)
    expected = "[PDF 解析失败: synthetic parse failure]"
    assert text == expected, repr(text)
    assert blocks is None
    assert md is None


def test_pymupdf_backend_fallback_to_pypdf2_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """pymupdf ImportError → falls back to PyPDF2 path (not placeholder)."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    # Fake PyPDF2 module with PdfReader that returns one page of known text.
    class _FakePage:
        def extract_text(self) -> str:
            return "fallback-pypdf2-page-1"

    class _FakeReader:
        def __init__(self, _fh):
            self.pages = [_FakePage(), _FakePage()]

    fake_pypdf2 = types.ModuleType("PyPDF2")
    fake_pypdf2.PdfReader = _FakeReader

    def fake_import(name: str, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("pymupdf blocked for test")
        if name == "PyPDF2":
            return fake_pypdf2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setitem(sys.modules, "PyPDF2", fake_pypdf2)

    pdf = tmp_path / "fallback.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    backend = PyMuPDFBackend()
    text, blocks, md = backend.parse(pdf)
    assert text == "fallback-pypdf2-page-1\n\nfallback-pypdf2-page-1"
    assert blocks is None
    assert md is None


# --------------------------------------------------------------------- #
# MarkerBackend — unavailable + mapping contract
# --------------------------------------------------------------------- #


def test_marker_backend_raises_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """marker-pdf missing → MarkerUnavailable raised inside parse()."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name: str, *args, **kwargs):
        if name.startswith("marker"):
            raise ImportError(f"{name} blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    pdf = tmp_path / "stub.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    backend = MarkerBackend()
    with pytest.raises(MarkerUnavailable):
        backend.parse(pdf)


@pytest.mark.parametrize(
    "block_type, expected_chunk_type",
    [
        ("Heading", "heading"),
        ("SectionHeader", "heading"),
        ("PageHeader", "heading"),
        ("Text", "narrative"),
        ("Paragraph", "narrative"),
        ("TextBlock", "narrative"),
        ("Footnote", "narrative"),       # 2026-06-12 真实 reparse 实测
        ("PageFooter", "narrative"),     # 页脚 — 噪声大但映射为 narrative,future retriever 加权降权
        ("Table", "table"),
        ("TableGroup", "table"),
        ("Equation", "formula"),
        ("Formula", "formula"),
        ("FigureCaption", "figure_caption"),
        ("Caption", "figure_caption"),
        ("TableCaption", "figure_caption"),
        ("FigureGroup", "figure_caption"),  # 2026-06-12 真实 reparse 实测
        ("PictureGroup", "figure_caption"), # 2026-06-12 真实 reparse 实测
        ("List", "list"),
        ("ListItem", "list"),
        ("ListGroup", "list"),           # 2026-06-12 真实 reparse 实测
        ("Code", "code"),
        ("CodeBlock", "code"),
        ("Image", "image_caption"),
        ("Figure", "image_caption"),
        ("Picture", "image_caption"),
    ],
)
def test_marker_block_type_mapping(block_type: str, expected_chunk_type: str) -> None:
    """Stable block_type → chunk_type mapping for all known marker types."""
    assert map_marker_block_type(block_type) == expected_chunk_type
    # MARKER_BLOCK_TYPE_MAPPING dict must agree
    assert MARKER_BLOCK_TYPE_MAPPING[block_type] == expected_chunk_type


def test_marker_mapping_table_covers_real_reparse_observed_types() -> None:
    """Lock: 2026-06-12 真实 reparse(proj_ec65a4e90854 / Reis 2013 Ti-6Al-4V 论文)
    出现过的 ListGroup/FigureGroup/PictureGroup/Footnote 4 个 block_type 必须
    在映射表里 — 不再走 unknown fallback。
    """
    observed_in_real_reparse = ["ListGroup", "FigureGroup", "PictureGroup", "Footnote"]
    for bt in observed_in_real_reparse:
        assert bt in MARKER_BLOCK_TYPE_MAPPING, (
            f"{bt} 在真实 reparse 出现过却未在映射表;请勿删,否则 fallback narrative 警告会回来"
        )


@pytest.mark.parametrize("unknown_type", [None, "", "FuturisticBlock", "UnknownType"])
def test_marker_unknown_block_type_falls_back_to_narrative(unknown_type) -> None:
    """Unknown / None block_type → ``"narrative"`` graceful fallback."""
    assert map_marker_block_type(unknown_type) == "narrative"


# --------------------------------------------------------------------- #
# StructuredBlock dataclass shape
# --------------------------------------------------------------------- #


def test_structured_block_is_frozen_and_has_required_fields() -> None:
    block = StructuredBlock(
        block_id="b0",
        page=1,
        bbox=[0.0, 0.0, 100.0, 50.0],
        block_type="Text",
        markdown="hello",
    )
    # Required fields present
    assert block.block_id == "b0"
    assert block.page == 1
    assert block.bbox == [0.0, 0.0, 100.0, 50.0]
    assert block.block_type == "Text"
    assert block.markdown == "hello"
    # Optional defaults
    assert block.html is None
    assert block.image_paths == []
    assert block.table_csv is None
    assert block.equation_latex is None
    assert block.section_heading is None
    # Frozen
    with pytest.raises(Exception):  # FrozenInstanceError
        block.markdown = "mutated"  # type: ignore[misc]
