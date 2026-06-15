# -*- coding: utf-8 -*-
"""Linter 模块 - 元数据检查和修复

参考 Zotero Format Metadata 插件的规则系统。

基本用法:
    from literature_assistant.core.linter import lint_materials

    materials = [
        {
            "material_id": "mat1",
            "title": "deep learning for nlp",
            "title_en": "deep learning for nlp",
            "metadata": {"language": "en-US"},
        }
    ]

    fixed_materials = await lint_materials(materials, debug=True)
"""

# 导入规则基类
from .rule_base import (
    ApplyContext,
    FieldRule,
    ItemRule,
    LinterRule,
    PrepareContext,
    ReportLevel,
    RuleCategory,
    RuleScope,
    get_all_rules,
    get_rule,
    get_rules_by_scope,
    register_rule,
)

# 导入引擎
from .engine import LinterEngine, lint_materials

# 导入工具函数
from .sentence_case import detect_case_style, to_sentence_case

# 自动导入所有规则（触发注册）
from .rules import correct_title_sentence_case  # noqa: F401

__all__ = [
    # 基类
    "LinterRule",
    "FieldRule",
    "ItemRule",
    "ApplyContext",
    "PrepareContext",
    "RuleScope",
    "RuleCategory",
    "ReportLevel",
    # 注册表
    "register_rule",
    "get_rule",
    "get_all_rules",
    "get_rules_by_scope",
    # 引擎
    "LinterEngine",
    "lint_materials",
    # 工具
    "to_sentence_case",
    "detect_case_style",
]
