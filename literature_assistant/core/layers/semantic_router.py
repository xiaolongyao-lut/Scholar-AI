# -*- coding: utf-8 -*-
"""
Semantic Router (Sprint 2)
Role: 将关注点库向量化并提供毫秒级的语义匹配

输入：focus_points.json（从 Sprint 1 生成）
输出：内存驻留的向量缓存 + route_query() 接口

使用方式：
    router = SemanticRouter(
        api_key=os.environ['SILICONFLOW_API_KEY'],
        focus_points_path='focus_points.json'
    )
    
    # 查询时
    top_points = router.route_query("温度如何影响晶粒形态？", top_k=3)
    # → ["温度梯度", "冷却速率", "参数优化"]
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

import httpx
import numpy as np
from runtime_env import (
    build_embedding_failover_pool,
    build_embedding_request_payload,
    extract_embedding_vectors,
    resolve_embedding_config,
    resolve_embedding_request_url,
)

# 配置日志（仅在首次导入时执行，避免干扰其他模块的日志配置）
_logger = logging.getLogger(__name__)
if not _logger.hasHandlers():
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)

logger = _logger
DEFAULT_EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"


class SemanticRouter:
    """
    语义路由器：用向量化的关注点库进行语义匹配

    核心优势：
    - ✅ 毫秒级响应（向量已缓存）
    - ✅ 支持同义词和口语表达
    - ✅ 无需本地 GPU（调用云 API）
    - ✅ 自动适应新增关注点（重新运行 focus_extractor.py）

    性能优化：
    - ✅ 预归一化关注点向量（避免重复计算）
    - ✅ 并发竞态控制（lazy_vectorize 下仅执行一次）
    - ✅ O(N) Top-K 查询（使用 argpartition）
    - ✅ 改进的 API 重试机制（指数退避）
    - ✅ 增强的连接池配置（支持更高并发）

    线程安全性：
    - ✅ asyncio.Lock 延迟初始化（确保绑定到正确的事件循环）
    - ✅ threading.Lock 保护跨线程初始化状态检查
    - ✅ route_query_sync 中完善的异步-同步桥接（含超时和异常处理）
    """

    def __init__(
        self,
        api_key: str | None,
        focus_points_path: str,
        base_url: str = DEFAULT_EMBEDDING_BASE_URL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        timeout: float = 60.0,
        batch_size: int = 50,
        lazy_vectorize: bool = True
    ):
        """
        初始化语义路由器

        Args:
            api_key: embedding 服务 API key
            focus_points_path: focus_points.json 文件路径
            base_url: embedding API 基础 URL
            embedding_model: 向量模型名称（bge-m3 输出 1024 维）
            timeout: HTTP 超时时间（秒）
            batch_size: 向量化批大小
            lazy_vectorize: 延迟向量化（True=首次查询时执行，False=初始化时执行）

        Raises:
            ValueError: 如果 api_key 为空或 focus_points_path 不存在
        """
        self.api_key, self.base_url, self.embedding_model = resolve_embedding_config(
            api_key,
            base_url=base_url,
            model=embedding_model,
            default_base_url=DEFAULT_EMBEDDING_BASE_URL,
            default_model=DEFAULT_EMBEDDING_MODEL,
            probe_candidates=False,
        )
        # 参数验证：API key 不能为空或仅包含空白字符
        if not self.api_key or not self.api_key.strip():
            raise ValueError("api_key 不能为空")

        self.timeout = timeout
        self.batch_size = batch_size
        self.lazy_vectorize = lazy_vectorize
        self._embedding_pool = build_embedding_failover_pool(
            api_key=api_key,
            base_url=base_url,
            model=embedding_model,
            default_base_url=DEFAULT_EMBEDDING_BASE_URL,
            default_model=DEFAULT_EMBEDDING_MODEL,
        )

        # 防卡死客户端（优化连接池配置以提升向量化性能）
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_connections=10,  # 提升到 10 以支持更高的并发
                max_keepalive_connections=5  # 增加保活连接数
            )
        )

        # 关注点数据
        self.focus_points: List[str] = []
        self.focus_vectors: Optional[np.ndarray] = None  # shape: (N, 1024)
        self.focus_vectors_norm: Optional[np.ndarray] = None  # 预归一化向量缓存
        self._vectorization_done: bool = False
        self._vectorization_lock: Optional[asyncio.Lock] = None  # 延迟初始化
        self._init_lock: threading.Lock = threading.Lock()  # 跨线程初始化保护

        # 缓存最近的查询结果（用于调试）
        self.last_query_result: dict[str, Any] = {}

        # 加载关注点库（不进行向量化）
        self._load_focus_points(focus_points_path)

        # 如果不延迟向量化，则在初始化时执行
        if not lazy_vectorize:
            self._init_vectorization_sync()

    def _init_vectorization_sync(self) -> None:
        """同步初始化向量化（在 __init__ 中调用）"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 没有事件循环，创建新的
            try:
                asyncio.run(self._vectorize_all_points())
                self._vectorization_done = True
            except RuntimeError as e:
                logger.error(f"初始化向量化失败: {e}，改为延迟模式")
                self.lazy_vectorize = True
            return

        if loop.is_running():
            logger.warning("检测到运行中的事件循环，强制改为延迟向量化模式")
            self.lazy_vectorize = True
            return

        # 事件循环存在但未运行，直接使用
        try:
            loop.run_until_complete(self._vectorize_all_points())
            self._vectorization_done = True
        except RuntimeError as e:
            logger.error(f"初始化向量化失败: {e}，改为延迟模式")
            self.lazy_vectorize = True

    def _load_focus_points(self, focus_points_path: str) -> None:
        """加载关注点库（仅读取，不向量化）"""
        path = Path(focus_points_path)

        if not path.exists():
            logger.error(f"关注点库文件不存在: {focus_points_path}")
            raise FileNotFoundError(f"focus_points.json not found at {focus_points_path}")

        try:
            data = json.loads(path.read_text(encoding='utf-8'))

            # 优先使用 focus_registry 中的规范名称（新的升级架构）
            focus_registry = data.get('focus_registry', [])
            if focus_registry:
                # focus_registry 是列表形式：[{id, canonical_name, aliases, ...}, ...]
                # 从 focus_registry 中提取规范名称
                if isinstance(focus_registry, list):
                    self.focus_points = [
                        item.get('canonical_name')
                        for item in focus_registry
                        if item.get('canonical_name')
                    ]
                    logger.info(f"✓ 从 focus_registry (list) 加载关注点库: {len(self.focus_points)} 个标签")
                elif isinstance(focus_registry, dict):
                    # 兼容旧的字典形式（如果存在）
                    self.focus_points = [
                        item.get('canonical_name', name)
                        for name, item in focus_registry.items()
                    ]
                    logger.info(f"✓ 从 focus_registry (dict) 加载关注点库: {len(self.focus_points)} 个标签")
                else:
                    logger.warning(f"focus_registry 格式不支持 ({type(focus_registry)})，回退到 points")
                    self.focus_points = data.get('points', [])
                    logger.info(f"✓ 从 points 字段加载关注点库: {len(self.focus_points)} 个标签")
            else:
                # 回退到旧的 points 字段（兼容性）
                self.focus_points = data.get('points', [])
                logger.info(f"✓ 从 points 字段加载关注点库: {len(self.focus_points)} 个标签")

        except json.JSONDecodeError as e:
            logger.error(f"无法解析 JSON 文件: {e}")
            raise
    
    async def _vectorize_all_points(self) -> None:
        """批量向量化所有关注点并预归一化（初始化或首次查询时调用）"""
        if not self.focus_points:
            logger.warning("没有关注点需要向量化")
            return

        logger.info(f"正在向量化 {len(self.focus_points)} 个关注点...")

        vectors = []
        failed_batches = []

        # 分批向量化
        for batch_idx in range(0, len(self.focus_points), self.batch_size):
            batch = self.focus_points[batch_idx:batch_idx + self.batch_size]

            try:
                batch_vectors = await self._call_embedding_api(batch)
                if not batch_vectors:
                    failed_batches.append(batch_idx)
                    continue

                vectors.extend(batch_vectors)
                progress = min(batch_idx + self.batch_size, len(self.focus_points))
                logger.info(f"  进度: {progress}/{len(self.focus_points)}")

            except Exception as e:
                logger.error(f"向量化批次 {batch_idx} 失败: {e}")
                failed_batches.append(batch_idx)

        if not vectors:
            logger.error("向量化失败，无可用向量")
            return

        if failed_batches:
            logger.warning(f"部分批次失败: {failed_batches}")

        # 创建向量矩阵并验证形状
        self.focus_vectors = np.array(vectors, dtype=np.float32)

        if self.focus_vectors.shape[0] != len(self.focus_points):
            logger.warning(
                f"向量数量不匹配：期望 {len(self.focus_points)}，"
                f"实际 {self.focus_vectors.shape[0]}"
            )

        # 预归一化向量（O(N) 一次性计算，后续查询只需归一化 query 向量）
        norms = np.linalg.norm(self.focus_vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)  # 避免除以零
        self.focus_vectors_norm = self.focus_vectors / norms

        logger.info(f"✓ 向量化完成！维度: {self.focus_vectors.shape}，已预归一化")
    
    async def _call_embedding_api_once(
        self,
        texts: List[str],
        api_key: str,
        base_url: str,
        embedding_model: str,
    ) -> List[List[float]]:
        """调用单个 embedding 凭证（包含重试机制）。"""
        max_retries = 3
        retry_delay = 1.0  # 初始重试延迟（秒）

        for attempt in range(max_retries):
            try:
                response = await self.client.post(
                    resolve_embedding_request_url(base_url, embedding_model),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json=build_embedding_request_payload(
                        texts,
                        base_url=base_url,
                        model=embedding_model,
                    ),
                )

                if response.status_code == 200:
                    embeddings = extract_embedding_vectors(response.json())
                    return embeddings
                elif response.status_code in (429, 500, 502, 503):
                    # 可重试的错误
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"API 返回 {response.status_code}，"
                            f"{retry_delay:.1f} 秒后重试（尝试 {attempt + 1}/{max_retries}）"
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                        continue
                    else:
                        raise RuntimeError(f"API 调用失败 {response.status_code}: {response.text}")
                else:
                    raise RuntimeError(f"API 调用失败 {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"API 调用超时，"
                        f"{retry_delay:.1f} 秒后重试（尝试 {attempt + 1}/{max_retries}）"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise RuntimeError("API 调用超时（所有重试均失败）")
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"API 调用异常: {e}，"
                        f"{retry_delay:.1f} 秒后重试（尝试 {attempt + 1}/{max_retries}）"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise RuntimeError(f"API 调用异常（所有重试均失败）: {e}") from e

        raise RuntimeError("API 调用异常（重试已耗尽）")

    async def _call_embedding_api(self, texts: List[str]) -> List[List[float]]:
        """调用 embedding API，失败时按凭证池自动轮换。"""
        try:
            if self._embedding_pool is not None:
                async def _invoke(cred: Any) -> List[List[float]]:
                    return await self._call_embedding_api_once(
                        texts,
                        cred.api_key,
                        cred.base_url,
                        cred.model,
                    )

                return await self._embedding_pool.try_call_async(
                    "embedding",
                    _invoke,
                    cooldown_on=lambda _exc: True,
                )

            return await self._call_embedding_api_once(
                texts,
                self.api_key,
                self.base_url,
                self.embedding_model,
            )
        except Exception as e:
            logger.error(f"API 调用异常（所有凭证均失败）: {e}")
            return []
    
    async def _get_query_vector(self, query: str) -> Optional[np.ndarray]:
        """获取查询的向量表示"""
        try:
            vectors = await self._call_embedding_api([query])
            
            if vectors and len(vectors) > 0:
                return np.array(vectors[0])
            else:
                logger.error("无法获取查询向量")
                return None
                
        except Exception as e:
            logger.error(f"获取查询向量失败: {e}")
            return None
    
    def _cosine_similarity(self, query_vector: np.ndarray) -> np.ndarray:
        """
        计算查询向量与所有关注点的余弦相似度（O(N) 时间）

        预期：focus_vectors_norm 已预归一化，仅需对 query_vector 进行归一化

        Args:
            query_vector: 查询向量 (1024,)

        Returns:
            相似度数组 (N,)，值域 [-1, 1]
        """
        if self.focus_vectors_norm is None:
            logger.warning("关注点向量未预归一化，回退到动态归一化")
            if self.focus_vectors is None:
                return np.array([])
            # 动态归一化（应仅在异常情况下发生）
            norms = np.linalg.norm(self.focus_vectors, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-8)
            vectors_norm = self.focus_vectors / norms
        else:
            vectors_norm = self.focus_vectors_norm

        # 仅归一化查询向量（关注点已预归一化）
        query_norm = np.linalg.norm(query_vector)
        query_norm = max(query_norm, 1e-8)
        query_normalized = query_vector / query_norm

        # 点积 = 余弦相似度（在归一化后）
        similarities = np.dot(vectors_norm, query_normalized)

        return similarities
    
    async def route_query(
        self,
        user_query: str,
        top_k: int = 3,
        confidence_threshold: float = 0.0
    ) -> List[str]:
        """
        将用户查询路由到最相关的关注点

        Args:
            user_query: 用户的自然语言问题
            top_k: 返回的关注点数量
            confidence_threshold: 置信度阈值（0-1）

        Returns:
            排序的关注点列表，例如 ["温度梯度", "冷却速率", "参数优化"]
        """
        # 延迟初始化 asyncio.Lock（必须在事件循环中执行）
        if self._vectorization_lock is None:
            self._vectorization_lock = asyncio.Lock()

        # 延迟向量化：首次查询时执行（带并发控制）
        if not self._vectorization_done and self.focus_vectors is None:
            async with self._vectorization_lock:
                # 双检查锁定（Double-Check Locking）
                if not self._vectorization_done and self.focus_vectors is None:
                    logger.info("首次查询，执行向量化...")
                    await self._vectorize_all_points()
                    self._vectorization_done = True
                else:
                    logger.info("向量化已由其他协程完成")

        if not self.focus_points or self.focus_vectors is None:
            logger.error("关注点库未初始化或向量化失败")
            return []

        # 1. 获取查询向量
        query_vector = await self._get_query_vector(user_query)

        if query_vector is None:
            logger.error(f"无法向量化查询: {user_query}")
            return []

        # 2. 计算相似度（O(N)，毫秒级）
        similarities = self._cosine_similarity(query_vector)

        # 3. 验证边界条件并使用 argpartition 进行 O(N) Top-K 查询
        if not self.focus_points or len(self.focus_points) == 0:
            logger.warning("没有可用的关注点")
            return []

        effective_k = min(top_k, len(self.focus_points))

        # 4. Top-K 检索（使用 argpartition 优化）
        if effective_k > 0 and len(self.focus_points) > 1:
            # 使用 argpartition 分割（更高效）
            partition_idx = np.argpartition(-similarities, effective_k - 1)[:effective_k]
            # 对分割结果进行排序以保持输出顺序
            sorted_pos = np.argsort(-similarities[partition_idx])
            top_indices = partition_idx[sorted_pos]
        else:
            # 只有 1 个或 0 个点时直接返回
            top_indices = np.argsort(-similarities)[:effective_k]

        top_points = [self.focus_points[i] for i in top_indices]
        top_scores = [float(similarities[i]) for i in top_indices]

        # 5. 过滤低置信度
        filtered_results = [
            (point, score)
            for point, score in zip(top_points, top_scores)
            if score >= confidence_threshold
        ]

        if not filtered_results:
            logger.warning(f"无点通过置信度阈值 {confidence_threshold}")
            # 安全的回退：确保 top_points 不为空
            if top_points:
                filtered_results = list(zip(top_points, top_scores))[:1]
            else:
                return []

        # 保存查询结果供调试
        self.last_query_result = {
            'query': user_query,
            'results': [(p, float(s)) for p, s in filtered_results],
            'timestamp': str(datetime.datetime.now())
        }

        logger.info(f"✓ 路由结果: {[p for p, _ in filtered_results]}")

        return [p for p, _ in filtered_results]
    
    def get_point_info(self, point: str) -> dict[str, Any]:
        """获取某个关注点的信息"""
        if point not in self.focus_points:
            return {}
        
        idx = self.focus_points.index(point)
        
        return {
            'point': point,
            'index': idx,
            'vector_shape': self.focus_vectors[idx].shape if self.focus_vectors is not None else None,
            'related_points': self._find_similar_points(idx, top_k=3)
        }
    
    def _find_similar_points(self, point_idx: int, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        找到与某个关注点最相似的其他点（用于理解点之间的关系）

        使用预归一化向量，性能优化
        """
        if self.focus_vectors_norm is None or point_idx >= len(self.focus_points):
            return []

        query_vector = self.focus_vectors_norm[point_idx]
        similarities = np.dot(self.focus_vectors_norm, query_vector)

        # 排除自身，取最相似的 top-k
        similarities[point_idx] = -1.0

        # 使用 argpartition 优化（O(N)）
        effective_k = min(top_k, len(self.focus_points) - 1)
        if len(self.focus_points) > effective_k + 1:
            partition_idx = np.argpartition(-similarities, effective_k)[:effective_k]
            sorted_pos = np.argsort(-similarities[partition_idx])
            top_indices = partition_idx[sorted_pos]
        else:
            top_indices = np.argsort(-similarities)[:effective_k]

        return [
            (self.focus_points[i], float(similarities[i]))
            for i in top_indices if similarities[i] >= 0.0
        ]
    
    def get_statistics(self) -> dict[str, Any]:
        """获取路由器的统计信息"""
        return {
            'total_points': len(self.focus_points),
            'vector_dimension': self.focus_vectors.shape[1] if self.focus_vectors is not None else 0,
            'vector_shape': str(self.focus_vectors.shape) if self.focus_vectors is not None else 'None',
            'embedding_model': self.embedding_model,
            'last_query': self.last_query_result
        }
    
    async def close(self) -> None:
        """关闭异步客户端"""
        await self.client.aclose()


# ============================================================================
# 便捷函数：用于同步调用（避免异步复杂性）
# ============================================================================

_global_router: Optional[SemanticRouter] = None


def init_router(
    api_key: str,
    focus_points_path: str,
    **kwargs
) -> SemanticRouter:
    """初始化全局路由器实例"""
    global _global_router
    
    _global_router = SemanticRouter(api_key, focus_points_path, **kwargs)
    return _global_router


def route_query_sync(
    query: str,
    top_k: int = 3,
    router: Optional[SemanticRouter] = None
) -> List[str]:
    """
    同步版本的 route_query（自动处理事件循环）

    Args:
        query: 查询文本
        top_k: 返回的关注点数
        router: 使用的 SemanticRouter 实例（若为None则使用全局）

    Returns:
        关注点列表
    """
    if router is None:
        router = _global_router

    if router is None:
        logger.error("路由器未初始化，请先调用 init_router()")
        return []

    # 线程安全的初始化检查
    with router._init_lock:
        # 使用线程锁保护跨线程的初始化状态检查
        vectorization_needed = not router._vectorization_done and router.focus_vectors is None

    # 如果需要初始化且客户端不是在当前事件循环中创建的，使用线程池
    if vectorization_needed:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop is None or not loop.is_running():
            # 没有运行的事件循环，创建新的或使用现有的
            try:
                return asyncio.run(router.route_query(query, top_k))
            except RuntimeError as e:
                logger.error(f"无法运行异步操作: {e}")
                return []
        else:
            # 已在异步上下文中，使用线程池运行
            def _run_async_in_thread():
                """在新线程中创建事件循环并运行"""
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(router.route_query(query, top_k))
                finally:
                    # 确保事件循环被正确关闭
                    try:
                        new_loop.run_until_complete(new_loop.shutdown_asyncgens())
                    except Exception as cleanup_error:
                        logger.warning(f"事件循环清理时出错: {cleanup_error}")
                    finally:
                        new_loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_async_in_thread)
                try:
                    return future.result(timeout=30.0)
                except concurrent.futures.TimeoutError:
                    logger.error("查询执行超时（30秒）")
                    return []
                except Exception as e:
                    logger.error(f"异步查询执行失败: {e}")
                    return []
    else:
        # 已初始化，使用常规流程
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在运行的事件循环中，使用线程池
                def _run_async_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(router.route_query(query, top_k))
                    finally:
                        try:
                            new_loop.run_until_complete(new_loop.shutdown_asyncgens())
                        except Exception:
                            pass
                        finally:
                            new_loop.close()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_run_async_in_thread)
                    try:
                        return future.result(timeout=30.0)
                    except concurrent.futures.TimeoutError:
                        logger.error("查询执行超时（30秒）")
                        return []
            else:
                return loop.run_until_complete(router.route_query(query, top_k))
        except RuntimeError:
            try:
                return asyncio.run(router.route_query(query, top_k))
            except Exception as e:
                logger.error(f"无法运行异步操作: {e}")
                return []


# ============================================================================
# 测试和演示
# ============================================================================

async def demo():
    """演示语义路由的效果"""

    # 获取 API key
    api_key = os.environ.get('SILICONFLOW_EMBEDDING_API_KEY') or os.environ.get('SILICONFLOW_API_KEY')
    if not api_key:
        print("❌ 环境变量 SILICONFLOW_API_KEY（或 SILICONFLOW_EMBEDDING_API_KEY）未设置")
        sys.exit(1)

    # 创建路由器
    print("初始化语义路由器...")
    try:
        router = SemanticRouter(
            api_key=api_key,
            focus_points_path='focus_points.json',
            base_url=os.environ.get('SILICONFLOW_EMBEDDING_BASE_URL', DEFAULT_EMBEDDING_BASE_URL),
            embedding_model=os.environ.get('SILICONFLOW_EMBEDDING_MODEL', DEFAULT_EMBEDDING_MODEL),
            lazy_vectorize=True
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    try:
        # 演示查询
        test_queries = [
            "激光功率如何影响熔池中的氮传输？",
            "温度梯度对晶粒形态的影响",
            "冷却速率与组织演变",
            "这个实验的材料成分是什么？",
            "图像识别和深度学习的应用"
        ]

        print("\n" + "="*60)
        print("🔍 语义路由演示")
        print("="*60)

        for query in test_queries:
            print(f"\n📝 查询: {query}")

            results = await router.route_query(query, top_k=3)

            print(f"✨ 路由结果:")
            for i, point in enumerate(results, 1):
                print(f"   {i}. {point}")

        # 显示统计信息
        print("\n" + "="*60)
        print("📊 路由器统计")
        print("="*60)
        stats = router.get_statistics()
        for key, value in stats.items():
            if key != 'last_query':
                print(f"{key}: {value}")

    finally:
        await router.close()


if __name__ == '__main__':
    asyncio.run(demo())
