# -*- coding: utf-8 -*-
"""作者相关高级规则"""

from literature_assistant.core.linter.rule_base import ItemRule, ApplyContext, ReportLevel, register_rule


class RequireCreators(ItemRule):
    """要求至少一个作者"""

    def __init__(self):
        super().__init__(
            rule_id="require-creators",
            name="要求作者",
            description="检查文献是否有作者信息",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        authors = ctx.item.get("metadata", {}).get("authors", [])

        if not authors or len(authors) == 0:
            ctx.report(
                level=ReportLevel.WARNING,
                message="缺少作者信息",
                action="建议添加至少一个作者",
            )


class CorrectCreatorsDuplicates(ItemRule):
    """删除重复作者"""

    def __init__(self):
        super().__init__(
            rule_id="correct-creators-duplicates",
            name="删除重复作者",
            description="检测并删除重复的作者",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        authors = metadata.get("authors", [])

        if not authors or len(authors) < 2:
            return

        # 标准化作者名用于比较
        seen = set()
        unique_authors = []

        for author in authors:
            # 简单标准化：去除空格，转小写
            normalized = author.strip().lower() if isinstance(author, str) else str(author)

            if normalized not in seen:
                seen.add(normalized)
                unique_authors.append(author)

        if len(unique_authors) < len(authors):
            removed_count = len(authors) - len(unique_authors)
            ctx.report(
                level=ReportLevel.INFO,
                message=f"删除了 {removed_count} 个重复作者",
                action=f"原 {len(authors)} 个 → {len(unique_authors)} 个",
            )
            ctx.item["metadata"]["authors"] = unique_authors


# 注册规则
register_rule(RequireCreators())
register_rule(CorrectCreatorsDuplicates())
