# -*- coding: utf-8 -*-
"""Tests for literature_assistant/core/pdf_backends/.

Locks the byte-level identity contract for PyMuPDFBackend, which must mirror
the legacy _document_extraction PDF branch.

Placeholder strings are byte-level locked here — any change is a
contract break and should fail this test.
"""

from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path

import pytest

# Ensure the core path is importable for direct module access.
_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import (  # noqa: E402
    ENV_VAR,
    StructuredBlock,
    get_pdf_backend,
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


def test_get_pdf_backend_marker_env_still_yields_pymupdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "marker")
    backend = get_pdf_backend()
    assert backend.name == "pymupdf"
    assert backend.supports_blocks is False


@pytest.mark.parametrize(
    "raw_value",
    ["", "auto", "pymupdf", "pdfminer", "AUTO", "invalid_value", " marker "],
)
def test_get_pdf_backend_non_marker_values_yield_pymupdf(
    raw_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, raw_value)
    backend = get_pdf_backend()
    assert backend.name == "pymupdf"


def test_external_backend_module_not_in_core_source() -> None:
    assert importlib.util.find_spec("pdf_backends.marker_backend") is None


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
