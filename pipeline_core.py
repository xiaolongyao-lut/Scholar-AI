# -*- coding: utf-8 -*-
"""
pipeline_core.py
文献处理器 6 层架构总控流水线 (Standard)

架构层级：
- E-Layer: 提取 (Extraction) -> 视觉与文本解析
- A-Layer: 调度 (Agent) -> 意图解析与关注点提取
- R-Layer: 检索 (Retrieval) -> 混合语义检索
- K-Layer: 索引 (Knowledge) -> 数据契约与项目看板
- G-Layer: 生成 (Generation) -> 学术评分与事实提取
- P-Layer: 展示 (Presentation) -> Word 文档排版
"""

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

# 导入模块化层（Patch 友好导入模式）
try:
    from modules.pipeline_observer import PipelineObserver
    import layers.e_layer_multimodal as e_layer
    import layers.a_layer_agent_coordinator as a_layer
    import layers.r_layer_hybrid_retriever as r_layer
    from layers.k_layer_index_builder import KLayerManager
    from layers.g_layer_academic_generator import AcademicScorer
    import layers.p_layer_presentation_word as p_layer
    import layers.contracts as contracts
    from material_bundler import build_material_pack
except ImportError as e:
    print(f"Error: 无法加载架构层模块，请确保 layers/ 目录完整。错误信息: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Pipeline_Core")

WINDOWS_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
MAX_SAFE_COMPONENT_LEN = 120


def _resolve_maybe_awaitable(value: Any) -> Any:
    """Resolve coroutine-style results without forcing the whole pipeline async."""
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _json_safe_copy(value: Any) -> Any:
    """Return a JSON-safe deep copy for pipeline envelopes."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def sanitize_path_component(name: str, fallback: str = "untitled") -> str:
    """Return a Windows-safe path component that keeps Unicode but removes invalid trailing forms."""
    original = str(name or "")
    candidate = WINDOWS_INVALID_CHARS_RE.sub("_", original)
    candidate = re.sub(r"\s+", " ", candidate).strip().strip(" .")
    if candidate in {"", ".", ".."}:
        candidate = fallback
    candidate = candidate[:MAX_SAFE_COMPONENT_LEN].rstrip(" .")
    if not candidate:
        candidate = fallback

    try:
        if hasattr(os.path, "isreserved") and os.path.isreserved(candidate):
            candidate = f"_{candidate}"
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    if candidate != original.strip():
        suffix = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
        head = candidate[: max(1, MAX_SAFE_COMPONENT_LEN - 9)].rstrip(" .")
        candidate = f"{head}_{suffix}"
    return candidate or fallback

def run_pipeline(pdf_path: str, goal: str, output_dir: str = "output", observer: Optional[PipelineObserver] = None):
    pdf_path = Path(pdf_path)
    pipeline_id = sanitize_path_component(pdf_path.stem)
    out_dir = Path(output_dir) / pipeline_id
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if observer:
        observer.on_run_start(pipeline_id, {"goal": goal, "pdf": str(pdf_path), "original_title": pdf_path.stem})

    logger.info("开始处理文献: %s", pdf_path.name)
    start_time = datetime.now()
    
    try:
        if observer: observer.on_phase_start("extraction", pipeline_id)
        logger.info(">>> [E-Layer] 正在进行多模态提取...")
        raw_extract = e_layer.full_extract(str(pdf_path))
        if observer: observer.on_phase_success("extraction", pipeline_id, {"chunk_count": len(raw_extract.get("chunks", []))})
    
        extract_json = out_dir / "01_full_extract.json"
        with open(extract_json, 'w', encoding='utf-8') as f:
            json.dump(raw_extract, f, ensure_ascii=False, indent=2, default=str)

        if observer: observer.on_phase_start("retrieval", pipeline_id)
        logger.info(">>> [A-Layer & R-Layer] 正在执行目标导向检索...")
        focus_points = a_layer.infer_open_focus_points("", goal)
        retrieval_results = _resolve_maybe_awaitable(
            r_layer.hybrid_search(raw_extract, query=goal, top_k=25)
        )
        try:
            retrieval_count = len(retrieval_results)
        except TypeError:
            retrieval_count = 0
        
        logger.info(">>> [Binding] 正在进行图文契约绑定...")
        bound_contract = contracts.bind_evidence(raw_extract)
        if observer: observer.on_phase_success("retrieval", pipeline_id, {"hit_count": retrieval_count})

        retrieval_json = out_dir / "02_hybrid_retrieval.json"
        with open(retrieval_json, 'w', encoding='utf-8') as f:
            json.dump({
                'status': 'hybrid_retrieval_ready',
                'focus_points': focus_points,
                'top_chunks': retrieval_results,
            }, f, ensure_ascii=False, indent=2, default=str)
    
        if observer: observer.on_phase_start("scoring", pipeline_id)
        logger.info(">>> [G-Layer & K-Layer] 正在进行学术打分与索引构建...")
        scorer = AcademicScorer(goal=goal)
        scoring_results = _resolve_maybe_awaitable(
            scorer.analyze_bound_data(bound_contract)
        )
        if isinstance(scoring_results, dict):
            scoring_results.setdefault("llm_status", getattr(scorer, "llm_status", "unknown"))

        k_manager = KLayerManager(out_dir)
        project_view = k_manager.build_project_view(raw_extract, bound_contract, scoring_results, goal)
        if observer: observer.on_phase_success("scoring", pipeline_id, {"score": scoring_results.get("overall_score")})

        scoring_json = out_dir / "03_academic_scoring.json"
        with open(scoring_json, 'w', encoding='utf-8') as f:
            json.dump({'scoring': scoring_results, 'view': project_view}, f, ensure_ascii=False, indent=2, default=str)

        logger.info(">>> [K-Layer] 正在构建写作材料包...")
        material_pack = build_material_pack(scoring_results, bound_contract)
        material_pack.setdefault("paper_title", pdf_path.stem)
        material_pack.setdefault("schema_version", "v3.academic-synthesis")
        material_pack.setdefault("source_pdf", str(pdf_path.resolve()))
        material_pack.setdefault("goal", goal)
        material_pack["pipeline_id"] = pipeline_id
        material_pack["llm_status"] = scoring_results.get("llm_status", getattr(scorer, "llm_status", "unknown"))

        # Backward-compatible aliases expected by downstream bundlers.
        material_pack.setdefault("selected_figures", list(material_pack.get("single_figure_cards", [])))
        material_pack.setdefault("selected_tables", list(material_pack.get("single_table_cards", [])))
        material_pack.setdefault(
            "selected_references",
            list(material_pack.get("reference_directory_with_original_markers", [])),
        )

        logger.info(">>> [E-Layer] 正在导出高清图表与表格证据...")
        refinement_result = e_layer.refine_multimodal_assets(material_pack, out_dir=out_dir, dpi=220)
        if isinstance(refinement_result, dict) and refinement_result.get("status") == "ok":
            material_pack["single_figure_cards"] = refinement_result.get(
                "single_figure_cards_refined",
                material_pack.get("single_figure_cards", []),
            )
            material_pack["single_table_cards"] = refinement_result.get(
                "single_table_cards_refined",
                material_pack.get("single_table_cards", []),
            )

        material_json = out_dir / "02_writing_material_pack.json"
        with open(material_json, 'w', encoding='utf-8') as f:
            json.dump(material_pack, f, ensure_ascii=False, indent=2, default=str)

        if observer: observer.on_phase_start("presentation", pipeline_id)
        logger.info(">>> [P-Layer] 正在生成 Word 报告...")
        docx_path = out_dir / f"{pipeline_id}_report.docx"
        p_layer.generate_docx_report(material_json, docx_path)
        if observer: observer.on_phase_success("presentation", pipeline_id, {"path": str(docx_path)})

        duration = (datetime.now() - start_time).total_seconds()
        logger.info("处理完成！耗时: %.2fs", duration)

        retrieval_payload = {
            "status": "hybrid_retrieval_ready",
            "focus_points": focus_points,
            "top_chunks": retrieval_results,
        }
        scoring_payload = {
            "scoring": scoring_results,
            "view": project_view,
        }
        
        if observer: observer.on_run_success(pipeline_id, {"duration": duration, "output": str(out_dir)})

        return {
            "status": "success",
            "output_dir": str(out_dir.resolve()),
            "docx": str(docx_path.resolve()),
            "material_pack": str(material_json.resolve()),
            "duration": duration,
            "artifacts": {
                "focus_points": list(focus_points),
                "retrieval_payload": _json_safe_copy(retrieval_payload),
                "scoring_payload": _json_safe_copy(scoring_payload),
                "analysis_payloads": [_json_safe_copy(scoring_payload)],
            },
        }
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
        logger.error("流水线执行失败: %s", e)
        if observer: 
            try:
                observer.on_run_error(pipeline_id, str(e), {"phase": "integrated_run"})
            except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                pass
        raise

def main():
    parser = argparse.ArgumentParser(description='文献处理器 - 模块化流水线总控')
    parser.add_argument('pdf', help='输入 PDF 文件路径')
    parser.add_argument('--goal', default='提取文献核心结论与实验数据', help='写作目标/关注点')
    parser.add_argument('--out', default='output', help='输出根目录')
    
    args = parser.parse_args()
    
    try:
        result = run_pipeline(args.pdf, args.goal, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
        logger.error("流水线执行失败: %s", e, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
