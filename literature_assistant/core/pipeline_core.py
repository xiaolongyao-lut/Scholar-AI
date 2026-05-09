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

from chunk_vector_store import batch_embed_texts
from project_paths import output_path
from runtime_env import resolve_embedding_config

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

# P3 因果推理层（可选，失败不阻断管线）
try:
    from layers.p3_causal_engine import CausalEngine
    _P3_AVAILABLE = True
except ImportError:
    _P3_AVAILABLE = False

# M-Layer 记忆层（可选）
try:
    from layers.m_layer_mempalace_memory import MempalaceAdapter
    _MEMPALACE_AVAILABLE = True
except ImportError:
    _MEMPALACE_AVAILABLE = False

# TOLF 撒饵捕鱼引擎（可选，失败不阻断管线）
try:
    from layers.tolf_engine import TOLFEngine
    import numpy as _np
    _TOLF_AVAILABLE = True
except ImportError:
    _TOLF_AVAILABLE = False

WINDOWS_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
MAX_SAFE_COMPONENT_LEN = 120

# 因果关系指示词（用于从 writing_point 提取三元组）
_CAUSAL_INDICATORS = re.compile(
    r'(导致|引起|促进|抑制|增强|降低|提高|改善|恶化|影响|决定|'
    r'causes?|leads?\s+to|results?\s+in|increases?|decreases?|enhances?|'
    r'inhibits?|improves?|affects?|determines?)',
    re.IGNORECASE
)

_MECHANISM_SPLITTERS = re.compile(
    r'(通过|由于|因为|使得|从而|进而|导致|引起|'
    r'through|due\s+to|because|thereby|resulting\s+in|leading\s+to)',
    re.IGNORECASE
)


def _extract_triplets_from_writing_points(writing_points: list[dict]) -> list[tuple[str, str, str]]:
    """从 G-Layer writing_points 中提取因果三元组 (subject, predicate, object)。

    策略：
    - result/mechanism 类型：基于因果指示词切分
    - 其他类型：基于句式结构提取
    - 保守提取：宁可少不可错
    """
    triplets = []
    for wp in writing_points:
        claim = wp.get("claim", "")
        p_type = wp.get("point_type", "")
        if not claim or len(claim) < 10:
            continue

        # 策略1：按因果指示词切分
        parts = _MECHANISM_SPLITTERS.split(claim, maxsplit=1)
        if len(parts) >= 3:
            subject = parts[0].strip().rstrip("，,。.")[:80]
            predicate = parts[1].strip()[:20]
            obj = parts[2].strip().rstrip("，,。.")[:80]
            if len(subject) > 3 and len(obj) > 3:
                triplets.append((subject, predicate, obj))
                continue

        # 策略2：按因果指示词定位
        match = _CAUSAL_INDICATORS.search(claim)
        if match:
            subject = claim[:match.start()].strip().rstrip("，,。.")[:80]
            predicate = match.group().strip()[:20]
            obj = claim[match.end():].strip().rstrip("，,。.")[:80]
            if len(subject) > 3 and len(obj) > 3:
                triplets.append((subject, predicate, obj))
                continue

        # 策略3：对 mechanism/result 类型，用 point_type 作为隐含谓词
        if p_type in ("mechanism", "result") and len(claim) > 20:
            mid = len(claim) // 2
            # 找最近的标点作为自然切分点
            for offset in range(min(20, mid)):
                for pos in (mid + offset, mid - offset):
                    if 0 < pos < len(claim) and claim[pos] in "，,;；":
                        subject = claim[:pos].strip()[:80]
                        obj = claim[pos + 1:].strip()[:80]
                        if len(subject) > 3 and len(obj) > 3:
                            pred = "causes" if p_type == "mechanism" else "produces"
                            triplets.append((subject, pred, obj))
                            break
                else:
                    continue
                break

    return triplets


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

def run_pipeline(
    pdf_path: str,
    goal: str,
    output_dir: str | None = None,
    observer: Optional[PipelineObserver] = None,
):
    pdf_path = Path(pdf_path)
    pipeline_id = sanitize_path_component(pdf_path.stem)
    out_dir = Path(output_dir or output_path()) / pipeline_id
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

        # --- P3: 因果推理引擎 ---
        causal_dag = None
        if _P3_AVAILABLE:
            try:
                if observer: observer.on_phase_start("causal_reasoning", pipeline_id)
                logger.info(">>> [P3-Layer] 正在提取因果推理链...")
                wp_list = scoring_results.get("writing_points", [])
                triplets = _extract_triplets_from_writing_points(wp_list)
                if triplets:
                    engine = CausalEngine(max_depth=6)
                    chains = engine.extract_chains(triplets)
                    causal_dag = engine.build_inference_dag(chains)
                    causal_dag["triplet_count"] = len(triplets)
                    causal_dag["chain_count"] = len(chains)
                    # 持久化因果图
                    causal_json = out_dir / "04_causal_dag.json"
                    with open(causal_json, 'w', encoding='utf-8') as f:
                        json.dump(causal_dag, f, ensure_ascii=False, indent=2, default=str)
                    logger.info(">>> [P3-Layer] 因果推理完成: %d 三元组 → %d 链路", len(triplets), len(chains))
                else:
                    logger.info(">>> [P3-Layer] 未提取到因果三元组，跳过因果推理")
                if observer: observer.on_phase_success("causal_reasoning", pipeline_id, {
                    "triplet_count": len(triplets), "chain_count": len(chains) if triplets else 0
                })
            except Exception as e:
                logger.warning(">>> [P3-Layer] 因果推理出错（不阻断管线）: %s", e)
                if observer: observer.on_phase_success("causal_reasoning", pipeline_id, {"skipped": True, "reason": str(e)})

        # --- TOLF: 撒饵捕鱼算法（可选，embedding 驱动的文献精准捕捞）---
        tolf_fish = []
        if _TOLF_AVAILABLE:
            try:
                if observer: observer.on_phase_start("tolf", pipeline_id)
                logger.info(">>> [TOLF] 正在执行撒饵捕鱼算法...")
                _chunks = raw_extract.get("chunks", [])
                if len(_chunks) >= 3:
                    _api_key, _base_url, _emb_model = resolve_embedding_config(
                        default_base_url="https://api.siliconflow.cn/v1",
                        default_model="BAAI/bge-large-zh-v1.5",
                        probe_candidates=False,
                    )
                    if _api_key:
                        # 提取 chunk 文本（最多 200 个块）；具体 batching / token guard 交给成熟 embedding 栈
                        _MAX_TOLF_CHUNKS = 200
                        _tolf_chunks = _chunks[:_MAX_TOLF_CHUNKS]
                        _texts = [
                            str(c.get("content") or c.get("claim") or c.get("text") or "")
                            for c in _tolf_chunks
                        ]

                        # 生成 aspect query embeddings（4 个）
                        _engine = TOLFEngine()
                        _aspect_q = _engine.generate_aspect_queries(goal)
                        _aspect_texts = list(_aspect_q.values())  # K/S/R/V

                        # 批量调用成熟 embedding 栈（provider-aware batching / token guard / failover）
                        _all_texts = _texts + _aspect_texts
                        _all_embs = _resolve_maybe_awaitable(
                            batch_embed_texts(
                                _all_texts,
                                api_key=_api_key,
                                base_url=_base_url,
                                model=_emb_model,
                                stage="tolf",
                            )
                        )

                        _chunk_embs = _np.array(_all_embs[:len(_texts)], dtype=_np.float32)
                        _aspect_embs = _np.array(_all_embs[len(_texts):], dtype=_np.float32)

                        # 执行 TOLF
                        _fish_results = _engine.run(
                            goal, _tolf_chunks, _chunk_embs, _aspect_embs
                        )
                        tolf_fish = [
                            {
                                "chunk_id": r.chunk_id,
                                "activation_score": round(r.activation_score, 4),
                                "evidence_score": round(r.evidence_score, 4),
                                "point_type": r.point_type,
                                "in_convex_hull": r.in_convex_hull,
                                "content": r.content[:300],
                            }
                            for r in _fish_results
                        ]
                        logger.info(">>> [TOLF] 捕捞完成: %d 个命中块", len(tolf_fish))
                        if observer: observer.on_phase_success("tolf", pipeline_id, {"fish_count": len(tolf_fish)})
                    else:
                        logger.info(">>> [TOLF] 未配置 API Key，跳过捕鱼算法")
                        if observer: observer.on_phase_success("tolf", pipeline_id, {"skipped": True, "reason": "no_api_key"})
                else:
                    logger.info(">>> [TOLF] chunk 数量不足（%d），跳过捕鱼算法", len(_chunks))
                    if observer: observer.on_phase_success("tolf", pipeline_id, {"skipped": True, "reason": "too_few_chunks"})
            except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as _e:
                logger.warning(">>> [TOLF] 撒饵捕鱼出错（不阻断管线）: %s", _e)
                if observer:
                    try:
                        observer.on_phase_success("tolf", pipeline_id, {"skipped": True, "reason": str(_e)})
                    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                        pass

        logger.info(">>> [K-Layer] 正在构建写作材料包...")
        material_pack = build_material_pack(scoring_results, bound_contract)
        material_pack.setdefault("paper_title", pdf_path.stem)
        material_pack.setdefault("schema_version", "v3.academic-synthesis")
        material_pack.setdefault("source_pdf", str(pdf_path.resolve()))
        material_pack.setdefault("goal", goal)
        material_pack["pipeline_id"] = pipeline_id
        material_pack["llm_status"] = scoring_results.get("llm_status", getattr(scorer, "llm_status", "unknown"))
        if causal_dag:
            material_pack["causal_dag"] = causal_dag
        if tolf_fish:
            material_pack["tolf_fish"] = tolf_fish

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

        # --- M-Layer: 记忆入库（可选，不阻断管线） ---
        memory_status = "skipped"
        if _MEMPALACE_AVAILABLE:
            try:
                logger.info(">>> [M-Layer] 正在将知识存入记忆宫殿...")
                mem = MempalaceAdapter()
                if mem.is_enabled():
                    wp_list = scoring_results.get("writing_points", [])
                    stored_count = 0
                    for wp in wp_list:
                        claim = wp.get("claim", "")
                        if not claim or len(claim) < 10:
                            continue
                        content = (
                            f"[{wp.get('point_type', 'claim')}] {claim}\n"
                            f"来源: {pdf_path.stem} (p.{wp.get('page', '?')})\n"
                            f"相关度: {wp.get('relevance_score', 0):.2f}"
                        )
                        mem.add_memory(
                            wing="literature",
                            room=goal or "general",
                            content=content,
                            source_file=str(pdf_path),
                            metadata={
                                "paper_title": pdf_path.stem,
                                "pipeline_id": pipeline_id,
                                "writing_point_id": wp.get("writing_point_id", ""),
                                "point_type": wp.get("point_type", ""),
                                "relevance_score": wp.get("relevance_score", 0),
                            },
                        )
                        stored_count += 1
                    # 存入因果关系
                    if causal_dag:
                        for link in causal_dag.get("links", []):
                            content = (
                                f"[causal] {link['source']} --{link.get('relation', '→')}--> {link['target']}\n"
                                f"置信度: {link.get('confidence', 0):.2f}\n"
                                f"来源: {pdf_path.stem}"
                            )
                            mem.add_memory(
                                wing="literature",
                                room=goal or "general",
                                content=content,
                                source_file=str(pdf_path),
                                metadata={
                                    "paper_title": pdf_path.stem,
                                    "pipeline_id": pipeline_id,
                                    "fact_type": "causal_relation",
                                    "source_entity": link["source"],
                                    "target_entity": link["target"],
                                    "relation": link.get("relation", ""),
                                },
                            )
                            stored_count += 1
                    memory_status = f"stored_{stored_count}"
                    logger.info(">>> [M-Layer] 记忆入库完成: %d 条知识", stored_count)
                else:
                    memory_status = "disabled"
            except Exception as e:
                logger.warning(">>> [M-Layer] 记忆入库出错（不阻断管线）: %s", e)
                memory_status = f"error: {e}"

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
                "causal_dag": _json_safe_copy(causal_dag) if causal_dag else None,
                "tolf_fish": _json_safe_copy(tolf_fish) if tolf_fish else [],
            },
            "memory_status": memory_status,
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
    parser.add_argument('--out', default=str(output_path()), help='输出根目录')
    
    args = parser.parse_args()
    
    try:
        result = run_pipeline(args.pdf, args.goal, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
        logger.error("流水线执行失败: %s", e, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
