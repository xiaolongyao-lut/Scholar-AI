# -*- coding: utf-8 -*-
"""Linter 规则基类系统

参考 Zotero Format Metadata 插件的规则架构：
https://github.com/northword/zotero-format-metadata

核心概念：
- Rule: 检测并修复元数据问题的独立规则
- ApplyContext: 规则执行上下文，包含 item、options、logger
- PrepareContext: 规则预处理上下文，用于批量加载数据
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol


class RuleScope(Enum):
    """规则作用域"""
    FIELD = "field"  # 字段级别（如 title, authors）
    ITEM = "item"    # 条目级别（如重复检测）
    TAG = "tag"      # 标签级别（未实现）
    ATTACHMENT = "attachment"  # 附件级别（未实现）


class RuleCategory(Enum):
    """规则类别"""
    RULE = "rule"  # 自动修复规则
    TOOL = "tool"  # 手动工具


class ReportLevel(Enum):
    """报告级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ReportInfo:
    """规则报告信息"""
    level: ReportLevel
    message: str
    action: Optional[str] = None  # 修复动作描述


@dataclass
class ApplyContext:
    """规则应用上下文"""
    item: dict[str, Any]  # 文献条目（WritingMaterial 的 dict 表示）
    options: dict[str, Any] = field(default_factory=dict)  # 从 prepare() 返回的选项
    debug: Callable[[str], None] = field(default_factory=lambda: print)  # 调试日志函数
    reports: list[ReportInfo] = field(default_factory=list)  # 收集的报告

    def report(self, level: ReportLevel, message: str, action: Optional[str] = None) -> None:
        """添加报告"""
        self.reports.append(ReportInfo(level=level, message=message, action=action))


@dataclass
class PrepareContext:
    """规则准备上下文"""
    items: list[dict[str, Any]]  # 所有待处理的文献条目
    debug: Callable[[str], None] = field(default_factory=lambda: print)


class LinterRule(ABC):
    """Linter 规则抽象基类"""

    def __init__(
        self,
        rule_id: str,
        scope: RuleScope,
        category: RuleCategory = RuleCategory.RULE,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cooldown_ms: int = 0,
    ):
        """
        Args:
            rule_id: 规则唯一 ID（kebab-case）
            scope: 规则作用域
            category: 规则类别
            name: 规则名称（可选，默认为 rule_id）
            description: 规则描述
            cooldown_ms: 最小执行间隔（毫秒），用于避免频繁 API 调用
        """
        self.id = rule_id
        self.scope = scope
        self.category = category
        self.name = name or rule_id
        self.description = description or f"Rule: {rule_id}"
        self.cooldown_ms = cooldown_ms

    @abstractmethod
    async def apply(self, ctx: ApplyContext) -> None:
        """应用规则到单个条目

        Args:
            ctx: 应用上下文，包含 item、options、debug、report 函数

        规则应该：
        1. 检查 ctx.item 的字段
        2. 如果需要修复，直接修改 ctx.item
        3. 使用 ctx.report() 报告问题和修复动作
        """
        raise NotImplementedError

    async def prepare(self, ctx: PrepareContext) -> dict[str, Any] | bool:
        """预处理：批量加载数据或检查前置条件

        Args:
            ctx: 准备上下文，包含所有待处理的 items

        Returns:
            - dict: 返回 options，会传递给 apply()
            - False: 跳过此规则
            - True 或 {}: 正常执行，无额外 options

        用途：
        - 批量加载外部数据（如期刊别名表、国家列表）
        - 检查前置条件（如 API token 是否可用）
        - 统计信息（如重复检测需要先构建索引）
        """
        return {}


class FieldRule(LinterRule):
    """字段级规则基类"""

    def __init__(
        self,
        rule_id: str,
        target_field: str,
        category: RuleCategory = RuleCategory.RULE,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cooldown_ms: int = 0,
    ):
        """
        Args:
            target_field: 目标字段名（如 'title', 'authors', 'journal'）
        """
        super().__init__(
            rule_id=rule_id,
            scope=RuleScope.FIELD,
            category=category,
            name=name,
            description=description,
            cooldown_ms=cooldown_ms,
        )
        self.target_field = target_field


class ItemRule(LinterRule):
    """条目级规则基类"""

    def __init__(
        self,
        rule_id: str,
        category: RuleCategory = RuleCategory.RULE,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cooldown_ms: int = 0,
    ):
        super().__init__(
            rule_id=rule_id,
            scope=RuleScope.ITEM,
            category=category,
            name=name,
            description=description,
            cooldown_ms=cooldown_ms,
        )


# 规则注册表
_RULE_REGISTRY: dict[str, LinterRule] = {}


def register_rule(rule: LinterRule) -> LinterRule:
    """注册规则到全局注册表"""
    if rule.id in _RULE_REGISTRY:
        raise ValueError(f"Rule {rule.id} already registered")
    _RULE_REGISTRY[rule.id] = rule
    return rule


def get_rule(rule_id: str) -> Optional[LinterRule]:
    """获取注册的规则"""
    return _RULE_REGISTRY.get(rule_id)


def get_all_rules() -> dict[str, LinterRule]:
    """获取所有注册的规则"""
    return _RULE_REGISTRY.copy()


def get_rules_by_scope(scope: RuleScope) -> dict[str, LinterRule]:
    """获取指定作用域的所有规则"""
    return {
        rule_id: rule
        for rule_id, rule in _RULE_REGISTRY.items()
        if rule.scope == scope
    }
