# -*- coding: utf-8 -*-
"""Tests for OCR classifier input guardrails."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends.ocr_classifier import OCRNeedClassifier, PDFStrategy  # noqa: E402


def test_classifier_rejects_invalid_threshold_shapes() -> None:
    with pytest.raises(TypeError, match="text_density_threshold"):
        OCRNeedClassifier(text_density_threshold=True)

    with pytest.raises(TypeError, match="ocr_density_threshold"):
        OCRNeedClassifier(ocr_density_threshold=True)

    with pytest.raises(ValueError, match="greater than ocr_density_threshold"):
        OCRNeedClassifier(text_density_threshold=20, ocr_density_threshold=20)

    with pytest.raises(ValueError, match="image_area_ratio_threshold"):
        OCRNeedClassifier(image_area_ratio_threshold=1.5)


def test_classifier_rejects_invalid_pdf_path_before_pymupdf_import(tmp_path: Path) -> None:
    classifier = OCRNeedClassifier()

    with pytest.raises(TypeError, match="pathlib.Path"):
        classifier.classify_pdf("paper.pdf")  # type: ignore[arg-type]

    with pytest.raises(FileNotFoundError, match="PDF file not found"):
        classifier.classify_pdf(tmp_path / "missing.pdf")


def test_pdf_strategy_type_alias_accepts_known_classifier_strategies() -> None:
    strategies: tuple[PDFStrategy, ...] = ("text_only", "ocr_only", "hybrid")

    assert strategies == ("text_only", "ocr_only", "hybrid")
