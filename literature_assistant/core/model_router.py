# -*- coding: utf-8 -*-
"""
Intelligent Model Router
Role: 根据意图路由到性价比最高且能力匹配的模型 (Spec §2.2)
"""

from __future__ import annotations

import logging
import re
from typing import List, Literal

logger = logging.getLogger(__name__)

class ModelRouter:
    """分类用户查询意图，分流至 V3 (解析) 或 R1 (推理)"""

    # 触发 R1 推理模型的逻辑特征词
    LOGIC_TRIGGER_PATTERNS = [
        r"为什么", r"分析", r"对比", r"权衡", r"优劣", r"推导",
        r"why", r"analyze", r"compare", r"contrast", r"conflict",
        r"矛盾", r"不一致", r"逻辑", r"由于", r"导致"
    ]

    def __init__(self, cheap_model: str, strong_model: str):
        self.cheap_model = cheap_model
        self.strong_model = strong_model
        self.trigger_re = re.compile("|".join(self.LOGIC_TRIGGER_PATTERNS), re.IGNORECASE)

    def route(self, query: str, points: List[str] = None) -> str:
        """
        分流策略：
        1. 关键词正则匹配 (低延迟方案)
        2. 关注点数量校验 (复杂问题通常对应更多关注点)
        3. 默认路由至廉价模型
        """
        all_text = query + " " + " ".join(points or [])

        # 判定 A: 正则命中
        if self.trigger_re.search(all_text):
            logger.info(f"🧠 模型路由: 命中逻辑关键词 -> {self.strong_model}")
            return self.strong_model

        # 判定 B: 关注点过多 (> 4个)
        if points and len(points) > 4:
            logger.info(f"🧠 模型路由: 关注点过于分散 -> {self.strong_model}")
            return self.strong_model

        # 默认为性价比最高模型
        logger.info(f"⚡ 模型路由: 命中快速生成模式 -> {self.cheap_model}")
        return self.cheap_model

def get_router(cheap: str, strong: str) -> ModelRouter:
    return ModelRouter(cheap, strong)
