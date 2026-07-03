# -*- coding: utf-8 -*-
"""Tests for literature_assistant/core/pdf_backends/.

Locks the byte-level identity contract for PyMuPDFBackend, which must mirror
the legacy _document_extraction PDF branch.

Placeholder strings are byte-level locked here — any change is a
contract break and should fail this test.
"""

from __future__ import annotations

import io
import sys
import types
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

# Ensure the core path is importable for direct module access.
_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from routers.resources_router import _document_extraction as document_extraction  # noqa: E402
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


class _FakeRect:
    """Minimal page rectangle shape consumed by bbox normalization."""

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _FakePage:
    """Minimal PyMuPDF page test double with configurable raw blocks."""

    rect = _FakeRect(500.0, 500.0)

    def __init__(self, image_bytes: bytes, image_ext: str) -> None:
        self._blocks = [
            {
                "type": 1,
                "bbox": [40.0, 40.0, 260.0, 200.0],
                "image": image_bytes,
                "ext": image_ext,
            },
            _fake_text_block([40.0, 220.0, 260.0, 250.0], "Fig. 1 Weld surface morphology"),
        ]

    def get_text(self, _mode: str, *, sort: bool = False) -> dict[str, Any]:
        return {"blocks": list(self._blocks)}


class _FakePageWithBlocks:
    """Minimal PyMuPDF page test double with caller-supplied blocks."""

    rect = _FakeRect(600.0, 800.0)

    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        self._blocks = blocks

    def get_text(self, _mode: str, *, sort: bool = False) -> dict[str, Any]:
        return {"blocks": list(self._blocks)}


class _FakeDocument:
    """Context-manager document test double returned by pymupdf.open."""

    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def __enter__(self) -> "_FakeDocument":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self) -> Any:
        return iter([self._page])


def _image_bytes(format_name: str) -> bytes:
    """Return small valid raster bytes in the requested Pillow format."""

    output = io.BytesIO()
    Image.new("RGB", (120, 80), (80, 120, 180)).save(output, format=format_name)
    return output.getvalue()


def _fake_text_block(bbox: list[float], text: str) -> dict[str, Any]:
    """Return a PyMuPDF-like text block fixture."""

    return {
        "type": 0,
        "bbox": bbox,
        "lines": [
            {
                "spans": [
                    {"text": text},
                ]
            }
        ],
    }


def _fake_image_block(bbox: list[float], image_bytes: bytes, ext: str = "jpeg") -> dict[str, Any]:
    """Return a PyMuPDF-like image block fixture."""

    return {
        "type": 1,
        "bbox": bbox,
        "image": image_bytes,
        "ext": ext,
    }


def test_pymupdf_visual_asset_transcodes_browser_unsafe_ext_to_png(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Browser-unsafe embedded PDF images must not be stored behind fake .png names."""

    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.open = lambda _path: _FakeDocument(_FakePage(_image_bytes("BMP"), "bmp"))
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)

    source_pdf = tmp_path / "paper.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    project_data_root = tmp_path / "project"

    blocks = document_extraction._extract_pymupdf_visual_blocks(
        "paper.pdf",
        source_pdf,
        project_data_root=project_data_root,
    )

    assert blocks is not None
    image_paths = [path for block in blocks for path in block.image_paths]
    assert len(image_paths) == 1
    assert image_paths[0].endswith(".png")
    output_path = project_data_root / image_paths[0]
    assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(output_path) as image:
        assert image.format == "PNG"


def test_pymupdf_visual_asset_does_not_bind_body_fig_mentions_to_distant_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Narrative paragraphs mentioning a figure must not steal unrelated assets."""

    image_bytes = _image_bytes("JPEG")
    blocks_fixture = [
        _fake_image_block([40.0, 80.0, 280.0, 190.0], image_bytes),
        _fake_text_block([100.0, 205.0, 230.0, 215.0], "Fig. 2. Configuration of tensile samples."),
        _fake_text_block(
            [40.0, 270.0, 290.0, 360.0],
            "Fig. 3 presents the weld surface morphologies of the 1#-4# sample. "
            "The weld widths and defects are discussed in the text.",
        ),
        _fake_image_block([100.0, 500.0, 500.0, 725.0], image_bytes),
        _fake_text_block([205.0, 735.0, 390.0, 745.0], "Fig. 3. Weld morphology: (a) 1#; (b) 2#."),
    ]
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.open = lambda _path: _FakeDocument(_FakePageWithBlocks(blocks_fixture))
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)

    source_pdf = tmp_path / "paper.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    project_data_root = tmp_path / "project"

    blocks = document_extraction._extract_pymupdf_visual_blocks(
        "paper.pdf",
        source_pdf,
        project_data_root=project_data_root,
    )

    assert blocks is not None
    fig_3_body = next(block for block in blocks if block.markdown.startswith("Fig. 3 presents"))
    fig_3_caption = next(block for block in blocks if block.markdown.startswith("Fig. 3. Weld morphology"))
    assert fig_3_body.block_type == "Text"
    assert fig_3_body.image_paths == []
    assert fig_3_caption.block_type == "FigureCaption"
    assert len(fig_3_caption.image_paths) == 1
    assert fig_3_caption.image_paths[0].endswith("/p0001_img002.jpeg")
    assert (project_data_root / fig_3_caption.image_paths[0]).is_file()


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
