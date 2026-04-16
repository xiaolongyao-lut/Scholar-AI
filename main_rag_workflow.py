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
import json
import logging
import os
from dataclasses import dataclass
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
DEFAULT_LLM_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
DEFAULT_LLM_MODEL = os.environ.get("ARK_MODEL", "ep-your-ark-endpoint")
LEGACY_LLM_API_ENV_NAMES = ("SILICONFLOW_API_KEY",)

# 导入适配层
from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter
from layers.r_layer_hybrid_retriever import hybrid_search


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
        self.api_key = api_key or os.environ.get('ARK_API_KEY')
        if not self.api_key:
            for legacy_env_name in LEGACY_LLM_API_ENV_NAMES:
                legacy_value = os.environ.get(legacy_env_name)
                if legacy_value:
                    self.api_key = legacy_value
                    break
        self.base_url = base_url
        self.model = model
        self.enable_requests_fallback = enable_requests_fallback
        self._owns_llm_client = llm_client is None
        self._memory_adapter = memory_adapter
        self._memory_adapter_resolved = memory_adapter is not None
        self._memory_wing = memory_wing
        self._association_ai_adapter = association_ai_adapter
        self._association_ai_adapter_resolved = association_ai_adapter is not None
        
        # 如果未传入适配器但有环境变量，则尝试自动初始化
        if not self.rag_adapter and os.environ.get('RAGFLOW_API_KEY'):
            self.rag_adapter = RAGFlowAdapter(
                api_key=os.environ.get('RAGFLOW_API_KEY'),
                base_url=os.environ.get('RAGFLOW_BASE_URL', 'https://localhost:9380')
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
        完整的查询流程
        
        Args:
            user_query: 用户的自然语言问题
            top_k_points: 返回的关注点数
            top_k_evidence: 返回的证据数
            dataset_ids: RAGFlow 数据集 ID 列表
        
        Returns:
            RAGResult 对象，包含所有中间步骤和最终答案
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
            # 第 1 步：语义收束
            # ========================================
            logger.info(f"[Step 1] 语义收束: {user_query}")
            
            focused_points = await self.router.route_query(
                user_query,
                top_k=top_k_points
            )
            
            trace['step_1_routing'] = {
                'user_query': user_query,
                'focused_points': focused_points,
                'routing_success': bool(focused_points)
            }
            
            logger.info(f"✓ 识别关注点: {focused_points}")

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
            
            rag_evidence = await self._rag_search(
                enhanced_query,
                top_k=top_k_evidence,
                dataset_ids=dataset_ids
            )
            
            trace['step_2_rag_search'] = {
                'enhanced_query': enhanced_query,
                'evidence_count': len(rag_evidence),
                'rag_search_success': bool(rag_evidence)
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
            
            trace['step_3_generation'] = {
                'answer_length': len(generated_answer),
                'generation_success': bool(generated_answer)
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
                    results.append({
                        "text": res.get("text", ""),
                        "source": res.get("source", "local_file"),
                        "score": res.get("hybrid_score", 0.0),
                        "metadata": {"type": "local_fallback"}
                    })
                
                if results:
                    logger.info(f"✓ 本地劫持/兜底检索成功，获取 {len(results)} 条结果")
                    return results
            except Exception as e:
                logger.error(f"本地兜底检索失败: {e}")

        # 策略 3: 最终回退（空结果）
        logger.warning("所有检索策略均未命中，返回空列表")
        return []
    
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
        # 构造上下文
        context_str = "\n".join([
            f"- {ev.get('text', '').strip()[:100]}"
            for ev in rag_evidence[:3]
        ])
        memory_str = "\n".join([
            (
                f"- [{hit.get('wing', 'unknown')}/{hit.get('room', 'unknown')}] "
                f"{hit.get('text', '').strip()[:120]}"
            )
            for hit in memory_hits[:3]
        ])
        
        prompt = f"""你是一个学术研究助手。请基于以下信息回答用户的问题。

用户问题：{user_query}

相关研究重点：{', '.join(focused_points)}

项目长期记忆：
{memory_str if memory_str else '（无长期记忆命中）'}

文献证据：
{context_str if context_str else '（无关联证据）'}

要求：
1. 基于提供的证据进行回答
2. 如果长期记忆与文献证据冲突，以文献证据为准，并明确指出冲突
3. 如果证据不足，明确说明
4. 保持学术规范和严谨性
5. 长度控制在 200-500 字

回答："""
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 800
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if not self.api_key:
            logger.warning("未配置 LLM API key，跳过答案生成")
            return "LLM 服务不可用"

        # 尝试使用 httpx (异步)
        if self.client:
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                if response.status_code == 200:
                    return response.json()['choices'][0]['message']['content']
                logger.error(f"LLM API (httpx) 失败: {response.status_code}")
            except Exception as e:
                logger.error(f"LLM API (httpx) 异常: {e}")

        # 兜底：使用 requests (同步)
        if self.enable_requests_fallback:
            try:
                import requests
                logger.info("尝试使用 requests 进行 LLM 调用兜底")
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                if response.status_code == 200:
                    return response.json()['choices'][0]['message']['content']
                return f"API 错误 (requests): {response.status_code}"
            except Exception as e:
                logger.error(f"LLM API (requests) 失败: {e}")
                return f"生成失败: {str(e)}"

        logger.warning("异步 LLM 客户端失败，且 requests 兜底已禁用")
        return "LLM 服务不可用"

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
                api_key=(
                    os.environ.get("ARK_API_KEY")
                    or os.environ.get("OPENAI_API_KEY")
                    or os.environ.get("SILICONFLOW_API_KEY")
                ),
                base_url=os.environ.get("ARK_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
                model=os.environ.get("ARK_MODEL") or os.environ.get("OPENAI_MODEL"),
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
    
    embedding_api_key = os.environ.get('SILICONFLOW_API_KEY') or os.environ.get('SILICONFLOW_EMBEDDING_API_KEY')
    llm_api_key = os.environ.get('ARK_API_KEY') or os.environ.get('SILICONFLOW_API_KEY')
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
            base_url=os.environ.get('SILICONFLOW_EMBEDDING_BASE_URL', 'https://api.siliconflow.cn/v1'),
            embedding_model=os.environ.get('SILICONFLOW_EMBEDDING_MODEL', 'BAAI/bge-m3'),
        )
        print("✓ 路由器初始化完成")
        
        # 初始化 RAG 工作流
        print("\n2️⃣ 初始化 RAG 工作流...")
        workflow = RAGWorkflow(
            semantic_router=router,
            api_key=llm_api_key,
            base_url=os.environ.get('ARK_BASE_URL', DEFAULT_LLM_BASE_URL),
            model=os.environ.get('ARK_MODEL', DEFAULT_LLM_MODEL),
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
