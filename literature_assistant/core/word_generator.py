# -*- coding: utf-8 -*-
"""
word_generator.py
调用 P-Layer (Presentation) 模块化层进行 Word 文档生成。
"""

import argparse
import json
import sys
from pathlib import Path

# 导入 P-Layer
try:
    from layers.p_layer_presentation_word import generate_docx_report
except ImportError:
    # 兼容相对于当前目录的导入
    sys.path.append(str(Path(__file__).parent))
    from layers.p_layer_presentation_word import generate_docx_report

def main():
    ap = argparse.ArgumentParser(description='把分析结果材料包整合成 Word 文档。')
    ap.add_argument('input_json', help='材料包 JSON 路径 (writing_material_pack.json)')
    ap.add_argument('output_docx', help='目标输出 docx 路径')
    args = ap.parse_args()

    try:
        out = generate_docx_report(args.input_json, args.output_docx)
        print(json.dumps({'status': 'ok', 'output_docx': str(out)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__':
    main()
