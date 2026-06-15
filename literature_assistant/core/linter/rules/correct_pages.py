# -*- coding: utf-8 -*-
"""页码范围和格式规则"""

import re
from literature_assistant.core.linter.rule_base import FieldRule, ApplyContext, ReportLevel, register_rule


class CorrectPagesRange(FieldRule):
    """标准化页码范围（使用 en dash）

    示例：
    - "100-110" → "100–110" (hyphen → en dash)
    - "100 - 110" → "100–110"
    - "100 -- 110" → "100–110"
    """

    def __init__(self):
        super().__init__(
            rule_id="correct-pages-range",
            target_field="pages",
            name="页码范围标准化",
            description="将页码范围的分隔符统一为 en dash",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        pages = ctx.item.get("metadata", {}).get("pages", "")
        if not pages or not isinstance(pages, str):
            return

        # 匹配页码范围：数字 + 分隔符 + 数字
        # 支持: hyphen (-), double hyphen (--), 空格分隔
        pattern = r'(\d+)\s*(?:-{1,2}|–|—)\s*(\d+)'
        match = re.search(pattern, pages)

        if match:
            start, end = match.groups()
            # 使用 en dash (U+2013)
            normalized = f"{start}–{end}"

            if normalized != pages:
                ctx.report(
                    level=ReportLevel.INFO,
                    message="页码范围已标准化",
                    action=f"{pages} → {normalized}",
                )
                if "metadata" not in ctx.item:
                    ctx.item["metadata"] = {}
                ctx.item["metadata"]["pages"] = normalized


class ValidatePagesFormat(FieldRule):
    """验证页码格式

    检查：
    - 页码必须是数字
    - 起始页必须小于结束页
    """

    def __init__(self):
        super().__init__(
            rule_id="validate-pages-format",
            target_field="pages",
            name="验证页码格式",
            description="检查页码是否为有效的数字或范围",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        pages = ctx.item.get("metadata", {}).get("pages", "")
        if not pages or not isinstance(pages, str):
            return

        # 匹配页码范围
        pattern = r'(\d+)\s*[–—-]+\s*(\d+)'
        match = re.search(pattern, pages)

        if match:
            start_str, end_str = match.groups()
            start = int(start_str)
            end = int(end_str)

            if start >= end:
                ctx.report(
                    level=ReportLevel.ERROR,
                    message="起始页码必须小于结束页码",
                    action=f"{pages} (起始: {start}, 结束: {end})",
                )
        else:
            # 检查是否是单页码
            if not re.match(r'^\d+$', pages.strip()):
                ctx.report(
                    level=ReportLevel.WARNING,
                    message="页码格式不正确",
                    action=f"{pages} (应为数字或范围，如 '100' 或 '100–110')",
                )


# 注册规则
register_rule(CorrectPagesRange())
register_rule(ValidatePagesFormat())
