# -*- coding: utf-8 -*-
"""日期格式规则：标准化为 ISO 8601"""

import re
from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule


# 月份映射
MONTH_NAMES = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}


def normalize_date(date_str: str) -> str | None:
    """尝试标准化日期为 ISO 8601 格式 (YYYY-MM-DD)

    支持格式：
    - "June 2024" -> "2024-06-01"
    - "2024-06" -> "2024-06-01"
    - "2024" -> "2024-01-01"
    - "06/15/2024" -> "2024-06-15"
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # 已经是 ISO 格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # 格式：YYYY-MM
    if re.match(r'^\d{4}-\d{2}$', date_str):
        return f"{date_str}-01"

    # 格式：YYYY
    if re.match(r'^\d{4}$', date_str):
        return f"{date_str}-01-01"

    # 格式：Month YYYY (e.g., "June 2024")
    match = re.match(r'^([a-zA-Z]+)\s+(\d{4})$', date_str)
    if match:
        month_name, year = match.groups()
        month_num = MONTH_NAMES.get(month_name.lower())
        if month_num:
            return f"{year}-{month_num}-01"

    # 格式：MM/DD/YYYY
    match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if match:
        month, day, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # 格式：DD/MM/YYYY (欧洲格式，不确定，返回 None)
    # 格式：YYYY/MM/DD
    match = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', date_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return None


class CorrectDateFormat(FieldRule):
    """标准化日期格式"""

    def __init__(self):
        super().__init__(
            rule_id="correct-date-format",
            target_field="publication_date",
            name="标准化日期格式",
            description="将日期转换为 ISO 8601 格式（YYYY-MM-DD）",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        # 从多个可能的位置获取日期
        date = ctx.item.get("publication_date")
        if not date:
            metadata = ctx.item.get("metadata", {})
            date = metadata.get("publication_date") or metadata.get("date")

        if not date:
            return

        date_str = str(date).strip()
        normalized = normalize_date(date_str)

        if normalized and normalized != date_str:
            ctx.report(
                level=ReportLevel.INFO,
                message="日期格式已标准化",
                action=f"{date_str} → {normalized}",
            )
            # 更新所有可能的字段
            if "publication_date" in ctx.item:
                ctx.item["publication_date"] = normalized
            if "metadata" in ctx.item and isinstance(ctx.item["metadata"], dict):
                if "publication_date" in ctx.item["metadata"]:
                    ctx.item["metadata"]["publication_date"] = normalized
                if "date" in ctx.item["metadata"]:
                    ctx.item["metadata"]["date"] = normalized

                # 同时更新年份字段
                year = int(normalized.split("-")[0])
                ctx.item["metadata"]["year"] = year


# 注册规则
register_rule(CorrectDateFormat())
