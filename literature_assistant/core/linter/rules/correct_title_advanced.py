# -*- coding: utf-8 -*-
"""标题高级规则"""

from literature_assistant.core.linter.rule_base import FieldRule, ApplyContext, ReportLevel, register_rule


class NoTitleCapitalization(FieldRule):
    """禁止全大写标题"""

    def __init__(self):
        super().__init__(
            rule_id="no-title-capitalization",
            target_field="title",
            name="禁止全大写标题",
            description="检测并修复全大写的标题",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        title = ctx.item.get("title", "")
        if not title or not isinstance(title, str) or len(title) < 10:
            return

        # 检查是否全大写（忽略标点和数字）
        letters = [c for c in title if c.isalpha()]
        if not letters:
            return

        upper_count = sum(1 for c in letters if c.isupper())
        if upper_count / len(letters) > 0.8:  # 80%以上是大写
            # 转换为 Title Case
            normalized = title.title()
            ctx.report(
                level=ReportLevel.INFO,
                message="全大写标题已转换",
                action=f"{title[:30]}... → {normalized[:30]}...",
            )
            ctx.item["title"] = normalized


class CorrectTitlePunctuation(FieldRule):
    """修复标题标点"""

    def __init__(self):
        super().__init__(
            rule_id="correct-title-punctuation",
            target_field="title",
            name="标题标点修复",
            description="去除标题末尾的句号",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        title = ctx.item.get("title", "")
        if not title or not isinstance(title, str):
            return

        # 去除末尾句号
        if title.endswith('.') and not title.endswith('...'):
            normalized = title.rstrip('.')
            ctx.report(
                level=ReportLevel.INFO,
                message="已去除标题末尾句号",
                action=f"{title} → {normalized}",
            )
            ctx.item["title"] = normalized


# 注册规则
register_rule(NoTitleCapitalization())
register_rule(CorrectTitlePunctuation())
