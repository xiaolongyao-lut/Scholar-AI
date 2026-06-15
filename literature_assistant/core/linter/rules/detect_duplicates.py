# -*- coding: utf-8 -*-
"""重复检测规则"""

from literature_assistant.core.linter.rule_base import ItemRule, PrepareContext, ApplyContext, ReportLevel, register_rule


class NoDuplicateDoi(ItemRule):
    """重复 DOI 检测"""

    def __init__(self):
        super().__init__(
            rule_id="no-duplicate-doi",
            name="检测重复 DOI",
            description="检测项目内是否有重复的 DOI",
        )

    async def prepare(self, ctx: PrepareContext) -> dict:
        """构建 DOI 索引"""
        doi_index = {}
        for item in ctx.items:
            doi = item.get("metadata", {}).get("doi", "")
            if doi and isinstance(doi, str):
                doi = doi.strip().lower()
                if doi not in doi_index:
                    doi_index[doi] = []
                doi_index[doi].append(item.get("material_id"))

        return {"doi_index": doi_index}

    async def apply(self, ctx: ApplyContext) -> None:
        doi = ctx.item.get("metadata", {}).get("doi", "")
        if not doi or not isinstance(doi, str):
            return

        doi = doi.strip().lower()
        doi_index = ctx.options.get("doi_index", )
        material_ids = doi_index.get(doi, [])

        if len(material_ids) > 1:
            ctx.report(
                level=ReportLevel.WARNING,
                message="发现重复 DOI",
                action=f"DOI: {doi}，共 {len(material_ids)} 条文献",
            )


class NoItemDuplication(ItemRule):
    """重复文献检测（基于标题相似度）"""

    def __init__(self):
        super().__init__(
            rule_id="no-item-duplication",
            name="检测重复文献",
            description="基于标题相似度检测重复文献",
        )

    async def prepare(self, ctx: PrepareContext) -> dict:
        """构建标题索引"""
        title_index = {}
        for item in ctx.items:
            title = item.get("title_en") or item.get("title", "")
            if title and isinstance(title, str):
                # 标准化标题用于比较
                normalized = title.strip().lower()
                if normalized not in title_index:
                    title_index[normalized] = []
                title_index[normalized].append(item.get("material_id"))

        return {"title_index": title_index}

    async def apply(self, ctx: ApplyContext) -> None:
        title = ctx.item.get("title_en") or ctx.item.get("title", "")
        if not title or not isinstance(title, str):
            return

        normalized = title.strip().lower()
        title_index = ctx.options.get("title_index", {})
        material_ids = title_index.get(normalized, [])

        if len(material_ids) > 1:
            ctx.report(
                level=ReportLevel.WARNING,
                message="发现疑似重复文献",
                action=f"标题相同，共 {len(material_ids)} 条",
            )


# 注册规则
register_rule(NoDuplicateDoi())
register_rule(NoItemDuplication())
