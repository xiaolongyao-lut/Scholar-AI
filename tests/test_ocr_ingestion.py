# -*- coding: utf-8 -*-
"""Tests for OCR auto-policy wiring in PDF ingestion."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import (  # noqa: E402
    OcrEngineHealth,
    build_ocr_engine,
    clear_ocr_engines_for_tests,
    register_ocr_engine,
)
from pdf_backends.ocr_classifier import PDFClassificationResult  # noqa: E402
from pdf_backends.ocr_ingestion import apply_pdf_ocr_if_needed  # noqa: E402
from routers.resources_router._document_extraction import ExtractedDocumentPayload  # noqa: E402
from services import unified_batch_upload_service as upload_service_module  # noqa: E402
from services.unified_batch_upload_service import (  # noqa: E402
    BatchSource,
    UnifiedBatchUploadService,
)


class _StaticClassifier:
    """Classifier stub that returns a precomputed page strategy."""

    def __init__(self, result: PDFClassificationResult) -> None:
        self.result = result
        self.calls = 0

    def classify_pdf(self, pdf_path: Path) -> PDFClassificationResult:
        if not isinstance(pdf_path, Path):
            raise TypeError("pdf_path must be a pathlib.Path")
        self.calls += 1
        return self.result


class _RecordingOcrEngine:
    """OCR engine stub that records image/language calls."""

    name = "mock"
    display_name = "Mock OCR"
    engine_type = "local"
    requires_network = False
    calls: list[tuple[bytes | Path, str]] = []

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        self.calls.append((image, language))
        if isinstance(image, bytes):
            return f"mock text {language} {image.decode('ascii')}"
        return f"mock text {language} {image.name}"

    def health_check(self) -> OcrEngineHealth:
        return OcrEngineHealth(ok=True, detail="mock", engine=self.name)


class _FailingOcrEngine(_RecordingOcrEngine):
    """OCR engine stub that is available but fails at page execution time."""

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        if not isinstance(image, (bytes, Path)):
            raise TypeError("image must be bytes or pathlib.Path")
        self.calls.append((image, language))
        raise RuntimeError("mock runtime adapter is not wired")


@pytest.fixture(autouse=True)
def _reset_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_ocr_engines_for_tests()
    _RecordingOcrEngine.calls = []
    for name in (
        "LITASSIST_OCR_POLICY",
        "LITASSIST_OCR_ENGINE",
        "LITASSIST_OCR_LANG",
        "LITASSIST_OCR_CONFIG_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    clear_ocr_engines_for_tests()


def _classification(
    *,
    text_pages: list[int] | None = None,
    ocr_pages: list[int] | None = None,
    mixed_pages: list[int] | None = None,
    strategy: str = "text_only",
) -> PDFClassificationResult:
    return PDFClassificationResult(
        text_pages=text_pages or [],
        ocr_pages=ocr_pages or [],
        mixed_pages=mixed_pages or [],
        strategy=strategy,
        total_pages=len(text_pages or []) + len(ocr_pages or []) + len(mixed_pages or []),
        avg_text_density=120.0,
    )


def _write_ocr_classifier_fixture_pdf(path: Path) -> None:
    """Create text-only, scanned, and mixed pages for classifier integration tests."""

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")

    pymupdf = pytest.importorskip("pymupdf")
    image_module = pytest.importorskip("PIL.Image")
    image_draw_module = pytest.importorskip("PIL.ImageDraw")

    scan_image = image_module.new("RGB", (600, 500), "white")
    draw = image_draw_module.Draw(scan_image)
    draw.rectangle((28, 28, 572, 472), outline="black", width=6)
    draw.text((80, 220), "SCAN PAGE", fill="black")
    image_buffer = io.BytesIO()
    scan_image.save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()

    doc = pymupdf.open()
    try:
        dense_page = doc.new_page(width=600, height=800)
        dense_page.insert_textbox(
            pymupdf.Rect(40, 40, 560, 740),
            "Dense selectable text page for OCR bypass. " * 8,
            fontsize=12,
        )

        scanned_page = doc.new_page(width=600, height=800)
        scanned_page.insert_image(pymupdf.Rect(20, 20, 580, 780), stream=image_bytes)

        mixed_page = doc.new_page(width=600, height=800)
        mixed_page.insert_textbox(
            pymupdf.Rect(40, 30, 560, 140),
            "Mixed page short selectable text with a dominant scanned figure.",
            fontsize=12,
        )
        mixed_page.insert_image(pymupdf.Rect(20, 180, 580, 780), stream=image_bytes)

        doc.save(str(path))
    finally:
        doc.close()


def _load_ocr_fixture_font(image_font_module: Any, *, size: int) -> Any:
    """Return a large local font so OCR fixtures survive PDF rasterization."""

    if isinstance(size, bool) or size < 12:
        raise ValueError("size must be an integer >= 12")

    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                return image_font_module.truetype(str(candidate), size=size)
            except OSError:
                continue
    try:
        return image_font_module.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return image_font_module.load_default()


def _write_windows_ocr_ingestion_fixture_pdf(path: Path) -> None:
    """Create one scanned PDF page with large English text for Windows OCR."""

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")

    pymupdf = pytest.importorskip("pymupdf")
    image_module = pytest.importorskip("PIL.Image")
    image_draw_module = pytest.importorskip("PIL.ImageDraw")
    image_font_module = pytest.importorskip("PIL.ImageFont")

    image = image_module.new("RGB", (1400, 900), "white")
    draw = image_draw_module.Draw(image)
    draw.rectangle((24, 24, 1376, 876), outline="black", width=8)
    font = _load_ocr_fixture_font(image_font_module, size=92)
    lines = ("SCHOLAR OCR INGESTION", "LOCAL WINDOWS PROOF")
    y = 260
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]
        draw.text(((1400 - width) / 2, y), line, fill="black", font=font)
        y += 150

    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=700, height=450)
        page.insert_image(pymupdf.Rect(0, 0, 700, 450), stream=image_buffer.getvalue())
        doc.save(str(path))
    finally:
        doc.close()


def test_text_pdf_makes_zero_ocr_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "text.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    register_ocr_engine("mock", lambda config: _RecordingOcrEngine(config))
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "engine")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "mock")

    payload = ExtractedDocumentPayload(content="already extracted text")
    result = apply_pdf_ocr_if_needed(
        "text.pdf",
        pdf_path,
        payload,
        classifier=_StaticClassifier(_classification(text_pages=[0], strategy="text_only")),
        render_page=lambda _path, _page: pytest.fail("text-only PDFs must not render pages"),
    )

    assert result.content == "already extracted text"
    assert _RecordingOcrEngine.calls == []
    assert result.ocr_report is not None
    assert result.ocr_report.strategy == "text_only"


def test_scanned_pdf_without_available_engine_degrades_visibly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "engine")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "remote_api")

    result = apply_pdf_ocr_if_needed(
        "scan.pdf",
        pdf_path,
        ExtractedDocumentPayload(content=""),
        classifier=_StaticClassifier(_classification(ocr_pages=[0], strategy="ocr_only")),
        render_page=lambda _path, _page: pytest.fail("unavailable engine must not render pages"),
    )

    assert "OCR not executed for scan.pdf" in result.content
    assert "strategy=ocr_only" in result.content
    assert "remote OCR requires explicit api_key and base_url configuration" in result.content
    assert result.ocr_report is not None
    assert result.ocr_report.candidate_pages == [0]
    assert result.ocr_report.applied_pages == []


def test_scanned_pdf_with_policy_none_does_not_render_or_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "scan-none.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    register_ocr_engine("mock", lambda config: _RecordingOcrEngine(config))
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "none")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "mock")

    result = apply_pdf_ocr_if_needed(
        "scan-none.pdf",
        pdf_path,
        ExtractedDocumentPayload(content="base parser text"),
        classifier=_StaticClassifier(_classification(ocr_pages=[0], strategy="ocr_only")),
        render_page=lambda _path, _page: pytest.fail("policy=none must not render pages"),
    )

    assert "base parser text" in result.content
    assert "OCR not executed for scan-none.pdf" in result.content
    assert "reason=OCR policy is none" in result.content
    assert _RecordingOcrEngine.calls == []
    assert result.ocr_report is not None
    assert result.ocr_report.candidate_pages == [0]
    assert result.ocr_report.applied_pages == []
    assert result.ocr_report.warning == "OCR policy is none"


def test_auto_policy_with_failing_engine_degrades_visibly_per_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "scan-auto-failing.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    rendered_pages: list[int] = []
    register_ocr_engine("mock", lambda config: _FailingOcrEngine(config))
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "auto")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "mock")

    def _render_page(_path: Path, page_index: int) -> bytes:
        rendered_pages.append(page_index)
        return f"page-{page_index + 1}".encode("ascii")

    result = apply_pdf_ocr_if_needed(
        "scan-auto-failing.pdf",
        pdf_path,
        ExtractedDocumentPayload(content="base parser text"),
        classifier=_StaticClassifier(_classification(ocr_pages=[0], strategy="ocr_only")),
        render_page=_render_page,
    )

    assert rendered_pages == [0]
    assert _RecordingOcrEngine.calls == [(b"page-1", "en")]
    assert "base parser text" in result.content
    assert "OCR not executed for scan-auto-failing.pdf" in result.content
    assert "page 1: mock runtime adapter is not wired" in result.content
    assert result.ocr_report is not None
    assert result.ocr_report.candidate_pages == [0]
    assert result.ocr_report.applied_pages == []
    assert result.ocr_report.warning == "page 1: mock runtime adapter is not wired"


def test_mock_engine_merges_scanned_and_mixed_page_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    rendered_pages: list[int] = []
    register_ocr_engine("mock", lambda config: _RecordingOcrEngine(config))
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "engine")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "mock")
    monkeypatch.setenv("LITASSIST_OCR_LANG", "zh")

    def _render_page(_path: Path, page_index: int) -> bytes:
        rendered_pages.append(page_index)
        return f"page-{page_index + 1}".encode("ascii")

    result = apply_pdf_ocr_if_needed(
        "mixed.pdf",
        pdf_path,
        ExtractedDocumentPayload(content="base parser text"),
        classifier=_StaticClassifier(
            _classification(text_pages=[2], ocr_pages=[0], mixed_pages=[1], strategy="hybrid")
        ),
        render_page=_render_page,
    )

    assert rendered_pages == [0, 1]
    assert _RecordingOcrEngine.calls == [(b"page-1", "zh"), (b"page-2", "zh")]
    assert "[OCR Page 1]\nmock text zh page-1" in result.content
    assert "[OCR Page 2]\nmock text zh page-2" in result.content
    assert result.ocr_report is not None
    assert result.ocr_report.applied_pages == [0, 1]


def test_real_classifier_routes_scanned_and_mixed_pages_through_ingestion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "classifier-real.pdf"
    _write_ocr_classifier_fixture_pdf(pdf_path)
    rendered_pages: list[int] = []
    register_ocr_engine("mock", lambda config: _RecordingOcrEngine(config))
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "engine")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "mock")
    monkeypatch.setenv("LITASSIST_OCR_LANG", "en")

    def _render_page(path: Path, page_index: int) -> bytes:
        assert path == pdf_path
        rendered_pages.append(page_index)
        return f"page-{page_index + 1}".encode("ascii")

    result = apply_pdf_ocr_if_needed(
        "classifier-real.pdf",
        pdf_path,
        ExtractedDocumentPayload(content="base parser text"),
        render_page=_render_page,
    )

    assert rendered_pages == [1, 2]
    assert _RecordingOcrEngine.calls == [(b"page-2", "en"), (b"page-3", "en")]
    assert "[OCR Page 2]\nmock text en page-2" in result.content
    assert "[OCR Page 3]\nmock text en page-3" in result.content
    assert result.ocr_report is not None
    assert result.ocr_report.strategy == "hybrid"
    assert result.ocr_report.candidate_pages == [1, 2]
    assert result.ocr_report.applied_pages == [1, 2]
    assert result.ocr_report.warning is None


def test_windows_ocr_engine_merges_real_scanned_pdf_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows OCR real ingestion proof requires Windows")

    engine = build_ocr_engine("windows")
    health = engine.health_check()
    if not health.ok:
        pytest.skip(f"Windows OCR unavailable: {health.detail}")

    pdf_path = tmp_path / "windows-real-ingestion.pdf"
    _write_windows_ocr_ingestion_fixture_pdf(pdf_path)
    monkeypatch.setenv("LITASSIST_OCR_POLICY", "engine")
    monkeypatch.setenv("LITASSIST_OCR_ENGINE", "windows")
    monkeypatch.setenv("LITASSIST_OCR_LANG", "en")

    result = apply_pdf_ocr_if_needed(
        "windows-real-ingestion.pdf",
        pdf_path,
        ExtractedDocumentPayload(content="base parser text"),
    )

    assert "base parser text" in result.content
    normalized_content = result.content.upper()
    assert "SCHOLAR" in normalized_content
    assert "INGESTION" in normalized_content
    assert result.ocr_report is not None
    assert result.ocr_report.strategy == "ocr_only"
    assert result.ocr_report.candidate_pages == [0]
    assert result.ocr_report.applied_pages == [0]
    assert result.ocr_report.warning is None


def test_batch_pdf_parse_results_are_ocr_post_processed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "batch.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    seen: list[tuple[str, Path, str]] = []

    def _apply_ocr(
        filename: str,
        source_path: Path,
        payload: ExtractedDocumentPayload,
    ) -> ExtractedDocumentPayload:
        seen.append((filename, source_path, payload.content))
        return ExtractedDocumentPayload(content=f"{payload.content}\nOCR batch text")

    monkeypatch.setattr(upload_service_module, "apply_pdf_ocr_if_needed", _apply_ocr)

    service = UnifiedBatchUploadService(
        persist_upload=lambda *_args: None,
        load_doc_store=lambda _project_id: {},
        save_doc_store=lambda *_args: None,
        extract_payload=lambda _filename, _path: pytest.fail("batch parse should supply payload"),
        truncate_content=lambda text: text,
        ensure_extracted_text=lambda _filename, text: text,
        write_material_document_content=lambda *_args, **_kwargs: {"chunks": 1},
        safe_upload_filename=lambda name: name,
    )
    monkeypatch.setattr(
        service,
        "_try_parse_pdf_batch",
        lambda _paths, _max_workers: [("batch parser text", None, None)],
    )

    result = service._extract_sources_sync(
        [
            BatchSource(
                source_path=pdf_path,
                display_name="batch.pdf",
                source_relative_path="batch.pdf",
                source_fingerprint="fp",
                source_size=pdf_path.stat().st_size,
            )
        ],
        max_workers=None,
    )

    payload = result[pdf_path]
    assert isinstance(payload, ExtractedDocumentPayload)
    assert payload.content == "batch parser text\nOCR batch text"
    assert seen == [("batch.pdf", pdf_path, "batch parser text")]
