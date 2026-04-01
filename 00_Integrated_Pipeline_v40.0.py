# -*- coding: utf-8 -*-
"""
00_Integrated_Pipeline_v40.0.py
文献处理器 6 层架构总控流水线 (Standard v4.0)

架构层级：
- E-Layer: 提取 (Extraction) -> 视觉与文本解析
- A-Layer: 调度 (Agent) -> 意图解析与关注点提取
- R-Layer: 检索 (Retrieval) -> 混合语义检索
- K-Layer: 索引 (Knowledge) -> 数据契约与项目看板
- G-Layer: 生成 (Generation) -> 学术评分与事实提取
- P-Layer: 展示 (Presentation) -> Word 文档排版
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# 导入模块化层
try:
    from layers.e_layer_multimodal import full_extract, refine_multimodal_assets
    from layers.a_layer_agent_coordinator import infer_open_focus_points
    from layers.r_layer_hybrid_retriever import hybrid_search
    from layers.k_layer_index_builder import KLayerManager
    from layers.g_layer_academic_generator import AcademicScorer
    from layers.p_layer_presentation_word import generate_docx_report
    from layers.contracts import make_bound_contract, bind_evidence
except ImportError as e:
    print(f"Error: 无法加载架构层模块，请确保 layers/ 目录完整。错误信息: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Pipeline_v40")

def run_pipeline(pdf_path: str, goal: str, output_dir: str = "output"):
    pdf_path = Path(pdf_path)
    out_dir = Path(output_dir) / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"开始处理文献: {pdf_path.name}")
    start_time = datetime.now()

    # ==========================================
    # Phase 1: E-Layer (提取)
    # ==========================================
    logger.info(">>> [E-Layer] 正在进行多模态提取...")
    raw_extract = full_extract(str(pdf_path))
    extract_json = out_dir / "01_full_extract.json"
    with open(extract_json, 'w', encoding='utf-8') as f:
        json.dump(raw_extract, f, ensure_ascii=False, indent=2)

    # ==========================================
    # Phase 2: A-Layer & R-Layer (调度与检索)
    # ==========================================
    logger.info(">>> [A-Layer & R-Layer] 正在执行目标导向检索...")
    # 提取关注点 (A-Layer)
    focus_points = infer_open_focus_points("", goal)
    # 执行混合检索 (R-Layer)
    retrieval_results = hybrid_search(raw_extract, query=goal, top_k=25)
    
    # 执行图文绑定 (Binding Layer) [NEW v40.1]
    logger.info(">>> [Binding] 正在进行图文契约绑定...")
    bound_contract = bind_evidence(raw_extract)

    retrieval_json = out_dir / "02_hybrid_retrieval.json"
    with open(retrieval_json, 'w', encoding='utf-8') as f:
        json.dump({
            'status': 'hybrid_retrieval_ready',
            'focus_points': focus_points,
            'top_chunks': retrieval_results,
        }, f, ensure_ascii=False, indent=2)
    
    # ==========================================
    # Phase 3: G-Layer (学术生成与评分)
    # ==========================================
    logger.info(">>> [G-Layer] 正在进行学术评分与证据筛选...")
    scorer = AcademicScorer(goal)
    # 将提取结果转换为契约格式进行评分
    analysis = scorer.analyze_bound_data(bound_contract)
    analysis_json = out_dir / "03_analysis_report.json"
    with open(analysis_json, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # ==========================================
    # Phase 4: K-Layer (索引与打包)
    # ==========================================
    logger.info(">>> [K-Layer] 正在构建项目看版与数据契约...")
    k_manager = KLayerManager(out_dir)
    # 模拟从分析结果生成最终材料包 (Material Pack)
    # 在 4.0 架构中，这一步将分析结果结构化为 writing_material_pack.json
    material_pack = {
        "paper_title": Path(pdf_path).stem,
        "goal": goal,
        "source_pdf": str(pdf_path),
        "writing_point_cards": analysis.get("selected_writing_points", []),
        "single_figure_cards": analysis.get("selected_figures", []),
        "single_table_cards": analysis.get("selected_tables", []),
        "semantic_themes": analysis.get("semantic_themes", []),
        "schema_version": "v3.academic-synthesis",
        "stats": analysis.get("stats_analysis", {}),
        "quality_gates": {
            "has_writing_points": len(analysis.get("selected_writing_points", [])) > 0,
            "has_figures": len(analysis.get("selected_figures", [])) > 0
        }
    }
    material_json = out_dir / "02_writing_material_pack.json"
    with open(material_json, 'w', encoding='utf-8') as f:
        json.dump(material_pack, f, ensure_ascii=False, indent=2)
    
    # 构建项目看板 (Project View)
    k_view = k_manager.build_project_view(raw_extract, bound_contract, analysis, goal)
    material_pack['quality_gates'] = k_view.get('quality_gates', material_pack.get('quality_gates', {}))
    with open(material_json, 'w', encoding='utf-8') as f:
        json.dump(material_pack, f, ensure_ascii=False, indent=2)

    # ==========================================
    # Phase 4.5: Multimodal Refinement (多模态精炼) [v40.2]
    # ==========================================
    logger.info(">>> [E-Layer] 正在执行像素级图像与表格裁切 (Clean Crop)...")
    refinement_result = refine_multimodal_assets(material_pack, out_dir=out_dir, dpi=220)
    
    if refinement_result.get('status') == 'ok':
        material_pack['single_figure_cards'] = refinement_result.get('single_figure_cards_refined', [])
        material_pack['single_table_cards'] = refinement_result.get('single_table_cards_refined', [])
        
        fig_count = len(material_pack['single_figure_cards'])
        tab_count = len(material_pack['single_table_cards'])
        logger.info(f"成功精炼 {fig_count} 张图表与 {tab_count} 个表格。")
        
        # 覆写材料包
        with open(material_json, 'w', encoding='utf-8') as f:
            json.dump(material_pack, f, ensure_ascii=False, indent=2)
    else:
        logger.warning(f"多模态精炼跳过或失败: {refinement_result.get('message')}")

    # ==========================================
    # Phase 5: P-Layer (展示)
    # ==========================================
    logger.info(">>> [P-Layer] 正在生成人看版 Word 文档...")
    docx_path = out_dir / "00_交付文献分析整合稿.docx"
    generate_docx_report(material_json, docx_path)

    duration = datetime.now() - start_time
    logger.info(f"处理完成！耗时: {duration}")
    logger.info(f"最终产物目录: {out_dir.resolve()}")
    
    return {
        "status": "success",
        "output_dir": str(out_dir.resolve()),
        "docx": str(docx_path.resolve()),
        "stats": material_pack["stats"]
    }

def main():
    parser = argparse.ArgumentParser(description='文献处理器 v40.0 模块化流水线总控')
    parser.add_argument('pdf', help='输入 PDF 文件路径')
    parser.add_argument('--goal', default='提取文献核心结论与实验数据', help='写作目标/关注点')
    parser.add_argument('--out', default='output', help='输出根目录')
    
    args = parser.parse_args()
    
    try:
        result = run_pipeline(args.pdf, args.goal, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"流水线执行失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
