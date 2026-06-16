#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 OCR 分类器"""

import sys
import io
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent / "literature_assistant" / "core"))

from pdf_backends.ocr_classifier import OCRNeedClassifier


def main():
    print("=" * 70)
    print("OCR 分类器测试")
    print("=" * 70)

    classifier = OCRNeedClassifier()
    pdf_folder = Path("C:/Users/xiao/Downloads/AlSi10Mg实验")

    if not pdf_folder.exists():
        print(f"ERROR: 文件夹不存在: {pdf_folder}")
        return

    all_pdfs = list(pdf_folder.glob("*.pdf"))[:10]
    print(f"\n测试样本: {len(all_pdfs)} 个 PDF\n")

    text_only_count = 0
    ocr_only_count = 0
    hybrid_count = 0

    for i, pdf_path in enumerate(all_pdfs, 1):
        try:
            result = classifier.classify_pdf(pdf_path)

            if result.strategy == "text_only":
                text_only_count += 1
                status = "✓ 纯文本"
            elif result.strategy == "ocr_only":
                ocr_only_count += 1
                status = "⚠ 需要 OCR"
            else:
                hybrid_count += 1
                status = "◐ 混合型"

            print(f"{i}. {pdf_path.name}")
            print(f"   策略: {status}")
            print(f"   总页数: {result.total_pages}")
            print(f"   文本页: {len(result.text_pages)}")
            print(f"   OCR 页: {len(result.ocr_pages)}")
            print(f"   混合页: {len(result.mixed_pages)}")
            print(f"   平均密度: {result.avg_text_density:.1f} 字符/页")
            print()

        except Exception as e:
            print(f"{i}. {pdf_path.name} - ERROR: {e}\n")

    # 统计
    print("=" * 70)
    print("分类统计")
    print("=" * 70)
    print(f"纯文本型: {text_only_count}/{len(all_pdfs)} ({text_only_count/len(all_pdfs)*100:.1f}%)")
    print(f"需要 OCR: {ocr_only_count}/{len(all_pdfs)} ({ocr_only_count/len(all_pdfs)*100:.1f}%)")
    print(f"混合型: {hybrid_count}/{len(all_pdfs)} ({hybrid_count/len(all_pdfs)*100:.1f}%)")
    print("=" * 70)

    # 推荐
    if text_only_count == len(all_pdfs):
        print("\n✅ 推荐：全部使用 PyMuPDF 快速处理")
    elif ocr_only_count == len(all_pdfs):
        print("\n⚠️ 推荐：全部使用 OCR API 处理")
    else:
        print(f"\n◐ 推荐：混合策略（{text_only_count} 个文本 + {ocr_only_count + hybrid_count} 个 OCR）")


if __name__ == "__main__":
    main()
