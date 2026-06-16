#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""摘要提取准确率测试"""

import sys
import io
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from literature_assistant.core.pdf_backends.pymupdf_backend import PyMuPDFBackend
from literature_assistant.core.services.abstract_extractor import (
    extract_abstract_enhanced,
)


def main():
    print("=" * 60)
    print("摘要提取准确率测试")
    print("=" * 60)

    backend = PyMuPDFBackend()
    pdf_folder = Path("C:/Users/xiao/Downloads/AlSi10Mg实验")

    if not pdf_folder.exists():
        print(f"ERROR: 文件夹不存在: {pdf_folder}")
        return

    # 测试前 10 个 PDF
    test_pdfs = list(pdf_folder.glob("*.pdf"))[:10]
    print(f"\n测试样本: {len(test_pdfs)} 个 PDF\n")

    results = []
    for i, pdf_path in enumerate(test_pdfs, 1):
        try:
            text, _, _ = backend.parse(pdf_path)
            result = extract_abstract_enhanced(text)

            print(f"{i}. {pdf_path.name}")
            print(f"   来源: {result['source']}")
            print(f"   置信度: {result['confidence']:.2f}")
            print(f"   语言: {result['language']}")
            print(f"   长度: {len(result['abstract'])} 字符")
            print(f"   预览: {result['abstract'][:100]}...")
            print()

            results.append(result)
        except Exception as e:
            print(f"{i}. {pdf_path.name} - ERROR: {e}\n")

    # 统计
    if results:
        abstract_count = sum(1 for r in results if r["source"] == "abstract")
        fallback_count = len(results) - abstract_count
        avg_confidence = sum(r["confidence"] for r in results) / len(results)

        print("=" * 60)
        print(f"统计:")
        print(
            f"  识别到 Abstract: {abstract_count}/{len(results)} ({abstract_count/len(results)*100:.1f}%)"
        )
        print(f"  Fallback: {fallback_count}/{len(results)}")
        print(f"  平均置信度: {avg_confidence:.2f}")
        print("=" * 60)
    else:
        print("=" * 60)
        print("没有成功解析的 PDF")
        print("=" * 60)


if __name__ == "__main__":
    main()
