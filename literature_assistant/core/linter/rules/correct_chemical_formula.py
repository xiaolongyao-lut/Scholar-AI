# -*- coding: utf-8 -*-
"""化学式上下标规则"""

import re
from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule
from ..special_words import CHEMICAL_ELEMENTS


def add_chemical_subscripts(text: str) -> str:
    """为化学式添加下标

    例如：
    - Cu2O → Cu<sub>2</sub>O
    - H2SO4 → H<sub>2</sub>SO<sub>4</sub>
    - CO2 → CO<sub>2</sub>
    """
    result = text

    # 构建化学元素的正则模式（按长度降序，避免 Ca 匹配了 C）
    elements_sorted = sorted(CHEMICAL_ELEMENTS, key=len, reverse=True)
    elements_pattern = '|'.join(re.escape(e) for e in elements_sorted)

    # 匹配：化学元素 + 数字
    # 使用 \b 单词边界可能不工作，改用更精确的模式
    pattern = rf'({elements_pattern})(\d+)'

    def replace_subscript(match: re.Match) -> str:
        element = match.group(1)
        number = match.group(2)
        # 检查是否已经有下标标签
        if '<sub>' in text[max(0, match.start()-10):match.end()+10]:
            return match.group(0)  # 已经处理过，不重复
        return f"{element}<sub>{number}</sub>"

    result = re.sub(pattern, replace_subscript, result)

    return result


def add_chemical_superscripts(text: str) -> str:
    """为化学式添加上标（电荷）

    例如：
    - Fe3+ → Fe<sup>3+</sup>
    - SO4 2- → SO<sub>4</sub><sup>2-</sup>
    - Co2+ → Co<sup>2+</sup>
    """
    result = text

    # 构建化学元素的正则模式
    elements_pattern = '|'.join(re.escape(e) for e in CHEMICAL_ELEMENTS)

    # 匹配：化学元素（可能带下标） + 数字 + +/-
    # 例如：Fe3+, Co2+
    pattern = rf'\b({elements_pattern}(?:<sub>\d+</sub>)?)(\d+)([+-])\b'

    def replace_superscript(match: re.Match) -> str:
        element = match.group(1)
        number = match.group(2)
        charge = match.group(3)
        return f"{element}<sup>{number}{charge}</sup>"

    result = re.sub(pattern, replace_superscript, result)

    return result


class CorrectTitleChemicalFormula(FieldRule):
    """为标题中的化学式添加上下标"""

    def __init__(self):
        super().__init__(
            rule_id="correct-title-chemical-formula",
            target_field="title_en",
            name="化学式上下标",
            description="自动为化学式添加上下标（如 CO2 → CO<sub>2</sub>）",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        title_en = ctx.item.get("title_en", "")
        if not title_en or not isinstance(title_en, str):
            return

        # 先添加下标，再添加上标
        try:
            modified = add_chemical_subscripts(title_en)
            modified = add_chemical_superscripts(modified)
        except Exception as e:
            ctx.debug(f"[chemical] 处理失败: {e}")
            return

        if modified != title_en:
            ctx.report(
                level=ReportLevel.INFO,
                message="化学式已添加上下标",
                action=f"{title_en[:40]}... → {modified[:40]}...",
            )
            ctx.item["title_en"] = modified


# 注册规则
register_rule(CorrectTitleChemicalFormula())
