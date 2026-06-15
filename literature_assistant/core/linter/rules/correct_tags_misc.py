# -*- coding: utf-8 -*-
"""标签和其他规则"""

from literature_assistant.core.linter.rule_base import ItemRule, FieldRule, ApplyContext, ReportLevel, register_rule


class NormalizeTags(ItemRule):
    """标签标准化"""

    def __init__(self):
        super().__init__(
            rule_id="normalize-tags",
            name="标签标准化",
            description="统一标签大小写并删除重复",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        tags = ctx.item.get("metadata", {}).get("tags", [])
        if not tags or not isinstance(tags, list):
            return

        # 标准化：首字母大写
        normalized_tags = []
        seen = set()

        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                continue

            # 标准化
            normalized = tag.strip().capitalize()

            # 去重
            if normalized.lower() not in seen:
                seen.add(normalized.lower())
                normalized_tags.append(normalized)

        if len(normalized_tags) != len(tags):
            ctx.report(
                level=ReportLevel.INFO,
                message="标签已标准化",
                action=f"原 {len(tags)} 个 → {len(normalized_tags)} 个",
            )
            ctx.item["metadata"]["tags"] = normalized_tags


class ValidateIssnIsbn(FieldRule):
    """验证 ISSN/ISBN"""

    def __init__(self):
        super().__init__(
            rule_id="validate-issn-isbn",
            target_field="issn",
            name="验证 ISSN/ISBN",
            description="验证 ISSN 和 ISBN 格式",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        import re

        # 检查 ISSN
        issn = ctx.item.get("metadata", {}).get("issn", "")
        if issn and isinstance(issn, str):
            # ISSN 格式: XXXX-XXXX
            if not re.match(r'^\d{4}-\d{3}[\dX]$', issn):
                ctx.report(
                    level=ReportLevel.WARNING,
                    message="ISSN 格式不正确",
                    action=f"{issn} (应为 XXXX-XXXX 格式)",
                )

        # 检查 ISBN
        isbn = ctx.item.get("metadata", {}).get("isbn", "")
        if isbn and isinstance(isbn, str):
            # ISBN 格式: ISBN-10 或 ISBN-13
            isbn_clean = isbn.replace('-', '').replace(' ', '')
            if not (re.match(r'^\d{9}[\dX]$', isbn_clean) or re.match(r'^\d{13}$', isbn_clean)):
                ctx.report(
                    level=ReportLevel.WARNING,
                    message="ISBN 格式不正确",
                    action=f"{isbn} (应为 10 或 13 位)",
                )


# 注册规则
register_rule(NormalizeTags())
register_rule(ValidateIssnIsbn())
