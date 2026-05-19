# -*- coding: utf-8 -*-
"""
Main RAG Workflow (Sprint 3)
Role: 连接 SemanticRouter → RAG-Anything 混合检索 → LLM 生成

架构：
  用户输入
    ↓
  SemanticRouter (语义收束)
    ↓
  增强查询词构造
    ↓
  RAG-Anything 混合检索
    ↓
  LLM 生成 (带防卡死机制)
    ↓
  最终答案

注意：这是 Sprint 3 的框架，实际集成待后续实现。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入适配层
from runtime_env import env_value, resolve_embedding_config, resolve_llm_config, wiki_first_retrieval_enabled

DEFAULT_LLM_BASE_URL = env_value("ARK_BASE_URL", "OPENAI_BASE_URL", "BASE_URL", default="https://ark.cn-beijing.volces.com/api/v3")
DEFAULT_LLM_MODEL = env_value("ARK_MODEL", "OPENAI_MODEL", "MODEL", default="ep-your-ark-endpoint")
LEGACY_LLM_API_ENV_NAMES = ("SILICONFLOW_API_KEY",)
from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter
from layers.r_layer_hybrid_retriever import hybrid_search
from evidence_packer import EvidenceReference, _token_set, build_evidence_references, format_evidence_item, pack_evidence
from model_call_gateway import gated_call, _compute_corpus_version
from query_expander import decompose_query_async
from retrieval_provenance import attach_source_labels, merge_source_labels
from llm_defaults import resolve_llm_params
from project_paths import output_path, wiki_generated_root, wiki_query_index_path

# Sprint 4: 高级缓存与路由
from semantic_cache import SemanticCache
from model_router import get_router
from conversation_manager import get_conv_manager
from citation_auditor import get_auditor # 新增
from prompts.identity_renderer import render_identity_header  # 2026-05-18 identity injection plan

try:
    from literature_assistant.core.wiki.page_store import WikiPageStore
    from literature_assistant.core.wiki.query import (
        WikiContextPack,
        WikiQueryIndex,
        WikiQueryResult,
        build_query_trace,
        build_wiki_index,
        render_context_pack,
        wiki_query_with_fallback,
        write_query_trace,
    )
except Exception:  # pragma: no cover - wiki integration remains default-off.
    WikiContextPack = None  # type: ignore[assignment]
    WikiPageStore = None  # type: ignore[assignment]
    WikiQueryIndex = None  # type: ignore[assignment]
    WikiQueryResult = None  # type: ignore[assignment]
    build_query_trace = None  # type: ignore[assignment]
    build_wiki_index = None  # type: ignore[assignment]
    render_context_pack = None  # type: ignore[assignment]
    wiki_query_with_fallback = None  # type: ignore[assignment]
    write_query_trace = None  # type: ignore[assignment]


@dataclass
class RAGResult:
    """RAG 查询结果数据类"""
    query: str
    focused_points: List[str]
    memory_hits: List[Dict[str, Any]]
    rag_evidence: List[Dict[str, Any]]
    generated_answer: str
    confidence_score: float
    trace: Dict[str, Any]
    association_bundle: Optional[Dict[str, Any]] = None
    evidence_refs: List[EvidenceReference] = field(default_factory=list)


# Sprint 4: Unified Generation Prompt Template (Centralized for DoD Audits)
def load_prompt_template(name: str) -> str:
    template_path = Path(__file__).parent / "prompt_templates" / f"{name}.txt"
    try:
        return template_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning(f"Failed to load prompt template {name}, falling back to built-in. Error: {e}")
        return "You are a technical assistant. Answer based on context."

GENERATION_PROMPT_TEMPLATE = load_prompt_template("generation")
class RAGWorkflow:
    """
    完整的 RAG 工作流：
    1. 输入用户问题
    2. 通过 SemanticRouter 收束到关注点
    3. 构建增强查询词
    4. 调用 RAG-Anything 混合检索
    5. 用大模型生成答案
    """
    
    def __init__(
        self,
        semantic_router: Any,  # SemanticRouter 实例
        ragflow_adapter: Optional[RAGFlowAdapter] = None,  # RAGFlow 适配器
        local_data: Optional[Dict[str, Any]] = None,  # 本地兜底数据 (raw_extract)
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_LLM_BASE_URL,
        model: str = DEFAULT_LLM_MODEL,
        llm_client: Optional[Any] = None,
        enable_requests_fallback: bool = True,
        memory_adapter: Optional[Any] = None,
        memory_wing: Optional[str] = None,
        association_ai_adapter: Optional[Any] = None,
    ):
        """
        初始化 RAG 工作流
        
        Args:
            semantic_router: SemanticRouter 实例
            ragflow_adapter: RAGFlowAdapter 实例
            local_data: 本地混合检索的兜底数据
            api_key: 聊天模型 API key，优先支持 ARK_API_KEY，兼容旧的 SILICONFLOW_API_KEY
            base_url: API 基础 URL
            model: LLM 模型名称
            llm_client: 可注入的异步 LLM 客户端（测试或外部管理连接时使用）
            enable_requests_fallback: 当异步客户端失败时，是否允许回退到 requests
        """
        self.router = semantic_router
        self.rag_adapter = ragflow_adapter
        self.local_data = local_data
        self.api_key, self.base_url, self.model = resolve_llm_config(
            api_key,
            base_url=base_url,
            model=model,
            default_base_url=DEFAULT_LLM_BASE_URL,
            default_model=DEFAULT_LLM_MODEL,
        )
        if not self.api_key:
            for legacy_env_name in LEGACY_LLM_API_ENV_NAMES:
                legacy_value = env_value(legacy_env_name)
                if legacy_value:
                    self.api_key = legacy_value
                    break
        self.enable_requests_fallback = enable_requests_fallback
        self._owns_llm_client = llm_client is None
        self._memory_adapter = memory_adapter
        self._memory_adapter_resolved = memory_adapter is not None
        self._memory_wing = memory_wing
        self._association_ai_adapter = association_ai_adapter
        self._association_ai_adapter_resolved = association_ai_adapter is not None

        # Sprint 4: 初始化高级组件
        self.semantic_cache = SemanticCache(threshold=0.985)
        self.model_router = get_router(
            cheap=str(env_value("ARK_MODEL_CHEAP", default="ep-20260414011719-8x7s4")),
            strong=str(env_value("ARK_MODEL_STRONG", default="ep-20260414011719-8x7s4"))
        )
        self.conv_manager = get_conv_manager()
        self.citation_auditor = get_auditor() # 新增
        
        # 如果未传入适配器但有环境变量，则尝试自动初始化
        if not self.rag_adapter and env_value('RAGFLOW_API_KEY'):
            self.rag_adapter = RAGFlowAdapter(
                api_key=env_value('RAGFLOW_API_KEY'),
                base_url=env_value('RAGFLOW_BASE_URL', default='https://localhost:9380')
            )

        # 防卡死 HTTP 客户端
        if llm_client is not None:
            self.client = llm_client
        elif httpx:
            self.client = httpx.AsyncClient(
                timeout=60.0,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2)
            )
        else:
            logger.warning("httpx 未安装，LLM 调用功能不可用")
            self.client = None

    def _invoke_generation_once(
        self,
        *,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None

        if self.client:
            try:
                response = self.client.post(endpoint, headers=headers, json=payload)
                if inspect.isawaitable(response):
                    response = asyncio.run(response)
                return self._extract_generation_content(response)
            except Exception as exc:
                last_error = exc
                logger.error("LLM API (client) 异常: %s", exc)

        if self.enable_requests_fallback and httpx:
            try:
                with httpx.Client(timeout=60.0) as fallback_client:
                    response = fallback_client.post(endpoint, headers=headers, json=payload)
                return self._extract_generation_content(response)
            except Exception as exc:
                last_error = exc
                logger.error("LLM API (sync fallback) 失败: %s", exc)

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM client unavailable")

    @staticmethod
    def _extract_generation_content(response: Any) -> str:
        status_code = getattr(response, "status_code", 200)
        if int(status_code) != 200:
            raise RuntimeError(f"LLM API failed: {status_code}")

        data = response.json() if hasattr(response, "json") else response
        if not isinstance(data, dict):
            raise TypeError("LLM response payload must be a dict")

        return str(data["choices"][0]["message"]["content"])

    async def _build_semantic_cache_query_vector(self, user_query: str) -> Optional[np.ndarray]:
        """Return an optional semantic-cache vector without blocking local RAG.

        Why:
            Project-local chat may not have a remote RAGFlow adapter. Semantic
            cache is an optimization, so missing embedding support must not
            prevent the retrieve-then-generate path from running.
        """
        if self.rag_adapter is None or not hasattr(self.rag_adapter, "_embed_query"):
            return None

        embedding_params = resolve_llm_params("embedding")
        try:
            query_vec_list = await asyncio.to_thread(
                gated_call,
                kind="embedding",
                cache_key_parts={
                    "model": embedding_params.get("model", "BAAI/bge-m3"),
                    "prompt_hash": sha256(user_query.encode("utf-8")).hexdigest(),
                    "task": "semantic_cache_lookup",
                },
                payload={"input": [user_query]},
                invoke=lambda: self.rag_adapter._embed_query(user_query),
                validate_result=lambda value: isinstance(value, list) and len(value) > 0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Semantic cache lookup skipped: %s", exc)
            return None

        return np.array(query_vec_list) if query_vec_list else None

    def _resolve_corpus_version(self, project_id: str = "target_project") -> str:
        """Return a corpus fingerprint for cache scoping.

        Args:
            project_id: Best-effort project identifier for manifest-backed
                corpora. Local in-memory corpora fall back to a deterministic
                hash of ``self.local_data``.
        """
        if self.local_data:
            material = json.dumps(
                self.local_data,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            return sha256(material.encode("utf-8")).hexdigest()
        try:
            return _compute_corpus_version(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.info("Corpus version fallback used: %s", exc)
            return "unknown-corpus"
    
    async def ask_my_literature(
        self,
        user_query: str,
        top_k_points: int = 3,
        top_k_evidence: int = 5,
        dataset_ids: Optional[List[str]] = None,
        include_association: bool = False,
        association_mode: str = "no_ai",
        association_project_id: Optional[str] = None,
        association_draft_id: Optional[str] = None,
        association_section_id: Optional[str] = None,
    ) -> RAGResult:
        """
        完整的查询流程 (Sprint 4: 整合语义缓存与模型路由)
        """
        trace = {
            'step_0_memory': None,
            'step_1_routing': None,
            'step_2_rag_search': None,
            'step_3_generation': None,
            'step_4_association': None,
        }

        try:
            # ========================================
            # Sprint 4: 语义缓存预检 (Semantic Cache Bypass)
            # ========================================
            current_query_vec = await self._build_semantic_cache_query_vector(user_query)
            corpus_version = self._resolve_corpus_version(
                association_project_id or os.environ.get("RAG_PROJECT_ID", "target_project")
            )

            # --- 加载会话历史 (FR-3 Resume) ---
            session_id = os.environ.get("RAG_SESSION_ID", "default_session")
            self.conv_manager.resume_session(session_id)

            if current_query_vec is not None:
                cached_answer = self.semantic_cache.lookup(
                    query_vec=current_query_vec,
                    corpus_hash=corpus_version,
                    model_id=self.model
                )
                if cached_answer:
                    logger.info("⚡ 语义缓存命中，秒级返回 (Cost = 0)")
                    try:
                        data = json.loads(cached_answer)
                        return RAGResult(
                            query=user_query,
                            focused_points=["cached"],
                            memory_hits=[],
                            rag_evidence=[],
                            evidence_refs=[],
                            generated_answer=data.get("conclusion", "Cached Answer"),
                            confidence_score=float(data.get("overall_score") or 1.0),
                            trace={"cache": "hit_semantic"},
                            association_bundle=None
                        )
                    except: pass

            # ========================================
            # 第 1 步：语义收束与逻辑拆解 (借鉴 sa-rag)
            # ========================================
            logger.info(f"[Step 1] 语义收束与拆解: {user_query}")

            # 同时进行语义路由和逻辑拆解
            focused_points_task = self.router.route_query(user_query, top_k=top_k_points)
            decomposed_tasks_task = decompose_query_async(
                user_query,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model
            )

            focused_points, decomposed_tasks = await asyncio.gather(
                focused_points_task,
                decomposed_tasks_task
            )

            trace['step_1_routing'] = {
                'user_query': user_query,
                'focused_points': focused_points,
                'decomposed_tasks': decomposed_tasks,
                'routing_success': bool(focused_points)
            }

            logger.info(f"✓ 识别关注点: {focused_points}")
            if len(decomposed_tasks) > 1:
                logger.info(f"✓ 逻辑拆解为 {len(decomposed_tasks)} 个子任务")

            # ========================================
            # 第 1.5 步：长期记忆检索（可选）
            # ========================================
            memory_hits = self._retrieve_memory_hits(
                user_query=user_query,
                focused_points=focused_points,
            )
            trace['step_0_memory'] = {
                'memory_hit_count': len(memory_hits),
                'memory_enabled': bool(self._resolve_memory_adapter()),
                'memory_wing': self._memory_wing,
            }
            if memory_hits:
                logger.info(f"✓ 命中 {len(memory_hits)} 条 MemPalace 长期记忆")
            
            # ========================================
            # 第 2 步：构建增强查询词
            # ========================================
            logger.info("[Step 2] 构建增强查询词")
            
            enhanced_query = self._build_enhanced_query(
                user_query,
                focused_points
            )
            
            logger.info(f"增强查询: {enhanced_query[:100]}...")
            
            # ========================================
            # 第 3 步：RAG 混合检索 (RAGFlow 优先 + 本地兜底)
            # ========================================
            logger.info("[Step 3] RAG 混合检索")

            wiki_evidence, wiki_trace = self._try_wiki_first_retrieval(
                user_query=user_query,
                top_k=top_k_evidence,
            )
            if wiki_trace:
                trace["step_2_wiki_first"] = wiki_trace

            if wiki_evidence:
                rag_evidence = wiki_evidence
                logger.info("✓ Wiki-first 检索命中 %s 个上下文片段", len(rag_evidence))
            else:
                rag_evidence = await self._rag_search(
                    enhanced_query,
                    top_k=top_k_evidence,
                    dataset_ids=dataset_ids
                )
            
            trace['step_2_rag_search'] = {
                'enhanced_query': enhanced_query,
                'evidence_count': len(rag_evidence),
                'rag_search_success': bool(rag_evidence),
                'source': 'wiki_first' if wiki_evidence else 'raw_rag',
            }
            
            logger.info(f"✓ 检索到 {len(rag_evidence)} 个证据")
            
            # ========================================
            # 第 4 步：LLM 生成答案
            # ========================================
            logger.info("[Step 4] LLM 生成答案")
            
            generated_answer = await self._generate_answer(
                user_query,
                focused_points,
                rag_evidence,
                memory_hits,
            )
            evidence_refs = self._build_generation_evidence_refs(rag_evidence, query=user_query)
            
            trace['step_3_generation'] = {
                'answer_length': len(generated_answer),
                'generation_success': bool(generated_answer),
                'evidence_ref_count': len(evidence_refs),
            }
            
            logger.info(f"✓ 生成答案 ({len(generated_answer)} 字)")

            association_bundle = None
            if include_association:
                logger.info("[Step 5] 构建联想写作 Bundle")
                association_bundle = await self._build_association_bundle(
                    user_query=user_query,
                    focused_points=focused_points,
                    rag_evidence=rag_evidence,
                    memory_hits=memory_hits,
                    generated_answer=generated_answer,
                    mode=association_mode,
                    project_id=association_project_id,
                    draft_id=association_draft_id,
                    section_id=association_section_id,
                    analysis_payloads=self._collect_workflow_analysis_payloads(
                        user_query=user_query,
                        focused_points=focused_points,
                        generated_answer=generated_answer,
                        association_mode=association_mode,
                    ),
                )
                trace['step_4_association'] = {
                    'enabled': True,
                    'mode': association_mode,
                    'available': bool(association_bundle),
                    'project_id': association_bundle.get('project_id') if association_bundle else association_project_id,
                    'signal_count': len(association_bundle.get('related_signals', [])) if association_bundle else 0,
                    'ai_enhanced': bool(association_bundle.get('ai_enhanced')) if association_bundle else False,
                }
            else:
                trace['step_4_association'] = {
                    'enabled': False,
                    'mode': association_mode,
                    'available': False,
                }
            
            # ========================================
            # 组织最终结果
            # ========================================
            result = RAGResult(
                query=user_query,
                focused_points=focused_points,
                memory_hits=memory_hits,
                rag_evidence=rag_evidence,
                evidence_refs=evidence_refs,
                generated_answer=generated_answer,
                confidence_score=self._calculate_confidence(
                    focused_points, rag_evidence, generated_answer
                ),
                trace=trace,
                association_bundle=association_bundle,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"工作流执行失败: {e}", exc_info=True)
            
            # 返回包含错误信息的结果
            return RAGResult(
                query=user_query,
                focused_points=[],
                memory_hits=[],
                rag_evidence=[],
                evidence_refs=[],
                generated_answer=f"发生错误: {str(e)}",
                confidence_score=0.0,
                trace={'error': str(e), **trace},
                association_bundle=None,
            )
    
    def _build_enhanced_query(
        self,
        user_query: str,
        focused_points: List[str]
    ) -> str:
        """
        构建增强查询词
        
        原始：用户的自然语言问题
        增强：加入语义收束的关注点，提高检索精度
        """
        if not focused_points:
            return user_query
        
        points_str = '、'.join(focused_points)
        enhanced = (
            f"请基于以下研究重点: [{points_str}]\n"
            f"来回答这个问题: {user_query}"
        )
        
        return enhanced

    def _try_wiki_first_retrieval(
        self,
        *,
        user_query: str,
        top_k: int,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
        """Return wiki evidence when default-off wiki-first retrieval is enabled.

        The branch never raises and never replaces raw RAG fallback when the wiki
        index is absent, empty, stale, or budget-constrained.
        """
        if not wiki_first_retrieval_enabled():
            return [], None
        if not user_query or not user_query.strip():
            return [], None
        if (
            WikiPageStore is None
            or WikiQueryIndex is None
            or build_wiki_index is None
            or wiki_query_with_fallback is None
            or render_context_pack is None
            or build_query_trace is None
        ):
            return [], {
                "enabled": True,
                "fallback_used": True,
                "fallback_reason": "wiki integration imports unavailable",
            }

        try:
            page_store = WikiPageStore(wiki_generated_root())
            index = WikiQueryIndex(wiki_query_index_path())
            build_wiki_index(page_store, index)
            query_result = wiki_query_with_fallback(
                user_query,
                index,
                page_store,
                enabled=True,
                limit=max(1, top_k),
                expand_links=True,
                max_linked=max(1, min(3, top_k)),
            )
            context_pack = (
                render_context_pack(
                    user_query,
                    query_result,
                    page_store,
                    max_tokens=max(512, int(os.environ.get("WIKI_CONTEXT_PACK_MAX_TOKENS", "4000"))),
                )
                if not query_result.fallback_used
                else None
            )
            query_trace = build_query_trace(
                user_query,
                query_result,
                context_pack,
                enabled=True,
            )
            trace_path = write_query_trace(query_trace) if write_query_trace is not None else None
            trace_payload: Dict[str, Any] = {
                "enabled": True,
                "wiki_hits": len(query_result.wiki_hits),
                "linked_hits": len(query_result.linked_hits),
                "fallback_used": query_result.fallback_used,
                "fallback_reason": query_result.fallback_reason,
                "context_tokens": query_trace.context_tokens,
                "context_max_tokens": query_trace.context_max_tokens,
                "context_truncated": query_trace.context_truncated,
                "omitted_pages": query_trace.omitted_pages,
                "trace_path": str(trace_path) if trace_path else None,
            }
            if query_result.fallback_used or context_pack is None:
                return [], trace_payload
            evidence = self._wiki_context_pack_to_evidence(context_pack, query_result)
            if not evidence:
                trace_payload["fallback_used"] = True
                trace_payload["fallback_reason"] = "wiki context pack empty"
                return [], trace_payload
            return evidence[:top_k], trace_payload
        except Exception as exc:  # noqa: BLE001
            logger.info("Wiki-first retrieval skipped: %s", exc)
            return [], {
                "enabled": True,
                "fallback_used": True,
                "fallback_reason": f"wiki retrieval error: {exc}",
            }

    def _wiki_context_pack_to_evidence(
        self,
        context_pack: Any,
        query_result: Any,
    ) -> List[Dict[str, Any]]:
        """Convert wiki context pages into RAG evidence-shaped dictionaries."""
        evidence: List[Dict[str, Any]] = []
        packed_pages = list(getattr(context_pack, "primary_pages", [])) + list(
            getattr(context_pack, "linked_pages", [])
        )
        hits = list(getattr(query_result, "wiki_hits", [])) + list(getattr(query_result, "linked_hits", []))
        for idx, page_text in enumerate(packed_pages):
            if not isinstance(page_text, str) or not page_text.strip():
                continue
            hit = hits[idx] if idx < len(hits) else None
            page_path = getattr(hit, "page_path", Path(f"wiki-page-{idx}.md"))
            page_title = str(getattr(hit, "title", page_path.stem if isinstance(page_path, Path) else "Wiki Page"))
            page_path_text = page_path.as_posix() if isinstance(page_path, Path) else str(page_path)
            chunk_digest = sha256(f"wiki:{page_path_text}:{idx}".encode("utf-8")).hexdigest()[:16]
            score = float(getattr(hit, "score", 0.0) or 0.0)
            source_label = str(getattr(hit, "source", "wiki_first") or "wiki_first")
            evidence.append(
                attach_source_labels(
                    {
                        "chunk_id": f"wiki-{chunk_digest}",
                        "material_id": page_path_text,
                        "text": page_text.strip(),
                        "source": page_path_text,
                        "score": score,
                        "label": page_title,
                        "metadata": {
                            "type": "wiki_first",
                            "title": page_title,
                            "source_labels": ["wiki_first", source_label],
                            "source_hint": f"wiki_first+{source_label}",
                        },
                    },
                    ["wiki_first", source_label],
                    source_hint=f"wiki_first+{source_label}",
                )
            )
        return evidence
    
    async def _rag_search(
        self,
        enhanced_query: str,
        top_k: int = 5,
        dataset_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        核心检索逻辑：
        1. 尝试使用 RAGFlowAdapter 检索远程数据集
        2. 如果失败或未配置，回退到本地 hybrid_search 检索 local_data
        """
        results = []
        
        # 策略 1: RAGFlow 检索
        if self.rag_adapter and dataset_ids:
            try:
                logger.info(f"尝试 RAGFlow 检索 (datasets: {dataset_ids})")
                results = self.rag_adapter.retrieve(
                    question=enhanced_query,
                    dataset_ids=dataset_ids,
                    top_k=top_k
                )
                if results:
                    logger.info(f"✓ RAGFlow 检索成功，获取 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.error(f"RAGFlow 检索异常: {e}，准备进入兜底逻辑")

        # 策略 2: 本地混合检索兜底
        if self.local_data:
            try:
                logger.info("尝试本地混合检索兜底 (BM25 + Overlap + Rerank)")
                # P1: hybrid_search 现在是异步的
                local_results = await hybrid_search(
                    raw_extract=self.local_data,
                    query=enhanced_query,
                    top_k=top_k
                )
                # 对齐字段格式
                for res in local_results:
                    local_text = (
                        res.get("text")
                        or res.get("claim")
                        or res.get("content")
                        or res.get("source_text")
                        or ""
                    )
                    score = res.get("rerank_score", res.get("hybrid_score", 0.0))
                    source_labels = merge_source_labels(res.get("source_labels"), "local_fallback")
                    source_hint = str(res.get("source_hint") or "+".join(source_labels)).strip()
                    metadata = {
                        "type": "local_fallback",
                        "source_labels": source_labels,
                        "source_hint": source_hint,
                    }
                    for key in ("hybrid_score", "dense_score", "graph_score", "rrf_score", "rerank_score", "rerank_model", "rerank_source", "warning"):
                        if key in res:
                            metadata[key] = res.get(key)
                    if "rerank_fallback" in res:
                        metadata["rerank_fallback"] = bool(res.get("rerank_fallback"))

                    aligned = attach_source_labels({
                        "text": local_text,
                        "source": res.get("source", "local_file"),
                        "score": score,
                        "metadata": metadata,
                    }, source_labels, source_hint=source_hint)
                    for key in ("chunk_id", "material_id", "page", "rerank_score", "rerank_model", "rerank_source", "warning"):
                        if res.get(key) is not None:
                            aligned[key] = res.get(key)
                    if "rerank_fallback" in res:
                        aligned["rerank_fallback"] = bool(res.get("rerank_fallback"))

                    results.append({
                        **aligned,
                    })
                
                if results:
                    logger.info(f"✓ 本地劫持/兜底检索成功，获取 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.error(f"本地兜底检索失败: {e}")

        # 策略 3: 最终回退（空结果）
        logger.warning("所有检索策略均未命中，返回空列表")
        return []

    def _pack_generation_evidence(
        self,
        rag_evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Pack retrieved evidence for generation and machine-readable artifacts.

        Args:
            rag_evidence: Retrieval hits represented as dictionaries. The list is
                never mutated; malformed callers fail early so provenance output
                cannot silently diverge from the answer prompt.

        Returns:
            Evidence candidates after token budget, per-material, and top-k
            constraints are applied.
        """
        if not isinstance(rag_evidence, list):
            raise TypeError("rag_evidence must be a list")

        evidence_budget = max(1, int(os.environ.get("EVIDENCE_TOKEN_BUDGET", "4000")))
        evidence_hard_cap = max(
            evidence_budget,
            int(os.environ.get("EVIDENCE_TOKEN_HARD_CAP", "5000")),
        )
        evidence_top_k = max(1, int(os.environ.get("EVIDENCE_PACK_TOP_K", "5")))
        evidence_max_per_material = max(
            1,
            int(os.environ.get("EVIDENCE_MAX_PER_MATERIAL", "2")),
        )
        return pack_evidence(
            rag_evidence,
            budget_tokens=evidence_budget,
            hard_cap_tokens=evidence_hard_cap,
            max_per_material=evidence_max_per_material,
            top_k=evidence_top_k,
        )

    def _build_generation_evidence_refs(
        self,
        rag_evidence: List[Dict[str, Any]],
        query: str = "",
    ) -> List[EvidenceReference]:
        """Return the evidence references that match the generation context."""
        query_tokens = _token_set(query) if query else None
        return build_evidence_references(
            self._pack_generation_evidence(rag_evidence),
            query_tokens=query_tokens,
        )

    async def _generate_answer(
        self,
        user_query: str,
        focused_points: List[str],
        rag_evidence: List[Dict[str, Any]],
        memory_hits: List[Dict[str, Any]],
    ) -> str:
        """
        调用大模型生成最终答案

        输入：用户问题 + 关注点 + RAG 证据
        输出：学术性的综合回答
        """
        packed_evidence = self._pack_generation_evidence(rag_evidence)

        # ------------------------------------------------------------------
        # Sprint 4: 冲突决策逻辑 (Conflict Detection)
        # ------------------------------------------------------------------
        has_conflict = False
        conflict_keywords = ["然而", "反之", "矛盾", "不一致", "but", "however", "contrast", "conflict"]
        evidence_text_pool = " ".join([str(ev.get("text", "")) for ev in rag_evidence])

        for kw in conflict_keywords:
            if kw in evidence_text_pool:
                has_conflict = True
                break

        # 构造上下文
        context_str = "\n\n".join(
            format_evidence_item(ev, rank=idx)
            for idx, ev in enumerate(packed_evidence)
        )
        memory_str = "\n".join([
            (
                f"- [{hit.get('wing', 'unknown')}/{hit.get('room', 'unknown')}] "
                f"{hit.get('text', '').strip()[:120]}"
            )
            for hit in memory_hits[:3]
        ])
        
        # Sprint 4: 使用统一模板构造 Prompt，增强可审计性与测试稳定性
        _identity_header = render_identity_header(
            "generation",
            context={"session_id": os.environ.get("RAG_SESSION_ID", "default_session")},
        )
        prompt_body = GENERATION_PROMPT_TEMPLATE.format(
            user_query=user_query,
            focused_points_str=', '.join(focused_points),
            memory_str=memory_str if memory_str else '（无长期记忆命中）',
            context_str=context_str if context_str else '（无关联证据）'
        )
        prompt = f"{_identity_header}\n\n{prompt_body}" if _identity_header else prompt_body

        params = resolve_llm_params("generation")

                # Sprint 4: 模型路由决策
        current_model = self.model_router.route(user_query, focused_points)

        # --- 推理等级强制提升 (Sprint 4: Conflict Override) ---
        if has_conflict:
            logger.info("🧨 检测到检索证据中存在潜在冲突 -> 强制启用逻辑推理模型")
            current_model = str(os.getenv("ARK_MODEL_STRONG", current_model))

        # --- 核心改造：多轮对话状态恢复 (Resume - FR-3) ---
        session_id = os.environ.get("RAG_SESSION_ID", "default_session")
        history_events = self.conv_manager.resume_session(session_id)

        messages = [{"role": "system", "content": prompt}]

        # 2. 注入历史 Turn (如果存在)
        for evt in history_events[-6:]: # 仅取最近 3 轮 (6个事件)
            kind = evt.get("event_kind")
            payload = evt.get("payload", {})
            if kind == "user_message":
                messages.append({"role": "user", "content": payload.get("query", "")})
            elif kind == "assistant_message":
                messages.append({"role": "assistant", "content": payload.get("response", "")})

        # 3. 注入当前问题，系统消息已经携带本轮检索证据与 JSON 约束
        messages.append({"role": "user", "content": user_query})

        payload = {
            "model": current_model,
            "messages": messages,
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "max_tokens": params["max_tokens"],
        }
        if params.get("top_k"):
            payload["extra_body"] = {"top_k": params["top_k"]}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if not self.api_key:
            logger.warning("未配置 LLM API key，过答案生成")
            return "LLM 服务不可用"

        sampling_payload = {
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "max_tokens": params["max_tokens"],
            "top_k": params.get("top_k"),
        }

        try:
            answer_text = await asyncio.to_thread(
                gated_call,
                kind="llm",
                cache_key_parts={
                    "model": self.model,
                    "prompt_hash": sha256(prompt.encode("utf-8")).hexdigest(),
                    "sampling_params_hash": sha256(
                        json.dumps(
                            sampling_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    "task": "generation",
                },
                payload=payload,
                invoke=lambda: self._invoke_generation_once(payload=payload, headers=headers),
                validate_result=lambda value: isinstance(value, str),
            )

            # ------------------------------------------------------------------
            # 第 5 步：质量门控与结果后处理 (Sprint 4 Quality Gate)
            # ------------------------------------------------------------------
            try:
                # 清理可能的 Markdown 标记
                cleaned_answer = re.sub(r"```json\s*|\s*```", "", answer_text).strip()
                data = json.loads(cleaned_answer)
                status = data.get("status", "success")
                score = float(data.get("overall_score") or 0.0)
                limitations = data.get("limitations") or ""

                if status == "conflict":
                    logger.warning(f"质量门控: 检测到证据冲突 ({limitations})")
                    data["conclusion"] = f"【由于检索证据存在冲突，无法得出准确结论】{limitations}"
                elif status == "insufficient_data" and score < 0.3:
                    logger.warning(f"质量门控: 数据严重不足 (score={score})")
                    data["conclusion"] = "【检索到的数据量不足以支撑准确结论】"
                elif score < 0.5:
                    logger.info(f"质量门控: 置信度较低 (score={score})")
                    if not limitations.startswith("【置信度不足提醒】"):
                        data["limitations"] = f"【置信度不足提醒】{limitations}"

                # --- 关键注入：引用溯源审计 (Sprint 4) ---
                data, audit_passed = self.citation_auditor.audit(data, packed_evidence)
                if not audit_passed:
                    logger.warning("🚫 引用审计未通过，已在结果中标记审计警告")

                answer_text = json.dumps(data, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"质量门控: JSON 解析失败 ({e})，返回原始文本")

            # 记录历史事件 (Sprint 4)
            self.conv_manager.log_event(
                session_id=session_id,
                kind="assistant_message",
                payload={
                    "query": user_query,
                    "response": answer_text,
                    "chunk_ids": [str(ev.get("chunk_id")) for ev in packed_evidence],
                    "evidence_refs": build_evidence_references(packed_evidence, query_tokens=_token_set(user_query)),
                }
            )
            self._persist_last_answer(
                user_query=user_query,
                answer=answer_text,
                packed_evidence=packed_evidence,
                model=current_model,
            )

            return answer_text
        except Exception as exc:
            logger.error("LLM generation gateway failed: %s", exc)
            self._persist_last_answer(
                user_query=user_query,
                answer="",
                packed_evidence=packed_evidence,
                model=current_model,
                error=str(exc),
            )
            if self.enable_requests_fallback:
                return f"生成失败: {exc}"
            logger.warning("异步 LLM 客户端失败，且同步兜底已禁用")
            return "LLM 服务不可用"

    def _persist_last_answer(
        self,
        *,
        user_query: str,
        answer: str,
        packed_evidence: List[Dict[str, Any]],
        model: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Write the most recent generation to ``output/last_answer.json``.

        Used by DoD §3.8.4 grep-based citation audits and by the
        ``test_main_rag_workflow_citation`` regression. Never raises —
        persistence is best-effort and must not affect the response.
        """
        try:
            chunk_ids = [
                str(ev.get("chunk_id"))
                for ev in (packed_evidence or [])
                if ev.get("chunk_id")
            ]
            payload = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "model": model or self.model,
                "query": user_query,
                "answer": answer,
                "chunk_ids": chunk_ids,
                "evidence_refs": build_evidence_references(packed_evidence or [], query_tokens=_token_set(user_query)),
            }
            if error:
                payload["error"] = error
            out_dir = Path(os.environ.get("RAG_OUTPUT_DIR", str(output_path())))
            out_dir.mkdir(parents=True, exist_ok=True)

            out_file = out_dir / "last_answer.json"
            tmp_file = out_file.with_suffix(".json.tmp")
            tmp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_file, out_file)

            session_id = os.environ.get("RAG_SESSION_ID", "default_session")
            self.conv_manager.log_event(
                session_id=session_id,
                kind="last_answer_persisted",
                payload={
                    "query": user_query,
                    "chunk_ids": chunk_ids,
                    "evidence_refs": payload["evidence_refs"],
                    "model": payload["model"],
                    "status": "success" if not error else "failed",
                    "output_file": str(out_file),
                },
            )
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("persist last_answer.json failed: %s", exc)

    def _resolve_memory_adapter(self) -> Optional[Any]:
        """Resolve the optional MemPalace adapter lazily."""
        if self._memory_adapter_resolved:
            return self._memory_adapter

        self._memory_adapter_resolved = True
        try:
            from layers.m_layer_mempalace_memory import (
                MempalaceMemoryAdapter,
                load_mempalace_settings,
            )

            adapter = MempalaceMemoryAdapter(load_mempalace_settings())
            if adapter.is_enabled():
                self._memory_adapter = adapter
            else:
                self._memory_adapter = None
        except Exception as exc:  # pragma: no cover - optional integration path
            logger.warning("MemPalace adapter unavailable for RAG workflow: %s", exc)
            self._memory_adapter = None
        return self._memory_adapter

    def _resolve_association_ai_adapter(self) -> Optional[Any]:
        """Resolve the optional AI enhancer for association mode lazily."""
        if self._association_ai_adapter_resolved:
            return self._association_ai_adapter

        self._association_ai_adapter_resolved = True
        try:
            from layers.ai_adapter import AIAdapter

            self._association_ai_adapter = AIAdapter(
                api_key=env_value("ARK_API_KEY", "OPENAI_API_KEY", "SILICONFLOW_API_KEY"),
                base_url=env_value("ARK_BASE_URL", "OPENAI_BASE_URL"),
                model=env_value("ARK_MODEL", "OPENAI_MODEL"),
            )
        except Exception as exc:  # pragma: no cover - optional integration path
            logger.warning("Association AI adapter unavailable for workflow: %s", exc)
            self._association_ai_adapter = None
        return self._association_ai_adapter

    async def _build_association_bundle(
        self,
        user_query: str,
        focused_points: List[str],
        rag_evidence: List[Dict[str, Any]],
        memory_hits: List[Dict[str, Any]],
        generated_answer: str,
        mode: str,
        project_id: Optional[str],
        draft_id: Optional[str],
        section_id: Optional[str],
        analysis_payloads: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a writing association bundle from either project state or ephemeral context."""
        try:
            from writing_resources import (
                build_association_bundle_from_runtime_context,
                apply_analysis_enrichment_to_bundle,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.warning("Writing resource layer unavailable for workflow association: %s", exc)
            return None

        # 1. Determine the appropriate draft seed based on mode
        draft_seed = self._build_association_seed(
            mode=mode,
            user_query=user_query,
            focused_points=focused_points,
            rag_evidence=rag_evidence,
            generated_answer=generated_answer,
        )

        try:
            # 2. Build base bundle WITHOUT analysis enrichment first (to detect actual increment)
            base_bundle, ephemeral_store = await asyncio.to_thread(
                build_association_bundle_from_runtime_context,
                query=user_query,
                draft_seed=draft_seed,
                focused_points=focused_points,
                retrieval_hits=rag_evidence,
                memory_hits=memory_hits,
                mode=mode,
                project_id=project_id,
                draft_id=draft_id,
                section_id=section_id,
                analysis_payloads=None,  # Delayed
                ai_adapter=self._resolve_association_ai_adapter(),
            )

            # 3. Apply enrichment and detect actual increment using unified helper
            enriched_bundle, was_enriched = apply_analysis_enrichment_to_bundle(
                base_bundle, analysis_payloads=analysis_payloads
            )

            bundle_dict = enriched_bundle.to_dict()
            bundle_dict["ephemeral_project"] = ephemeral_store
            bundle_dict["analysis_enriched"] = was_enriched
            return bundle_dict

        except ValueError as exc:
            logger.warning("Association bundle build failed in workflow: %s", exc)
            return None

    def _build_association_seed(
        self,
        mode: str,
        user_query: str,
        focused_points: List[str],
        rag_evidence: List[Dict[str, Any]],
        generated_answer: str,
    ) -> str:
        """
        Build a deterministic or generative draft seed based on the association mode.

        Why:
            Ensures 'no_ai' mode is decoupled from LLM hallucinations (generated_answer),
            maintaining a pure grounded baseline. 'ai' mode can leverage richer
            context from the generated response.
        """
        if mode == "ai":
            return generated_answer.strip()

        # Deterministic seed for 'no_ai'
        parts = [f"Focus Query: {user_query}"]
        if focused_points:
            parts.append(f"Derived Research Points: {', '.join(focused_points)}")

        # Include top 2 evidence fragments to ground the seed without generation
        stable_evidence = []
        for ev in rag_evidence[:2]:
            text = str(ev.get("text", "")).strip()[:150]
            if text:
                stable_evidence.append(text)
        
        if stable_evidence:
            parts.append("Grounded Evidence Base:\n" + "\n".join(f"- {e}" for e in stable_evidence))

        return "\n\n".join(parts)

    def _collect_workflow_analysis_payloads(
        self,
        user_query: str,
        focused_points: List[str],
        generated_answer: str,
        association_mode: str,
    ) -> List[Dict[str, Any]]:
        """
        Organize workflow runtime information into structured analysis payloads.

        Why:
            Provides a bridge for the associative writing assistant to pick up
            simulated "research results" like semantic themes and reasoning
            chains, enabling analytical enrichment even when not running the full
            pipeline. The reasoning chain is only included for ai mode so the
            no_ai baseline stays grounded and deterministic.
        """
        payloads: List[Dict[str, Any]] = []

        # 1. Synthesize semantic themes from focused points
        if focused_points:
            themes = [
                {
                    "theme_title": str(point).strip(),
                    "summary": f"Key theme identified during RAG routing for query: {user_query[:60]}",
                }
                for point in focused_points
                if str(point).strip()
            ]
            if themes:
                payloads.append({"semantic_themes": themes})

        # 2. Extract a simulated reasoning chain from the answer
        error_prefixes = ("发生错误", "LLM 服务不可用", "API 错误", "生成失败")
        if (
            str(association_mode or "").strip().lower() == "ai"
            and generated_answer
            and not any(generated_answer.startswith(p) for p in error_prefixes)
        ):
            payloads.append({
                "reasoning_chain": {
                    "final_conclusion": generated_answer[:300].strip().replace("\n", " "),
                    "conflicts": [],
                }
            })

        return payloads

    def _retrieve_memory_hits(
        self,
        user_query: str,
        focused_points: List[str],
    ) -> List[Dict[str, Any]]:
        """Query MemPalace for supporting project memory without blocking retrieval."""
        adapter = self._resolve_memory_adapter()
        if adapter is None:
            return []

        search_terms: List[str] = []
        if isinstance(user_query, str) and user_query.strip():
            search_terms.append(user_query.strip())
        if focused_points:
            focus_query = " ".join(point.strip() for point in focused_points if isinstance(point, str) and point.strip())
            if focus_query and focus_query not in search_terms:
                search_terms.append(focus_query)

        hits: List[Dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for term in search_terms:
            try:
                search_result = adapter.search(query=term, wing=self._memory_wing)
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.warning("MemPalace search failed for query %s: %s", term, exc)
                continue

            if not getattr(search_result, "available", False):
                continue

            for hit in getattr(search_result, "results", []):
                hit_dict = hit.to_dict() if hasattr(hit, "to_dict") else dict(hit)
                normalized_text = " ".join(str(hit_dict.get("text", "")).split())
                dedupe_key = (
                    str(hit_dict.get("wing", "")).strip(),
                    str(hit_dict.get("room", "")).strip(),
                    str(hit_dict.get("source_file", "")).strip(),
                    normalized_text,
                )
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                hits.append(hit_dict)
                if len(hits) >= 3:
                    return hits
        return hits
    
    def _calculate_confidence(
        self,
        focused_points: List[str],
        rag_evidence: List[Dict[str, Any]],
        generated_answer: str
    ) -> float:
        """
        计算置信度分数
        
        基于：
        - 是否识别出关注点
        - 是否找到相关证据
        - 答案长度和质量
        """
        score = 0.0
        
        # 关注点
        if focused_points:
            score += 0.3
        
        # 证据
        if rag_evidence:
            score += min(0.4, len(rag_evidence) * 0.1)
        
        # 答案
        if generated_answer and not generated_answer.startswith("发生错误"):
            answer_len = len(generated_answer)
            if answer_len > 100:
                score += 0.3
            elif answer_len > 50:
                score += 0.2
        
        return min(1.0, score)
    
    async def close(self) -> None:
        """关闭客户端和 RAGFlow 适配器资源"""
        if self.client and self._owns_llm_client and hasattr(self.client, "aclose"):
            await self.client.aclose()
        if self.rag_adapter:
            self.rag_adapter.close()


# ============================================================================
# 演示和测试
# ============================================================================

async def demo():
    """演示 RAG 工作流"""
    from layers.semantic_router import SemanticRouter
    
    print("=" * 60)
    print("RAG 工作流演示")
    print("=" * 60)
    
    embedding_api_key, embedding_base_url, embedding_model = resolve_embedding_config(
        default_base_url='https://api.siliconflow.cn/v1',
        default_model='BAAI/bge-m3',
    )
    llm_api_key, llm_base_url, llm_model = resolve_llm_config(
        default_base_url=DEFAULT_LLM_BASE_URL,
        default_model=DEFAULT_LLM_MODEL,
    )
    if not embedding_api_key:
        print("❌ 未设置 SILICONFLOW_API_KEY（或 SILICONFLOW_EMBEDDING_API_KEY）")
        return
    if not llm_api_key:
        print("❌ 未设置 ARK_API_KEY（兼容旧的 SILICONFLOW_API_KEY）")
        return
    
    try:
        # 初始化语义路由器
        print("\n1️⃣ 初始化语义路由器...")
        router = SemanticRouter(
            api_key=embedding_api_key,
            focus_points_path='focus_points.json',
            base_url=embedding_base_url,
            embedding_model=embedding_model,
        )
        print("✓ 路由器初始化完成")
        
        # 初始化 RAG 工作流
        print("\n2️⃣ 初始化 RAG 工作流...")
        workflow = RAGWorkflow(
            semantic_router=router,
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
        )
        print("✓ 工作流初始化完成")
        
        # 执行查询
        test_queries = [
            "激光功率如何影响熔池中的氮传输？",
            "温度梯度对晶粒形态的影响",
            "冷却速率与组织演变的关系"
        ]
        
        for query in test_queries:
            print(f"\n3️⃣ 查询: {query}")
            
            result = await workflow.ask_my_literature(query)
            
            print(f"\n   关注点: {result.focused_points}")
            print(f"   答案: {result.generated_answer[:200]}...")
            print(f"   置信度: {result.confidence_score:.2f}")
        
    except FileNotFoundError as e:
        print(f"❌ 文件未找到: {e}")
        print("   请先运行 focus_extractor.py 生成 focus_points.json")
    except Exception as e:
        print(f"❌ 演示失败: {e}")
    finally:
        await workflow.close()


if __name__ == '__main__':
    asyncio.run(demo())
