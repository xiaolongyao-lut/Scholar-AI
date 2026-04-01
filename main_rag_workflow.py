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


@dataclass
class RAGResult:
    """RAG 查询结果数据类"""
    query: str
    focused_points: List[str]
    rag_evidence: List[Dict[str, Any]]
    generated_answer: str
    confidence_score: float
    trace: Dict[str, Any]


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
        rag_instance: Optional[Any] = None,  # RAG-Anything 实例（可选，Sprint 3 中集成）
        api_key: Optional[str] = None,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "deepseek-ai/DeepSeek-V3"
    ):
        """
        初始化 RAG 工作流
        
        Args:
            semantic_router: SemanticRouter 实例
            rag_instance: RAG-Anything 实例（可选）
            api_key: 硅基流动 API key
            base_url: API 基础 URL
            model: LLM 模型名称
        """
        self.router = semantic_router
        self.rag = rag_instance
        self.api_key = api_key or os.environ.get('SILICONFLOW_API_KEY')
        self.base_url = base_url
        self.model = model
        
        # 防卡死 HTTP 客户端
        if httpx:
            self.client = httpx.AsyncClient(
                proxies=None,
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
        top_k_evidence: int = 5
    ) -> RAGResult:
        """
        完整的查询流程
        
        Args:
            user_query: 用户的自然语言问题
            top_k_points: 返回的关注点数
            top_k_evidence: 返回的证据数
        
        Returns:
            RAGResult 对象，包含所有中间步骤和最终答案
        """
        trace = {
            'step_1_routing': None,
            'step_2_rag_search': None,
            'step_3_generation': None
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
            # 第 2 步：构建增强查询词
            # ========================================
            logger.info("[Step 2] 构建增强查询词")
            
            enhanced_query = self._build_enhanced_query(
                user_query,
                focused_points
            )
            
            logger.info(f"增强查询: {enhanced_query[:100]}...")
            
            # ========================================
            # 第 3 步：RAG 混合检索（TODO: 集成 RAG-Anything）
            # ========================================
            logger.info("[Step 3] RAG 混合检索")
            
            rag_evidence = await self._rag_search(
                enhanced_query,
                top_k=top_k_evidence
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
                rag_evidence
            )
            
            trace['step_3_generation'] = {
                'answer_length': len(generated_answer),
                'generation_success': bool(generated_answer)
            }
            
            logger.info(f"✓ 生成答案 ({len(generated_answer)} 字)")
            
            # ========================================
            # 组织最终结果
            # ========================================
            result = RAGResult(
                query=user_query,
                focused_points=focused_points,
                rag_evidence=rag_evidence,
                generated_answer=generated_answer,
                confidence_score=self._calculate_confidence(
                    focused_points, rag_evidence, generated_answer
                ),
                trace=trace
            )
            
            return result
            
        except Exception as e:
            logger.error(f"工作流执行失败: {e}", exc_info=True)
            
            # 返回包含错误信息的结果
            return RAGResult(
                query=user_query,
                focused_points=[],
                rag_evidence=[],
                generated_answer=f"发生错误: {str(e)}",
                confidence_score=0.0,
                trace={'error': str(e), **trace}
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
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        调用 RAG-Anything 进行混合检索
        
        TODO: 集成实际的 RAG-Anything 调用
        当前返回空列表（回退方案）
        """
        if self.rag is None:
            logger.warning("RAG-Anything 未初始化，返回空结果")
            return []
        
        try:
            # TODO: 实现 RAG-Anything 的 aquery() 调用
            # rag_results = await self.rag.aquery(
            #     enhanced_query,
            #     param=QueryParam(mode="hybrid", top_k=top_k)
            # )
            # return rag_results
            
            # 临时回退：返回模拟数据
            logger.info("RAG-Anything 集成待实现，使用模拟数据")
            return [
                {
                    "chunk_id": "chunk_001",
                    "text": "这是一个模拟的检索结果...",
                    "score": 0.85,
                    "source": "mock"
                }
            ]
            
        except Exception as e:
            logger.error(f"RAG 检索失败: {e}")
            return []
    
    async def _generate_answer(
        self,
        user_query: str,
        focused_points: List[str],
        rag_evidence: List[Dict[str, Any]]
    ) -> str:
        """
        调用大模型生成最终答案
        
        输入：用户问题 + 关注点 + RAG 证据
        输出：学术性的综合回答
        """
        if not self.client or not self.api_key:
            logger.warning("LLM 客户端未初始化")
            return "LLM 服务不可用"
        
        # 构造上下文
        context_str = "\n".join([
            f"- {ev.get('text', '').strip()[:100]}"
            for ev in rag_evidence[:3]
        ])
        
        prompt = f"""你是一个学术研究助手。请基于以下信息回答用户的问题。

用户问题：{user_query}

相关研究重点：{', '.join(focused_points)}

文献证据：
{context_str if context_str else '（无关联证据）'}

要求：
1. 基于提供的证据进行回答
2. 如果证据不足，明确说明
3. 保持学术规范和严谨性
4. 长度控制在 200-500 字

回答："""
        
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 800
                }
            )
            
            if response.status_code != 200:
                logger.error(f"LLM API 失败: {response.status_code}")
                return f"API 错误: {response.status_code}"
            
            result = response.json()
            answer = result['choices'][0]['message']['content']
            
            return answer
            
        except Exception as e:
            logger.error(f"生成答案失败: {e}")
            return f"生成失败: {str(e)}"
    
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
        """关闭客户端"""
        if self.client:
            await self.client.aclose()


# ============================================================================
# 演示和测试
# ============================================================================

async def demo():
    """演示 RAG 工作流"""
    from layers.semantic_router import SemanticRouter
    
    print("=" * 60)
    print("RAG 工作流演示")
    print("=" * 60)
    
    api_key = os.environ.get('SILICONFLOW_API_KEY')
    if not api_key:
        print("❌ 未设置 SILICONFLOW_API_KEY")
        return
    
    try:
        # 初始化语义路由器
        print("\n1️⃣ 初始化语义路由器...")
        router = SemanticRouter(
            api_key=api_key,
            focus_points_path='focus_points.json'
        )
        print("✓ 路由器初始化完成")
        
        # 初始化 RAG 工作流
        print("\n2️⃣ 初始化 RAG 工作流...")
        workflow = RAGWorkflow(
            semantic_router=router,
            api_key=api_key
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
