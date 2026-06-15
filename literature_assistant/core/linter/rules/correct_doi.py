# -*- coding: utf-8 -*-
"""DOI 规则：去除前缀、格式标准化"""

import re
from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule


def normalize_doi(doi: str) -> str:
    """标准化 DOI 格式：去除 https://doi.org/ 前缀"""
    if not doi:
        return doi

    # 去除常见前缀
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi, flags=re.IGNORECASE)
    doi = re.sub(r'^doi:\s*', '', doi, flags=re.IGNORECASE)

    return doi.strip()


class NoDOIPrefix(FieldRule):
    """去除 DOI 的 URL 前缀"""

    def __init__(self):
        super().__init__(
            rule_id="no-doi-prefix",
            target_field="doi",
            name="去除 DOI 前缀",
            description="移除 DOI 的 https://doi.org/ 前缀，保留纯 DOI",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        # 从多个可能的位置获取 DOI
        doi = ctx.item.get("doi")
        if not doi:
            metadata = ctx.item.get("metadata", {})
            doi = metadata.get("doi") or metadata.get("DOI")

        if not doi:
            return

        normalized = normalize_doi(str(doi))
        if normalized != str(doi):
            ctx.report(
                level=ReportLevel.INFO,
                message="DOI 包含 URL 前缀",
                action=f"{doi} → {normalized}",
            )
            # 更新所有可能的字段
            if "doi" in ctx.item:
                ctx.item["doi"] = normalized
            if "metadata" in ctx.item and isinstance(ctx.item["metadata"], dict):
                if "doi" in ctx.item["metadata"]:
                    ctx.item["metadata"]["doi"] = normalized
                if "DOI" in ctx.item["metadata"]:
                    ctx.item["metadata"]["DOI"] = normalized


class ValidateDOIFormat(FieldRule):
    """验证 DOI 格式是否规范"""

    def __init__(self):
        super().__init__(
            rule_id="validate-doi-format",
            target_field="doi",
            name="验证 DOI 格式",
            description="检查 DOI 是否符合标准格式（10.xxxx/xxx）",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        doi = ctx.item.get("doi")
        if not doi:
            metadata = ctx.item.get("metadata", {})
            doi = metadata.get("doi") or metadata.get("DOI")

        if not doi:
            return

        doi_str = str(doi).strip()

        # DOI 应该以 10. 开头
        if not re.match(r'^10\.\d{4,9}/[^\s]+$', doi_str):
            ctx.report(
                level=ReportLevel.WARNING,
                message="DOI 格式不规范（应为 10.xxxx/xxx）",
                action=None,  # 无自动修复建议
            )


# 注册规则
register_rule(NoDOIPrefix())
register_rule(ValidateDOIFormat())
