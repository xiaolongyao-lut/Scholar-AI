#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PyMuPDF 批处理性能测试"""

import time
import sys
import io
from pathlib import Path

# UTF-8 输出
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from literature_assistant.core.pdf_backends.pymupdf_backend import PyMuPDFBackend


def main():
    print("=" * 60)
    print("PyMuPDF 批处理性能测试")
    print("=" * 60)

    backend = PyMuPDFBackend()
    pdf_folder = Path("C:/Users/xiao/Downloads/AlSi10Mg实验")

    if not pdf_folder.exists():
        print(f"ERROR: 文件夹不存在: {pdf_folder}")
        return

    all_pdfs = list(pdf_folder.glob("*.pdf"))
    print(f"\n找到 {len(all_pdfs)} 个 PDF")

    # 测试不同 worker 数量
    for max_workers in [2, 4, 6]:
        print(f"\n{'='*60}")
        print(f"测试配置: max_workers={max_workers}")
        print(f"{'='*60}")

        start = time.time()
        results = backend.parse_batch(all_pdfs, max_workers=max_workers)
        elapsed = time.time() - start

        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success

        print(f"\n结果:")
        print(f"  成功: {success}/{len(all_pdfs)}")
        print(f"  失败: {failed}/{len(all_pdfs)}")
        print(f"  耗时: {elapsed:.1f}s ({elapsed/60:.2f} 分钟)")
        print(f"  速度: {len(all_pdfs)/elapsed:.2f} PDF/s")

        if elapsed < 180:
            print(f"  评级: GOOD (<3 分钟)")
        elif elapsed < 300:
            print(f"  评级: OK (3-5 分钟)")
        else:
            print(f"  评级: BAD (>5 分钟)")

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
