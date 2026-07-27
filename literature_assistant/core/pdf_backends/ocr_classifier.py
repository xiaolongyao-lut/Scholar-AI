# -*- coding: utf-8 -*-
"""PDF 页面类型分类器：文本型 vs 扫描型"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeGuard

__all__ = ["OCRNeedClassifier", "PDFClassificationResult", "PDFStrategy"]

logger = logging.getLogger("OCRNeedClassifier")

PDFStrategy = Literal["text_only", "ocr_only", "hybrid"]


class _CloseableDocument(Protocol):
    """Minimum resource capability required after opening a PDF."""

    def close(self) -> None: ...


class _PageSequenceDocument(_CloseableDocument, Protocol):
    """PyMuPDF document capabilities consumed by classification."""

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> object: ...


def _is_page_sequence_document(value: object) -> TypeGuard[_PageSequenceDocument]:
    """Narrow an opened value to the sequence API consumed below."""

    return (
        callable(getattr(value, "__len__", None))
        and callable(getattr(value, "__getitem__", None))
        and callable(getattr(value, "close", None))
    )


def _is_closeable_document(value: object) -> TypeGuard[_CloseableDocument]:
    """Narrow an opened value before any later capability validation."""

    return callable(getattr(value, "close", None))


def _call_runtime_method(
    target: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """Call one method exposed by PyMuPDF's partially typed runtime surface."""

    method = getattr(target, method_name, None)
    if not callable(method):
        raise TypeError(f"PyMuPDF object must expose callable {method_name}")
    result: object = method(*args, **kwargs)
    return result


def _require_sequence(value: object, *, label: str) -> list[object] | tuple[object, ...]:
    """Validate a PyMuPDF sequence before indexing or iterating over it."""

    if not isinstance(value, (list, tuple)):
        raise TypeError(f"PyMuPDF {label} must be a list or tuple")
    return value


def _require_number(value: object, *, label: str) -> float:
    """Validate and normalize one PyMuPDF geometry value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"PyMuPDF {label} must be numeric")
    return float(value)


def _geometry_value(target: object, attribute: str) -> float:
    """Read one validated numeric attribute from a PyMuPDF rectangle."""

    return _require_number(
        getattr(target, attribute, None),
        label=f"rectangle {attribute}",
    )


def _optional_dimension(value: object) -> float:
    """Return a non-negative image dimension, or zero for malformed metadata."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, float(value))


@dataclass(frozen=True)
class PDFClassificationResult:
    """PDF 分类结果

    Args:
        text_pages: 文本型页面列表（页码从 0 开始）
        ocr_pages: 需要 OCR 的扫描型页面列表
        mixed_pages: 文本+图片混合页面列表
        strategy: "text_only" | "ocr_only" | "hybrid"
        total_pages: 总页数
        avg_text_density: 平均文本密度（字符/页）
    """

    text_pages: list[int]
    ocr_pages: list[int]
    mixed_pages: list[int]
    strategy: PDFStrategy
    total_pages: int
    avg_text_density: float


class OCRNeedClassifier:
    """PDF 页面类型智能分类器

    启发式规则：
    - 文本密度 >100 字/页 → text_page
    - 文本密度 <20 字/页 → ocr_page
    - 20-100 字/页 + 大图片占比 >0.5 → mixed_page
    """

    def __init__(
        self,
        text_density_threshold: int = 100,
        ocr_density_threshold: int = 20,
        image_area_ratio_threshold: float = 0.5,
    ):
        """初始化分类器

        Args:
            text_density_threshold: 文本型阈值（字符数）
            ocr_density_threshold: 扫描型阈值（字符数）
            image_area_ratio_threshold: 图片面积占比阈值
        """
        if isinstance(text_density_threshold, bool) or not isinstance(
            text_density_threshold, int
        ):
            raise TypeError("text_density_threshold must be an integer")
        if isinstance(ocr_density_threshold, bool) or not isinstance(ocr_density_threshold, int):
            raise TypeError("ocr_density_threshold must be an integer")
        if text_density_threshold <= 0:
            raise ValueError("text_density_threshold must be positive")
        if ocr_density_threshold < 0:
            raise ValueError("ocr_density_threshold must be non-negative")
        if text_density_threshold <= ocr_density_threshold:
            raise ValueError("text_density_threshold must be greater than ocr_density_threshold")
        if isinstance(image_area_ratio_threshold, bool) or not isinstance(
            image_area_ratio_threshold, (int, float)
        ):
            raise TypeError("image_area_ratio_threshold must be numeric")
        if not 0.0 <= float(image_area_ratio_threshold) <= 1.0:
            raise ValueError("image_area_ratio_threshold must be between 0 and 1")

        self.text_threshold = text_density_threshold
        self.ocr_threshold = ocr_density_threshold
        self.image_ratio_threshold = float(image_area_ratio_threshold)

    def classify_pdf(self, pdf_path: Path) -> PDFClassificationResult:
        """分类 PDF 文件的每一页

        Args:
            pdf_path: PDF 文件路径

        Returns:
            分类结果

        Raises:
            ImportError: PyMuPDF 未安装
            OSError: PDF 文件无法打开
        """
        if not isinstance(pdf_path, Path):
            raise TypeError("pdf_path must be a pathlib.Path")
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            import pymupdf
        except ImportError as exc:
            raise ImportError(
                "pymupdf is required for OCR classification. "
                "Install it with: pip install pymupdf"
            ) from exc

        opened_document = _call_runtime_method(pymupdf, "open", str(pdf_path))
        if not _is_closeable_document(opened_document):
            raise TypeError("PyMuPDF open() must return a closeable document")
        document = opened_document
        text_pages = []
        ocr_pages = []
        mixed_pages = []
        total_text_chars = 0

        try:
            if not _is_page_sequence_document(document):
                raise TypeError(
                    "PyMuPDF open() must return a closeable page-sequence document"
                )
            for page_num in range(len(document)):
                page = document[page_num]

                # 1. 提取文本
                raw_text = _call_runtime_method(page, "get_text")
                if not isinstance(raw_text, str):
                    raise TypeError("PyMuPDF Page.get_text() must return a string")
                text = raw_text.strip()
                text_len = len(text)
                total_text_chars += text_len

                # 2. 分析图片
                images = _require_sequence(
                    _call_runtime_method(page, "get_images", full=True),
                    label="Page.get_images() result",
                )
                page_rect = getattr(page, "rect", None)
                page_area = _geometry_value(page_rect, "width") * _geometry_value(
                    page_rect,
                    "height",
                )

                # 计算图片占比
                image_area = 0.0
                if images and page_area > 0:
                    for raw_image in images:
                        image = _require_sequence(raw_image, label="image metadata")
                        if not image:
                            continue
                        # img 格式：(xref, smask, width, height, bpc, colorspace, ...)
                        try:
                            # 尝试获取图片在页面上的实际矩形
                            img_rects = _require_sequence(
                                _call_runtime_method(page, "get_image_rects", image[0]),
                                label="Page.get_image_rects() result",
                            )
                            if img_rects:
                                for rect in img_rects:
                                    image_area += abs(
                                        _geometry_value(rect, "width")
                                        * _geometry_value(rect, "height")
                                    )
                        except Exception:
                            # Fallback：使用图片原始尺寸估算
                            if len(image) >= 4:
                                img_width = _optional_dimension(image[2])
                                img_height = _optional_dimension(image[3])
                                image_area += img_width * img_height * 0.5  # 保守估计

                image_ratio = image_area / page_area if page_area > 0 else 0.0

                # 3. 分类逻辑
                if text_len >= self.text_threshold:
                    # 文本密度高 → 文本型
                    text_pages.append(page_num)
                elif text_len < self.ocr_threshold:
                    # 文本密度低 → 扫描型
                    ocr_pages.append(page_num)
                elif image_ratio > self.image_ratio_threshold:
                    # 中等文本密度 + 大图片 → 混合型
                    mixed_pages.append(page_num)
                else:
                    # 中等文本密度 + 小图片 → 文本型
                    text_pages.append(page_num)
        finally:
            document.close()

        # 4. 确定整体策略
        total_pages = len(text_pages) + len(ocr_pages) + len(mixed_pages)
        strategy: PDFStrategy
        if not ocr_pages and not mixed_pages:
            strategy = "text_only"
        elif not text_pages and not mixed_pages:
            strategy = "ocr_only"
        else:
            strategy = "hybrid"

        avg_density = total_text_chars / total_pages if total_pages > 0 else 0.0

        logger.info(
            "pdf_classify path=%s total=%d strategy=%s text=%d ocr=%d mixed=%d density=%.1f",
            pdf_path.name,
            total_pages,
            strategy,
            len(text_pages),
            len(ocr_pages),
            len(mixed_pages),
            avg_density,
        )

        return PDFClassificationResult(
            text_pages=text_pages,
            ocr_pages=ocr_pages,
            mixed_pages=mixed_pages,
            strategy=strategy,
            total_pages=total_pages,
            avg_text_density=avg_density,
        )
