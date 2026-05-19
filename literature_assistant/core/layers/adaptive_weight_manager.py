import json
import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("AdaptiveWeightManager")

class AdaptiveWeightManager:
    """
    P0: 混合检索权重智能自适应。
    职责：根据论文关注点 (focus) 映射最优检索权重配置，并实现持久化缓存。
    """

    # 预定义的领域映射方案 (启发式初筛)
    DOMAIN_MAPPING = {
        "laser_processing": ["激光", "功率", "速度", "熔池", "laser", "weld", "power"],
        "microstructure": ["组织", "晶粒", "相变", "析出", "grain", "microstructure", "phase"],
        "mechanical_property": ["拉伸", "硬度", "应力", "形变", "tensile", "hardness", "stress", "strain"]
    }

    # 默认领域的基础权重 - 基于 Tier 3 (3264 queries) 评估结果微调
    DEFAULT_WEIGHTS = {
        "general": {"bm25": 0.35, "vector": 0.35, "context": 0.3}, # 提升 BM25 解决长 query 命中点偏移
        "laser_processing": {"bm25": 0.3, "vector": 0.4, "context": 0.3},
        "microstructure": {"bm25": 0.4, "vector": 0.3, "context": 0.3}, # 结构类词汇更多依赖精确匹配
        "mechanical_property": {"bm25": 0.3, "vector": 0.3, "context": 0.4}
    }

    def __init__(self, cache_path: str = ".cache/weight_configs.json"):
        self.cache_path = cache_path
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        self.calibrator: Optional[Any] = None
        self._calibrator_resolution_attempted = False
        self.cached_configs = self._load_cache()

    def _create_calibrator(self) -> Optional[Any]:
        """Resolve the optional calibrator lazily to avoid circular imports at import time."""
        try:
            from layers.p1_fusion_weight_calibrator import FusionWeightCalibrator

            return FusionWeightCalibrator()
        except Exception as exc:
            logger.warning(f"初始化 FusionWeightCalibrator 失败，回退到静态权重: {exc}")
            return None

    def _get_calibrator(self) -> Optional[Any]:
        """Create the optional calibrator only when calibration is explicitly requested."""
        if self._calibrator_resolution_attempted:
            return self.calibrator
        self._calibrator_resolution_attempted = True
        self.calibrator = self._create_calibrator()
        return self.calibrator

    def _load_cache(self) -> Dict[str, Any]:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载权重缓存失败: {e}")
        return {}

    def _save_cache(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cached_configs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存权重缓存失败: {e}")

    def identify_domain(self, focus_keywords: List[str]) -> str:
        """根据关键词确定论文所属主领域。"""
        if not focus_keywords:
            return "general"
        
        scores = {domain: 0 for domain in self.DOMAIN_MAPPING}
        text_blob = " ".join(focus_keywords).lower()
        
        for domain, keywords in self.DOMAIN_MAPPING.items():
            for kw in keywords:
                if kw.lower() in text_blob:
                    scores[domain] += 1
        
        # 找匹配分最高的领域
        best_domain = max(scores, key=scores.get)
        if scores[best_domain] == 0:
            return "general"
        return best_domain

    async def get_optimal_weights(self, focus_keywords: List[str]) -> Dict[str, float]:
        """
        核心方法：获取针对特定关注点的最优权重。
        优先从缓存获取，缺失或过期则触发校准（Calibrator）。
        """
        domain = self.identify_domain(focus_keywords)
        
        # 1. 检查持久化缓存中是否有经过校准的权重
        if domain in self.cached_configs:
            logger.debug(f"命中权重缓存: {domain}")
            return self.cached_configs[domain]["weights"]

        # 2. 如果没有校准权重，尝试返回默认领域权重
        if domain in self.DEFAULT_WEIGHTS:
            logger.info(f"使用领域预设权重: {domain}")
            weights = self.DEFAULT_WEIGHTS[domain]
            # 标记为非校准值，待后续触发异步搜索
            return weights

        return self.DEFAULT_WEIGHTS["general"]

    async def run_calibration(self, domain: str):
        """
        【异步执行】利用 Grid Search 寻找该领域的最优权重并持久化。
        """
        calibrator = self._get_calibrator()
        if calibrator is None:
            logger.warning(f"领域 [{domain}] 校准器不可用，跳过权重校准。")
            return
        logger.info(f"开始为领域 [{domain}] 执行权重网格搜索校准...")
        best_res = await calibrator.calibrate_grid(step=0.1)
        
        if best_res:
            self.cached_configs[domain] = {
                "weights": {
                    "bm25": best_res.bm25_weight,
                    "vector": best_res.vector_weight,
                    "context": best_res.context_weight
                },
                "mrr": best_res.mrr,
                "recall_at_3": best_res.recall_at_3,
                "timestamp": os.path.getmtime(self.cache_path) if os.path.exists(self.cache_path) else 0
            }
            self._save_cache()
            logger.info(f"领域 [{domain}] 权重校准完成并缓存。")
