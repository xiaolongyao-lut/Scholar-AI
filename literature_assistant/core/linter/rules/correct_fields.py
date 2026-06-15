# -*- coding: utf-8 -*-
"""字段通用规则"""

from literature_assistant.core.linter.rule_base import ItemRule, ApplyContext, ReportLevel, register_rule


class NoEmptyFields(ItemRule):
    """删除空字段"""

    def __init__(self):
        super().__init__(
            rule_id="no-empty-fields",
            name="删除空字段",
            description="删除空字符串和空数组字段",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        if not metadata:
            return

        empty_fields = []
        for key, value in list(metadata.items()):
            # 检查是否为空
            if value == "" or value == [] or value is None:
                empty_fields.append(key)
                del metadata[key]

        if empty_fields:
            ctx.report(
                level=ReportLevel.INFO,
                message=f"删除了 {len(empty_fields)} 个空字段",
                action=f"字段: {', '.join(empty_fields)}",
            )


class CorrectFieldWhitespace(ItemRule):
    """清理所有字段空格"""

    def __init__(self):
        super().__init__(
            rule_id="correct-field-whitespace",
            name="清理字段空格",
            description="清理所有文本字段的多余空格",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        import re

        def clean_whitespace(text: str) -> str:
            """标准化空格"""
            return re.sub(r'\s+', ' ', text).strip()

        metadata = ctx.item.get("metadata", {})
        if not metadata:
            return

        cleaned_count = 0
        for key, value in metadata.items():
            if isinstance(value, str) and value:
                cleaned = clean_whitespace(value)
                if cleaned != value:
                    metadata[key] = cleaned
                    cleaned_count += 1

        # 清理顶级字段
        for field in ["title", "title_en"]:
            if field in ctx.item and isinstance(ctx.item[field], str):
                original = ctx.item[field]
                cleaned = clean_whitespace(original)
                if cleaned != original:
                    ctx.item[field] = cleaned
                    cleaned_count += 1

        if cleaned_count > 0:
            ctx.report(
                level=ReportLevel.INFO,
                message=f"清理了 {cleaned_count} 个字段的空格",
                action="",
            )


# 注册规则
register_rule(NoEmptyFields())
register_rule(CorrectFieldWhitespace())
