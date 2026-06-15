# -*- coding: utf-8 -*-
"""日期高级规则"""

from datetime import datetime
from literature_assistant.core.linter.rule_base import FieldRule, ApplyContext, ReportLevel, register_rule


class RequirePublicationDate(FieldRule):
    """要求发布日期"""

    def __init__(self):
        super().__init__(
            rule_id="require-publication-date",
            target_field="date",
            name="要求发布日期",
            description="检查文献是否有发布日期",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        date = ctx.item.get("metadata", {}).get("date") or ctx.item.get("metadata", {}).get("year")

        if not date:
            ctx.report(
                level=ReportLevel.WARNING,
                message="缺少发布日期",
                action="建议添加日期字段",
            )


class ValidateDateRange(FieldRule):
    """验证日期范围"""

    def __init__(self):
        super().__init__(
            rule_id="validate-date-range",
            target_field="date",
            name="验证日期范围",
            description="检查日期是否在合理范围内",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        date_str = ctx.item.get("metadata", {}).get("date", "")
        if not date_str or not isinstance(date_str, str):
            return

        try:
            # 尝试解析日期
            if len(date_str) == 4 and date_str.isdigit():  # 只有年份
                year = int(date_str)
            elif '-' in date_str:  # ISO 格式
                date_obj = datetime.fromisoformat(date_str.split('T')[0])
                year = date_obj.year
            else:
                return

            current_year = datetime.now().year

            # 检查范围
            if year > current_year:
                ctx.report(
                    level=ReportLevel.ERROR,
                    message="日期不能是未来",
                    action=f"{date_str} (当前年份: {current_year})",
                )
            elif year < 1000:
                ctx.report(
                    level=ReportLevel.ERROR,
                    message="日期过早",
                    action=f"{date_str} (应大于 1000 年)",
                )

        except (ValueError, AttributeError):
            pass  # 日期格式不正确，由其他规则处理


# 注册规则
register_rule(RequirePublicationDate())
register_rule(ValidateDateRange())
