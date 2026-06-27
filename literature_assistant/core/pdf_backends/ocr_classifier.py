# -*- coding: utf-8 -*-
"""PDF 页面类型分类器：文本型 vs 扫描型"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = ["OCRNeedClassifier", "PDFClassificationResult", "PDFStrategy"]

logger = logging.getLogger("OCRNeedClassifier")

PDFStrategy = Literal["text_only", "ocr_only", "hybrid"]


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

        doc = pymupdf.open(str(pdf_path))
        text_pages = []
        ocr_pages = []
        mixed_pages = []
        total_text_chars = 0

        try:
            for page_num in range(len(doc)):
                page = doc[page_num]

                # 1. 提取文本
                text = page.get_text().strip()
                text_len = len(text)
                total_text_chars += text_len

                # 2. 分析图片
                images = page.get_images(full=True)
                page_rect = page.rect
                page_area = page_rect.width * page_rect.height

                # 计算图片占比
                image_area = 0.0
                if images and page_area > 0:
                    for img in images:
                        # img 格式：(xref, smask, width, height, bpc, colorspace, ...)
                        try:
                            # 尝试获取图片在页面上的实际矩形
                            img_rects = page.get_image_rects(img[0])
                            if img_rects:
                                for rect in img_rects:
                                    image_area += abs(rect.width * rect.height)
                        except Exception:
                            # Fallback：使用图片原始尺寸估算
                            if len(img) >= 4:
                                img_width = img[2] if img[2] else 0
                                img_height = img[3] if img[3] else 0
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
            doc.close()

        # 4. 确定整体策略
        total_pages = len(text_pages) + len(ocr_pages) + len(mixed_pages)
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
