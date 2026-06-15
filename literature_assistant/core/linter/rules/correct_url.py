# -*- coding: utf-8 -*-
"""URL 和文献类型规则"""

import re
from literature_assistant.core.linter.rule_base import FieldRule, ItemRule, ApplyContext, ReportLevel, register_rule


class NoUrlInTitle(FieldRule):
    """标题中不应有 URL"""

    URL_PATTERN = re.compile(r'https?://|www\.|\.com|\.org|\.net|\.edu')

    def __init__(self):
        super().__init__(
            rule_id="no-url-in-title",
            target_field="title",
            name="标题不应含 URL",
            description="检查标题中是否包含 URL",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        for field in ["title", "title_en"]:
            title = ctx.item.get(field, "")
            if not title or not isinstance(title, str):
                continue

            if self.URL_PATTERN.search(title):
                ctx.report(
                    level=ReportLevel.WARNING,
                    message=f"{field} 包含 URL",
                    action=f"{title[:50]}...",
                )


class ValidateUrlFormat(FieldRule):
    """验证 URL 格式"""

    URL_PATTERN = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            rule_id="validate-url-format",
            target_field="url",
            name="验证 URL 格式",
            description="检查 URL 是否符合标准格式",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        url = ctx.item.get("metadata", {}).get("url", "")

        if not url or not isinstance(url, str):
            return

        if not self.URL_PATTERN.match(url):
            ctx.report(
                level=ReportLevel.ERROR,
                message="URL 格式不正确",
                action=f"{url}",
            )


class RequireItemType(ItemRule):
    """要求文献类型"""

    VALID_TYPES = {
        "journal-article",
        "book",
        "book-chapter",
        "conference-paper",
        "thesis",
        "report",
        "patent",
        "webpage",
        "dataset",
        "software",
    }

    def __init__(self):
        super().__init__(
            rule_id="require-item-type",
            name="要求文献类型",
            description="检查文献是否有类型字段",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        item_type = ctx.item.get("metadata", {}).get("itemType")

        if not item_type:
            ctx.report(
                level=ReportLevel.WARNING,
                message="缺少文献类型",
                action="建议添加 itemType 字段",
            )
        elif item_type not in self.VALID_TYPES:
            ctx.report(
                level=ReportLevel.WARNING,
                message="文献类型不在标准列表中",
                action=f"{item_type} (标准类型: {', '.join(sorted(self.VALID_TYPES))})",
            )


# 注册规则
register_rule(NoUrlInTitle())
register_rule(ValidateUrlFormat())
register_rule(RequireItemType())
