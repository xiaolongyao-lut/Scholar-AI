# -*- coding: utf-8 -*-
"""Title Sentence Case 规则

参考：
https://github.com/northword/zotero-format-metadata/blob/main/src/modules/rules/correct-title-sentence-case.ts

Zotero 推荐使用 Sentence case 存储标题，这样 CSL 样式可以轻松转换为 Title Case。
此规则将标题转换为 Sentence case，同时保护化学式、专有名词等。
"""

from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule
from ..sentence_case import keep_original_title, to_sentence_case


class CorrectTitleSentenceCase(FieldRule):
    """标题 Sentence Case 规则"""

    def __init__(self):
        super().__init__(
            rule_id="correct-title-sentence-case",
            target_field="title",
            name="转换标题为 Sentence Case",
            description="将标题转换为 Sentence case（句首大写），保护化学式和专有名词",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        """应用规则"""
        # 获取语言字段
        lang = ctx.item.get("metadata", {}).get("language") or "en-US"

        # 获取标题
        title = ctx.item.get("title_en") or ctx.item.get("title", "")
        if not title or not isinstance(title, str):
            return  # 没有标题，跳过

        # 检查是否禁用此语言
        disabled_languages = ctx.options.get("disabled_languages", "zh")
        if keep_original_title(lang, disabled_languages):
            ctx.debug(f"[title] 语言 {lang} 在禁用列表中，跳过转换")
            return

        # 转换为 Sentence Case（总是转换，确保首字母大写）
        try:
            new_title = to_sentence_case(title, lang)
        except Exception as e:
            ctx.debug(f"[title] 转换失败: {e}")
            return

        # 应用自定义术语替换（如果有）
        custom_terms = ctx.options.get("custom_terms", [])
        for term in custom_terms:
            if "search" in term and "replace" in term:
                new_title = new_title.replace(term["search"], term["replace"])

        # 如果标题改变了，记录并更新
        if new_title != title:
            ctx.report(
                level=ReportLevel.INFO,
                message=f"标题转换为 Sentence Case",
                action=f"{title[:50]}... → {new_title[:50]}...",
            )
            # 更新 title_en（如果有）或 title
            if "title_en" in ctx.item:
                ctx.item["title_en"] = new_title
            else:
                ctx.item["title"] = new_title

    async def prepare(self, ctx: Any) -> dict[str, Any] | bool:
        """预处理：加载配置"""
        # 这里可以从配置文件加载自定义术语
        # 暂时返回默认配置
        return {
            "disabled_languages": "zh,ja,ko",  # 中文、日语、韩语不转换
            "custom_terms": [],  # 自定义术语替换
        }


class CorrectShortTitleSentenceCase(FieldRule):
    """短标题 Sentence Case 规则"""

    def __init__(self):
        super().__init__(
            rule_id="correct-short-title-sentence-case",
            target_field="short_title",
            name="转换短标题为 Sentence Case",
            description="将短标题转换为 Sentence case",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        """应用规则"""
        lang = ctx.item.get("metadata", {}).get("language") or "en-US"
        short_title = ctx.item.get("metadata", {}).get("short_title", "")

        if not short_title:
            return

        disabled_languages = ctx.options.get("disabled_languages", "zh")
        if keep_original_title(lang, disabled_languages):
            return

        new_short_title = to_sentence_case(short_title, lang)

        if new_short_title != short_title:
            ctx.report(
                level=ReportLevel.INFO,
                message="短标题转换为 Sentence Case",
                action=f"{short_title} → {new_short_title}",
            )
            if "metadata" not in ctx.item:
                ctx.item["metadata"] = {}
            ctx.item["metadata"]["short_title"] = new_short_title

    async def prepare(self, ctx: Any) -> dict[str, Any] | bool:
        return {
            "disabled_languages": "zh,ja,ko",
            "custom_terms": [],
        }


# 注册规则
register_rule(CorrectTitleSentenceCase())
register_rule(CorrectShortTitleSentenceCase())
