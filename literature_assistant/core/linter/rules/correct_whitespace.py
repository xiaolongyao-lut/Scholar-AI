# -*- coding: utf-8 -*-
"""基础清理规则：空格、换行符等"""

import re
from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule


def normalize_whitespace(text: str) -> str:
    """标准化空格和换行符"""
    # 替换所有连续空白字符为单个空格
    text = re.sub(r'\s+', ' ', text)
    # 去除首尾空格
    return text.strip()


class CorrectTitleWhitespace(FieldRule):
    """清理标题中的多余空格"""

    def __init__(self):
        super().__init__(
            rule_id="correct-title-whitespace",
            target_field="title",
            name="清理标题空格",
            description="去除标题中的多余空格和换行符",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        title = ctx.item.get("title", "")
        if not title or not isinstance(title, str):
            return

        normalized = normalize_whitespace(title)
        if normalized != title:
            ctx.report(
                level=ReportLevel.WARNING,
                message="标题包含多余空格",
                action=f"{title[:30]}... → {normalized[:30]}...",
            )
            ctx.item["title"] = normalized


class CorrectTitleEnWhitespace(FieldRule):
    """清理英文标题中的多余空格"""

    def __init__(self):
        super().__init__(
            rule_id="correct-title-en-whitespace",
            target_field="title_en",
            name="清理英文标题空格",
            description="去除英文标题中的多余空格和换行符",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        title_en = ctx.item.get("title_en", "")
        if not title_en or not isinstance(title_en, str):
            return

        normalized = normalize_whitespace(title_en)
        if normalized != title_en:
            ctx.report(
                level=ReportLevel.WARNING,
                message="英文标题包含多余空格",
                action=f"{title_en[:30]}... → {normalized[:30]}...",
            )
            ctx.item["title_en"] = normalized


class CorrectJournalWhitespace(FieldRule):
    """清理期刊名中的多余空格"""

    def __init__(self):
        super().__init__(
            rule_id="correct-journal-whitespace",
            target_field="journal",
            name="清理期刊名空格",
            description="去除期刊名中的多余空格和换行符",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        # 从多个可能的位置获取期刊名
        journal = ctx.item.get("journal")
        if not journal:
            metadata = ctx.item.get("metadata", {})
            journal = metadata.get("journal") or metadata.get("publicationTitle")

        if not journal:
            return

        normalized = normalize_whitespace(str(journal))
        if normalized != str(journal):
            ctx.report(
                level=ReportLevel.INFO,
                message="期刊名包含多余空格",
                action=f"{journal} → {normalized}",
            )
            # 更新所有可能的字段
            if "journal" in ctx.item:
                ctx.item["journal"] = normalized
            if "metadata" in ctx.item and isinstance(ctx.item["metadata"], dict):
                if "journal" in ctx.item["metadata"]:
                    ctx.item["metadata"]["journal"] = normalized
                if "publicationTitle" in ctx.item["metadata"]:
                    ctx.item["metadata"]["publicationTitle"] = normalized


# 注册规则
register_rule(CorrectTitleWhitespace())
register_rule(CorrectTitleEnWhitespace())
register_rule(CorrectJournalWhitespace())
