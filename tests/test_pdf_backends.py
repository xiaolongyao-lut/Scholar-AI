# -*- coding: utf-8 -*-
"""Tests for literature_assistant/core/pdf_backends/.

Locks the byte-level identity contract for PyMuPDFBackend, which must mirror
the legacy _document_extraction PDF branch.

Placeholder strings are byte-level locked here — any change is a
contract break and should fail this test.
"""

from __future__ import annotations

import io
import hashlib
import sys
import types
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Ensure the core path is importable for direct module access.
_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

import routers.resources_router as resources_router  # noqa: E402
from routers.resources_router import _document_extraction as document_extraction  # noqa: E402
from pdf_backends import (  # noqa: E402
    ENV_VAR,
    PDFParserProvenance,
    StructuredBlock,
    get_pdf_backend,
    parse_pdf_with_provenance,
)
from pdf_backends.pymupdf_backend import PyMuPDFBackend  # noqa: E402
from python_adapter_server import app  # noqa: E402


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


def test_pymupdf_typed_result_records_actual_module_version_and_keeps_legacy_tuple(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Typed provenance must not alter the legacy parser return values."""

    class _TextPage:
        def get_text(self) -> str:
            return "typed-pymupdf-text"

    class _TextDocument:
        def __iter__(self):
            return iter([_TextPage()])

        def close(self) -> None:
            return None

    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.__version__ = "9.8.7-test"
    fake_pymupdf.open = lambda _path: _TextDocument()
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)

    pdf = tmp_path / "typed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    backend = PyMuPDFBackend()

    typed = backend.parse_with_provenance(pdf)

    assert typed.legacy_tuple() == ("typed-pymupdf-text", None, None)
    assert backend.parse(pdf) == typed.legacy_tuple()
    assert typed.provenance == PDFParserProvenance(
        backend_name="pymupdf",
        parser_name="pymupdf",
        parser_version="9.8.7-test",
        parser_version_source="module",
        backend_contract="scholar-ai.pdf-parser.pymupdf-fallback-compat/v1",
        backend_fingerprint=typed.provenance.backend_fingerprint,
        outcome="succeeded",
        attempted_parsers=("pymupdf",),
    )
    assert typed.provenance.backend_fingerprint.startswith("sha256:")
    assert len(typed.provenance.backend_fingerprint) == 71
    assert PDFParserProvenance.from_mapping(typed.provenance.to_dict()) == typed.provenance

    monkeypatch.setattr(document_extraction, "apply_pdf_ocr_if_needed", None)
    payload = document_extraction._extract_document_payload_from_path("typed.pdf", pdf)
    assert payload.content == typed.text
    assert payload.parser_provenance is not None
    assert payload.parser_provenance.parser_name == "pymupdf"
    assert payload.parser_provenance.parser_version == "9.8.7-test"
    assert payload.parser_output_sha256 == (
        "sha256:" + hashlib.sha256(typed.text.encode("utf-8")).hexdigest()
    )


def test_pymupdf_typed_batch_preserves_provenance_and_legacy_batch_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _TextPage:
        def get_text(self) -> str:
            return "typed-batch-text"

    class _TextDocument:
        def __iter__(self):
            return iter([_TextPage()])

        def close(self) -> None:
            return None

    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.__version__ = "9.8.7-batch"
    fake_pymupdf.open = lambda _path: _TextDocument()
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)
    paths = [tmp_path / "one.pdf", tmp_path / "two.pdf"]
    for path in paths:
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    backend = PyMuPDFBackend()
    typed = backend.parse_batch_with_provenance(paths, max_workers=2)
    legacy = backend.parse_batch(paths, max_workers=2)

    assert all(not isinstance(item, Exception) for item in typed)
    assert [item.provenance.parser_version for item in typed if not isinstance(item, Exception)] == [
        "9.8.7-batch",
        "9.8.7-batch",
    ]
    assert legacy == [("typed-batch-text", None, None)] * 2


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

    typed = backend.parse_with_provenance(pdf)
    assert typed.legacy_tuple() == (expected, None, None)
    assert typed.provenance.parser_name == "unavailable"
    assert typed.provenance.parser_version == "unavailable"
    assert typed.provenance.parser_version_source == "unavailable"
    assert typed.provenance.outcome == "unavailable"
    assert typed.provenance.attempted_parsers == ("pymupdf", "pypdf2")


def test_pymupdf_backend_returns_parse_failure_placeholder_on_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parse exception → ``[PDF 解析失败: {exc}]`` placeholder (byte-locked)."""
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.__version__ = "9.8.7-failure"

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

    typed = backend.parse_with_provenance(pdf)
    assert typed.legacy_tuple() == (expected, None, None)
    assert typed.provenance.parser_name == "pymupdf"
    assert typed.provenance.parser_version == "9.8.7-failure"
    assert typed.provenance.outcome == "failed"
    assert typed.provenance.attempted_parsers == ("pymupdf",)


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
    fake_pypdf2.__version__ = "3.0.1-test"
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

    typed = backend.parse_with_provenance(pdf)
    assert typed.legacy_tuple() == (text, blocks, md)
    assert typed.provenance.parser_name == "pypdf2"
    assert typed.provenance.parser_version == "3.0.1-test"
    assert typed.provenance.parser_version_source == "module"
    assert typed.provenance.outcome == "succeeded"
    assert typed.provenance.attempted_parsers == ("pymupdf", "pypdf2")


def test_legacy_third_party_backend_provenance_is_explicitly_unknown(tmp_path: Path) -> None:
    """Legacy three-tuple backends must not receive guessed version data."""

    class _LegacyBackend:
        name = "third-party"
        supports_blocks = False

        def parse(self, _source_path: Path) -> tuple[str, None, None]:
            return "legacy text", None, None

    pdf = tmp_path / "legacy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = parse_pdf_with_provenance(_LegacyBackend(), pdf)

    assert result.legacy_tuple() == ("legacy text", None, None)
    assert result.provenance.backend_name == "third-party"
    assert result.provenance.parser_name == "third-party"
    assert result.provenance.parser_version == "unknown"
    assert result.provenance.parser_version_source == "unknown"
    assert result.provenance.backend_fingerprint == "unavailable"
    assert result.provenance.outcome == "unknown"


def test_document_payload_records_actual_pymupdf_fallback_after_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Extraction fallback provenance must name both failed and adopted paths."""

    class _FailingThirdPartyBackend:
        name = "third-party"
        supports_blocks = False

        def parse(self, _source_path: Path) -> tuple[str, None, None]:
            raise RuntimeError("synthetic third-party failure")

    class _TextPage:
        def get_text(self) -> str:
            return "fallback parser text"

    class _TextDocument:
        def __iter__(self):
            return iter([_TextPage()])

        def close(self) -> None:
            return None

    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.__version__ = "9.8.7-fallback"
    fake_pymupdf.open = lambda _path: _TextDocument()
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)
    monkeypatch.setattr(
        document_extraction,
        "get_pdf_backend",
        lambda: _FailingThirdPartyBackend(),
    )
    monkeypatch.setattr(document_extraction, "apply_pdf_ocr_if_needed", None)

    pdf = tmp_path / "fallback-payload.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    payload = document_extraction._extract_document_payload_from_path(
        "fallback-payload.pdf",
        pdf,
    )

    assert payload.content == "fallback parser text"
    assert payload.parser_provenance is not None
    assert payload.parser_provenance.parser_name == "pymupdf"
    assert payload.parser_provenance.parser_version == "9.8.7-fallback"
    assert payload.parser_provenance.outcome == "succeeded"
    assert payload.parser_provenance.attempted_parsers == ("third-party", "pymupdf")


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

    def __init__(
        self,
        blocks: list[dict[str, Any]],
        drawings: list[dict[str, Any]] | None = None,
    ) -> None:
        self._blocks = blocks
        self._drawings = drawings or []
        self.pixmap_requests: list[dict[str, Any]] = []

    def get_text(self, _mode: str, *, sort: bool = False) -> dict[str, Any]:
        return {"blocks": list(self._blocks)}

    def get_drawings(self) -> list[dict[str, Any]]:
        return list(self._drawings)

    def get_pixmap(self, **kwargs: Any) -> "_FakePixmap":
        self.pixmap_requests.append(dict(kwargs))
        return _FakePixmap()


class _FakeDocument:
    """Context-manager document test double returned by pymupdf.open."""

    def __init__(self, page: _FakePage | _FakePageWithBlocks) -> None:
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


class _FakeClipRect:
    """Minimal PyMuPDF Rect replacement used by caption-crop tests."""

    def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1

    def get_area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


class _FakeMatrix:
    """Minimal PyMuPDF Matrix replacement."""

    def __init__(self, x_scale: float, y_scale: float) -> None:
        self.x_scale = x_scale
        self.y_scale = y_scale


class _FakePixmap:
    """Minimal pixmap that materializes a valid browser-safe PNG."""

    def save(self, output_path: str) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (120, 80), (190, 190, 190)).save(output_path, format="PNG")


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
    assert all(block.bbox_unit == "normalized_ratio" for block in blocks if block.bbox is not None)
    assert image_paths[0].endswith(".png")
    output_path = project_data_root / image_paths[0]
    assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(output_path) as image:
        assert image.format == "PNG"


def test_pymupdf_uncaptioned_image_is_not_primary_visual_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Embedded images without a caption link must not become figure evidence."""

    fake_pymupdf = types.ModuleType("pymupdf")
    page = _FakePageWithBlocks(
        [
            _fake_image_block([40.0, 40.0, 300.0, 220.0], _image_bytes("JPEG")),
            _fake_text_block([40.0, 250.0, 500.0, 285.0], "The process parameters are summarized here."),
        ]
    )
    fake_pymupdf.open = lambda _path: _FakeDocument(page)
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
    assert [block.block_type for block in blocks] == ["Text"]
    assert [path for block in blocks for path in block.image_paths] == []
    assert not (project_data_root / "figure_assets").exists()


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
    assert fig_3_body.linked_figure_ids == [fig_3_caption.figure_id]
    assert fig_3_caption.block_type == "FigureCaption"
    assert fig_3_caption.figure_id is not None
    assert len(fig_3_caption.image_paths) == 1
    assert fig_3_caption.image_paths[0].endswith("/p0001_img002.jpeg")
    assert (project_data_root / fig_3_caption.image_paths[0]).is_file()


def test_pymupdf_visual_asset_does_not_treat_chinese_body_refs_as_captions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Chinese narrative figure/table refs are links, not primary visual evidence."""

    image_bytes = _image_bytes("JPEG")
    blocks_fixture = [
        _fake_image_block([80.0, 80.0, 520.0, 260.0], image_bytes),
        _fake_text_block([90.0, 275.0, 520.0, 305.0], "图3所示的焊缝表面形貌随功率发生变化。"),
        _fake_image_block([90.0, 430.0, 520.0, 610.0], image_bytes),
        _fake_text_block([120.0, 625.0, 500.0, 655.0], "图3. 焊缝表面形貌。"),
        _fake_text_block([70.0, 690.0, 530.0, 725.0], "表2中列出了不同样品的显微硬度。"),
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
    figure_body = next(block for block in blocks if block.markdown.startswith("图3所示"))
    figure_caption = next(block for block in blocks if block.markdown.startswith("图3."))
    table_body = next(block for block in blocks if block.markdown.startswith("表2中"))

    assert figure_body.block_type == "Text"
    assert figure_body.image_paths == []
    assert figure_body.figure_id is None
    assert figure_body.linked_figure_ids == [figure_caption.figure_id]
    assert figure_caption.block_type == "FigureCaption"
    assert figure_caption.figure_id is not None
    assert len(figure_caption.image_paths) == 1

    assert table_body.block_type == "Text"
    assert table_body.image_paths == []
    assert table_body.table_id is None
    assert len(table_body.linked_table_ids) == 1


def test_pymupdf_caption_without_image_block_renders_local_neighbor_crop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Caption-only vector figures produce a local crop, not a page screenshot."""

    page = _FakePageWithBlocks(
        [
            _fake_text_block([60.0, 80.0, 540.0, 130.0], "The experiment setup is described above."),
            _fake_text_block([120.0, 400.0, 480.0, 425.0], "Fig. 4. Melt pool morphology."),
            _fake_text_block([60.0, 500.0, 540.0, 560.0], "Fig. 4 shows the morphology change."),
        ],
        # Real vector figure ink above the caption; the crop must anchor to it.
        drawings=[{"rect": (150.0, 200.0, 450.0, 395.0)}],
    )
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.Rect = _FakeClipRect
    fake_pymupdf.Matrix = _FakeMatrix
    fake_pymupdf.open = lambda _path: _FakeDocument(page)
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
    caption = next(block for block in blocks if block.markdown.startswith("Fig. 4."))
    body = next(block for block in blocks if block.markdown.startswith("Fig. 4 shows"))
    assert caption.block_type == "FigureCaption"
    assert caption.figure_id is not None
    assert len(caption.image_paths) == 1
    assert caption.image_paths[0].endswith("/p0001_cap001.png")
    assert caption.bbox is not None
    assert caption.bbox[2] < 0.92
    assert caption.bbox[3] < 0.88
    assert body.block_type == "Text"
    assert body.image_paths == []
    assert body.linked_figure_ids == [caption.figure_id]
    assert len(page.pixmap_requests) == 1
    assert (project_data_root / caption.image_paths[0]).is_file()


def test_pymupdf_caption_with_no_visual_ink_is_not_cropped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caption whose page has no figure ink must not crop prose as a figure.

    Covers the cross-page / floating-caption case: the figure body lives on
    another page, so the caption page holds only text. The crop fallback must
    be gated off and the caption kept as a text-linked ref, never a false tile.
    """

    page = _FakePageWithBlocks(
        [
            _fake_text_block([60.0, 80.0, 540.0, 120.0], "Preceding discussion paragraph on this page."),
            _fake_text_block([120.0, 300.0, 480.0, 325.0], "Fig. 8. Cross-page morphology overview."),
            _fake_text_block([60.0, 400.0, 540.0, 470.0], "Ordinary prose continues after the caption."),
        ],
        drawings=[],  # No figure ink anywhere on this page.
    )
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.Rect = _FakeClipRect
    fake_pymupdf.Matrix = _FakeMatrix
    fake_pymupdf.open = lambda _path: _FakeDocument(page)
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
    caption = next(block for block in blocks if block.markdown.startswith("Fig. 8."))
    # Caption identity is preserved for retrieval, but no false pixels rendered.
    assert caption.block_type == "FigureCaption"
    assert caption.figure_id is not None
    assert caption.image_paths == []
    # Nothing was rendered to disk for this page.
    assert page.pixmap_requests == []


def test_pymupdf_borderless_table_uses_consecutive_text_geometry_for_native_crop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cui-style borderless tables must include every column without the next figure."""

    page = _FakePageWithBlocks(
        [
            _fake_text_block(
                [37.8858, 52.9528, 266.8566, 74.4304],
                "Table 1\nNominal chemical compositions of the BM of AlSi10Mg alloys (wt,%).",
            ),
            _fake_text_block(
                [43.9428, 76.8280, 553.3164, 87.3352],
                "Element\nCu\nFe\nMg\nMn\nNi\nSi\nZn\nTi\nPb\nSn\nAl",
            ),
            _fake_text_block(
                [43.9428, 90.0848, 559.8264, 109.2208],
                "SLM\n0.05\n0.55\n0.20-0.45\n0.45\n0.05\n9.0-11.0\n0.10\n0.15\n0.05\n0.05\nBal.\n"
                "Casting\n0.03\n0.12\n0.417\n0.051\n0.006\n9.375\n<0.002\n0.164\n<0.005\n<0.002\nBal.",
            ),
            _fake_image_block([100.0, 134.0, 500.0, 605.0], _image_bytes("PNG"), "png"),
            _fake_text_block(
                [100.0, 615.0, 500.0, 640.0],
                "Fig. 1. Macrostructure of SLM AlSi10Mg alloys.",
            ),
        ],
        drawings=[],
    )
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.Rect = _FakeClipRect
    fake_pymupdf.Matrix = _FakeMatrix
    fake_pymupdf.open = lambda _path: _FakeDocument(page)
    monkeypatch.setitem(sys.modules, "pymupdf", fake_pymupdf)

    source_pdf = tmp_path / "cui-2022.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    project_data_root = tmp_path / "project"

    blocks = document_extraction._extract_pymupdf_visual_blocks(
        "cui-2022.pdf",
        source_pdf,
        project_data_root=project_data_root,
    )

    assert blocks is not None
    table = next(block for block in blocks if block.markdown.startswith("Table 1"))
    assert table.block_type == "TableCaption"
    assert table.table_id is not None
    assert len(table.image_paths) == 1
    assert table.image_paths[0].endswith("/p0001_cap001.png")
    assert table.bbox is not None
    assert table.bbox[0] <= 43.9428 / 600.0
    assert table.bbox[0] + table.bbox[2] >= 559.8264 / 600.0
    assert table.bbox[1] <= 52.9528 / 800.0
    assert table.bbox[1] + table.bbox[3] < 0.17
    assert len(page.pixmap_requests) == 1
    clip = page.pixmap_requests[0]["clip"]
    assert clip.x1 >= 559.8264
    assert clip.y1 < 136.0
    asset_path = project_data_root / table.image_paths[0]
    assert asset_path.is_file()

    asset_path.write_bytes(b"stale-truncated-crop")
    page.pixmap_requests.clear()
    refreshed = document_extraction._extract_pymupdf_visual_blocks(
        "cui-2022.pdf",
        source_pdf,
        project_data_root=project_data_root,
    )
    assert refreshed is not None
    assert asset_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(page.pixmap_requests) == 1


def test_pymupdf_whole_page_image_block_is_not_primary_figure_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Near-page-sized image blocks are page captures and must be rejected."""

    image_bytes = _image_bytes("JPEG")
    page = _FakePageWithBlocks(
        [
            _fake_image_block([0.0, 0.0, 600.0, 760.0], image_bytes),
            _fake_text_block([110.0, 610.0, 500.0, 635.0], "Fig. 7. Full-page scan caption."),
        ]
    )
    fake_pymupdf = types.ModuleType("pymupdf")
    fake_pymupdf.Rect = _FakeClipRect
    fake_pymupdf.Matrix = _FakeMatrix
    fake_pymupdf.open = lambda _path: _FakeDocument(page)
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
    assert all(not path.endswith("_img001.jpeg") for block in blocks for path in block.image_paths)
    caption = next(block for block in blocks if block.markdown.startswith("Fig. 7."))
    assert caption.block_type == "FigureCaption"
    assert len(caption.image_paths) == 1
    assert caption.image_paths[0].endswith("/p0001_cap001.png")
    assert caption.bbox is not None
    assert caption.bbox[2] < 0.92
    assert caption.bbox[3] < 0.88


@pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="PyMuPDF is required for real PDF import")
def test_real_pdf_persisted_chunks_public_refs_return_caption_pixels(tmp_path: Path) -> None:
    """Persisted real-PDF chunks should expose caption pixels through public refs."""

    import pymupdf

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "Real PDF visual refs"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]

    pdf_path = tmp_path / "alsi10mg-surface.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        pymupdf.Rect(72, 58, 520, 98),
        "图3所示，AlSi10Mg 焊缝上表面形貌随激光功率变化，并出现局部塌陷趋势。",
        fontsize=11,
        fontname="china-s",
    )
    page.insert_image(
        pymupdf.Rect(86, 150, 450, 355),
        stream=_image_bytes("PNG"),
    )
    page.insert_textbox(
        pymupdf.Rect(86, 368, 520, 408),
        "图3. AlSi10Mg 焊缝上表面形貌与外观。",
        fontsize=11,
        fontname="china-s",
    )
    doc.save(str(pdf_path))
    doc.close()

    payload = document_extraction._extract_document_payload_from_path(
        "alsi10mg-surface.pdf",
        pdf_path,
        project_id=project_id,
    )
    assert payload.blocks is not None
    result = resources_router._persist_uploaded_document(  # type: ignore[attr-defined]
        project_id,
        "alsi10mg-surface.pdf",
        payload.content,
        store=resources_router.get_writing_resource_store(),  # type: ignore[attr-defined]
        blocks=payload.blocks,
        markdown_full=payload.markdown_full,
    )
    assert result["chunks"] >= 2

    chunk_store = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    chunks = next(iter(chunk_store.values()))
    body_chunk = next(chunk for chunk in chunks if str(chunk.get("raw_content") or "").startswith("图3所示"))
    caption_chunk = next(chunk for chunk in chunks if str(chunk.get("raw_content") or "").startswith("图3."))
    caption_assets = caption_chunk.get("image_paths") or []
    assert body_chunk.get("image_paths") is None
    assert body_chunk.get("linked_figure_ids") == [caption_chunk.get("figure_id")]
    assert caption_assets
    assert (resources_router.project_data_path(project_id) / caption_assets[0]).is_file()  # type: ignore[attr-defined]

    search_response = client.get(
        "/resources/chunks/search-refs",
        params={
            "project_id": project_id,
            "query": "AlSi10Mg 上表面 焊缝 外观 形貌 图片",
            "top_k": 10,
        },
    )
    assert search_response.status_code == 200
    search_refs = {ref["chunk_id"]: ref for ref in search_response.json()["refs"]}
    search_ref = search_refs[body_chunk["chunk_id"]]
    assert search_ref["metadata"]["image_paths"] == caption_assets
    assert search_ref["metadata"]["figure_candidate"] == caption_chunk["figure_id"]
    assert search_ref["metadata"]["figure_candidate_detail"]["source"] == "linked_caption_chunk"

    pack_response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 上表面 焊缝 外观 形貌 图片",
            "top_k": 10,
        },
    )
    assert pack_response.status_code == 200
    pack_refs = {ref["chunk_id"]: ref for ref in pack_response.json()["evidence_refs"]}
    pack_ref = pack_refs[body_chunk["chunk_id"]]
    assert pack_ref["image_paths"] == caption_assets
    assert pack_ref["figure_candidate"] == caption_chunk["figure_id"]
    assert pack_ref["figure_candidate_detail"]["source"] == "linked_caption_chunk"

    persisted = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    persisted_body = next(
        chunk
        for chunk in next(iter(persisted.values()))
        if chunk["chunk_id"] == body_chunk["chunk_id"]
    )
    assert persisted_body.get("image_paths") is None
    assert persisted_body.get("linked_figure_ids") == [caption_chunk.get("figure_id")]


@pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="PyMuPDF is required for real PDF import")
def test_real_pdf_persisted_table_public_refs_return_caption_pixels(tmp_path: Path) -> None:
    """Persisted real-PDF table refs should expose table-caption crop assets."""

    import pymupdf

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "Real PDF table refs"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]

    pdf_path = tmp_path / "alsi10mg-table.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        pymupdf.Rect(72, 58, 520, 98),
        "表2中列出了AlSi10Mg焊缝孔隙率和成形质量随激光功率的变化。",
        fontsize=11,
        fontname="china-s",
    )
    page.insert_textbox(
        pymupdf.Rect(86, 132, 520, 162),
        "表2. AlSi10Mg焊缝孔隙率与成形质量。",
        fontsize=11,
        fontname="china-s",
    )
    left, top, width, row_height = 86, 180, 360, 28
    for index in range(4):
        y = top + index * row_height
        page.draw_line(
            pymupdf.Point(left, y),
            pymupdf.Point(left + width, y),
            color=(0, 0, 0),
            width=0.8,
        )
    for x in (left, left + 120, left + 240, left + width):
        page.draw_line(
            pymupdf.Point(x, top),
            pymupdf.Point(x, top + 3 * row_height),
            color=(0, 0, 0),
            width=0.8,
        )
    rows = [
        ("功率/W", "孔隙率/%", "成形"),
        ("250", "1.8", "连续"),
        ("300", "0.7", "稳定"),
    ]
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            page.insert_textbox(
                pymupdf.Rect(
                    left + column_index * 120 + 8,
                    top + row_index * row_height + 7,
                    left + (column_index + 1) * 120 - 6,
                    top + (row_index + 1) * row_height - 4,
                ),
                text,
                fontsize=9,
                fontname="china-s",
            )
    doc.save(str(pdf_path))
    doc.close()

    payload = document_extraction._extract_document_payload_from_path(
        "alsi10mg-table.pdf",
        pdf_path,
        project_id=project_id,
    )
    assert payload.blocks is not None
    result = resources_router._persist_uploaded_document(  # type: ignore[attr-defined]
        project_id,
        "alsi10mg-table.pdf",
        payload.content,
        store=resources_router.get_writing_resource_store(),  # type: ignore[attr-defined]
        blocks=payload.blocks,
        markdown_full=payload.markdown_full,
    )
    assert result["chunks"] >= 2

    chunk_store = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    chunks = next(iter(chunk_store.values()))
    body_chunk = next(chunk for chunk in chunks if str(chunk.get("raw_content") or "").startswith("表2中"))
    caption_chunk = next(chunk for chunk in chunks if str(chunk.get("raw_content") or "").startswith("表2."))
    caption_assets = caption_chunk.get("image_paths") or []
    assert body_chunk.get("image_paths") is None
    assert body_chunk.get("linked_table_ids") == [caption_chunk.get("table_id")]
    assert caption_chunk.get("figure_id") is None
    assert caption_chunk.get("table_id")
    assert caption_assets
    assert caption_assets[0].endswith(".png")
    assert (resources_router.project_data_path(project_id) / caption_assets[0]).is_file()  # type: ignore[attr-defined]

    search_response = client.get(
        "/resources/chunks/search-refs",
        params={
            "project_id": project_id,
            "query": "AlSi10Mg 表2 焊缝 孔隙率 成形质量",
            "top_k": 10,
        },
    )
    assert search_response.status_code == 200
    search_refs = {ref["chunk_id"]: ref for ref in search_response.json()["refs"]}
    search_ref = search_refs[body_chunk["chunk_id"]]
    assert search_ref["metadata"]["image_paths"] == caption_assets
    assert search_ref["metadata"]["figure_candidate"] == caption_chunk["table_id"]
    assert search_ref["metadata"]["figure_candidate_detail"]["source"] == "linked_caption_chunk"
    assert "visual_linked_caption_asset" in search_ref["metadata"]["source_labels"]

    pack_response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 表2 焊缝 孔隙率 成形质量",
            "top_k": 10,
        },
    )
    assert pack_response.status_code == 200
    pack_refs = {ref["chunk_id"]: ref for ref in pack_response.json()["evidence_refs"]}
    pack_ref = pack_refs[body_chunk["chunk_id"]]
    assert pack_ref["image_paths"] == caption_assets
    assert pack_ref["figure_candidate"] == caption_chunk["table_id"]
    assert pack_ref["figure_candidate_detail"]["source"] == "linked_caption_chunk"

    persisted = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    persisted_body = next(
        chunk
        for chunk in next(iter(persisted.values()))
        if chunk["chunk_id"] == body_chunk["chunk_id"]
    )
    assert persisted_body.get("image_paths") is None
    assert persisted_body.get("linked_table_ids") == [caption_chunk.get("table_id")]


@pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="PyMuPDF is required for real PDF import")
def test_real_pdf_vector_figure_crop_includes_drawings_and_caption(tmp_path: Path) -> None:
    """Vector-drawn figures (no embedded raster) yield a caption-bound crop.

    Guards the blank-crop regression: figures drawn as vector paths have no
    image block and no table grid, so the crop must be framed from the drawings
    union above the caption and must include the caption band itself.
    """

    import pymupdf

    pdf_path = tmp_path / "vector-figure.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # Body reference above the figure (must not own pixels).
    page.insert_textbox(
        pymupdf.Rect(72, 60, 520, 96),
        "As shown in Figure 3, the attention weights spread across many heads.",
        fontsize=11,
    )
    # Vector figure region (diagonals + circles, no embedded raster, no grid).
    for index in range(12):
        x = 120 + index * 30
        page.draw_line(pymupdf.Point(120, 160), pymupdf.Point(x, 300), color=(0.3, 0.2, 0.6), width=1.1)
        page.draw_circle(pymupdf.Point(x, 300), 6, color=(0.2, 0.2, 0.2), fill=(0.6, 0.5, 0.8))
    # Caption below the figure.
    page.insert_textbox(
        pymupdf.Rect(72, 330, 520, 372),
        "Figure 3: Attention weight distribution across heads.",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    project_data_root = tmp_path / "project"
    blocks = document_extraction._extract_pymupdf_visual_blocks(
        "vector-figure.pdf",
        pdf_path,
        project_data_root=project_data_root,
    )

    assert blocks is not None
    caption = next(block for block in blocks if block.markdown.startswith("Figure 3:"))
    body = next(block for block in blocks if block.markdown.startswith("As shown in Figure 3"))
    assert caption.block_type == "FigureCaption"
    assert caption.figure_id is not None
    assert len(caption.image_paths) == 1
    assert caption.image_paths[0].endswith(".png")
    crop_path = project_data_root / caption.image_paths[0]
    assert crop_path.is_file()
    # Non-blank: a framed vector region renders far larger than an empty band.
    assert crop_path.stat().st_size > 4000

    # Crop must reach up into the drawing region and down through the caption.
    caption_text_top_norm = 330 / 842
    assert caption.bbox is not None
    # Top edge sits in the vector-figure region, well above the caption text.
    assert caption.bbox[1] < caption_text_top_norm - 0.05
    # Bottom edge reaches the caption text band (framing figure + label together).
    assert caption.bbox[1] + caption.bbox[3] >= caption_text_top_norm
    assert caption.bbox[2] < 0.92
    assert caption.bbox[3] < 0.88

    # Body reference links to the figure without owning pixels.
    assert body.image_paths == []
    assert body.linked_figure_ids == [caption.figure_id]


@pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="PyMuPDF is required for real PDF import")
def test_real_pdf_cross_page_caption_yields_no_false_crop(tmp_path: Path) -> None:
    """A caption on a page whose figure body is on another page renders no crop.

    Guards the silent cross-page mis-crop: the figure ink is on page 1, only the
    caption and prose land on page 2, so the caption page must not fabricate an
    evidence tile from its own body text. The caption stays a retrievable ref.
    """

    import pymupdf

    pdf_path = tmp_path / "cross-page.pdf"
    doc = pymupdf.open()
    # Page 1: the real vector figure, with no caption (caption overflowed).
    page1 = doc.new_page(width=595, height=842)
    for index in range(12):
        x = 120 + index * 30
        page1.draw_line(pymupdf.Point(120, 160), pymupdf.Point(x, 300), color=(0.3, 0.2, 0.6), width=1.1)
        page1.draw_circle(pymupdf.Point(x, 300), 6, color=(0.2, 0.2, 0.2), fill=(0.6, 0.5, 0.8))
    page1.insert_textbox(pymupdf.Rect(72, 700, 520, 760), "Trailing body text on page one.", fontsize=11)
    # Page 2: only the caption and ordinary prose; the figure is on page 1.
    page2 = doc.new_page(width=595, height=842)
    page2.insert_textbox(
        pymupdf.Rect(72, 60, 520, 100),
        "Figure 9: Cross-page attention diagram continued from the prior page.",
        fontsize=11,
    )
    page2.insert_textbox(
        pymupdf.Rect(72, 140, 520, 220),
        "Ordinary prose discussion continues here on page two without any figure.",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()

    project_data_root = tmp_path / "project"
    blocks = document_extraction._extract_pymupdf_visual_blocks(
        "cross-page.pdf",
        pdf_path,
        project_data_root=project_data_root,
    )

    assert blocks is not None
    caption = next(block for block in blocks if block.markdown.startswith("Figure 9:"))
    assert caption.block_type == "FigureCaption"
    assert caption.figure_id is not None
    # The cross-page caption owns no pixels: no false text-as-figure crop.
    assert caption.image_paths == []
    # And no stray crop asset was written for the caption page.
    extracted_root = project_data_root / "figure_assets" / "extracted"
    crop_pngs = list(extracted_root.rglob("*_cap*.png")) if extracted_root.exists() else []
    assert crop_pngs == []


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
    assert block.bbox_unit is None
    assert block.block_type == "Text"
    assert block.markdown == "hello"
    # Optional defaults
    assert block.html is None
    assert block.image_paths == []
    assert block.figure_id is None
    assert block.table_id is None
    assert block.linked_figure_ids == []
    assert block.linked_table_ids == []
    assert block.table_csv is None
    assert block.equation_latex is None
    assert block.section_heading is None
    # Frozen
    with pytest.raises(Exception):  # FrozenInstanceError
        block.markdown = "mutated"  # type: ignore[misc]
