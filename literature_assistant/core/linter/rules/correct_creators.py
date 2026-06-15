# -*- coding: utf-8 -*-
"""作者名格式规则"""

import re
from typing import Any

from ..rule_base import ApplyContext, FieldRule, ReportLevel, register_rule


def to_title_case_name(name: str) -> str:
    """将作者名转换为首字母大写"""
    words = name.split()
    return " ".join(word.capitalize() for word in words)


def normalize_author_format(name: str) -> str:
    """标准化作者名格式为 'Last, First' 或首字母大写"""
    name = name.strip()

    # 如果已经是 'Last, First' 格式，只需首字母大写
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        return ', '.join(to_title_case_name(p) for p in parts if p)

    # 简单的首字母大写
    return to_title_case_name(name)


class CorrectCreatorsCase(FieldRule):
    """标准化作者名大小写"""

    def __init__(self):
        super().__init__(
            rule_id="correct-creators-case",
            target_field="authors",
            name="标准化作者名大小写",
            description="确保作者名使用首字母大写格式",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        # 从多个位置获取作者
        authors = ctx.item.get("authors")
        if not authors:
            metadata = ctx.item.get("metadata", {})
            authors = metadata.get("authors")

        if not authors or not isinstance(authors, list):
            return

        normalized_authors = []
        changed = False

        for i, author in enumerate(authors):
            if not author:
                continue

            author_str = str(author)
            normalized = normalize_author_format(author_str)

            if normalized != author_str:
                ctx.report(
                    level=ReportLevel.INFO,
                    message=f"作者名 [{i}] 格式已标准化",
                    action=f"{author_str} → {normalized}",
                )
                changed = True

            normalized_authors.append(normalized)

        if changed:
            # 更新所有可能的字段
            if "authors" in ctx.item:
                ctx.item["authors"] = normalized_authors
            if "metadata" in ctx.item and isinstance(ctx.item["metadata"], dict):
                if "authors" in ctx.item["metadata"]:
                    ctx.item["metadata"]["authors"] = normalized_authors


class CorrectCreatorsPinyin(FieldRule):
    """中文拼音拆分（Zhang Jianbei → Zhang Jian Bei）"""

    def __init__(self):
        super().__init__(
            rule_id="correct-creators-pinyin",
            target_field="authors",
            name="中文拼音拆分",
            description="将连写的中文拼音拆分为独立音节",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        # 从多个位置获取作者
        authors = ctx.item.get("authors")
        if not authors:
            metadata = ctx.item.get("metadata", {})
            authors = metadata.get("authors")

        if not authors or not isinstance(authors, list):
            return

        normalized_authors = []
        changed = False

        for i, author in enumerate(authors):
            if not author:
                continue

            author_str = str(author)
            normalized = self._split_pinyin(author_str)

            if normalized != author_str:
                ctx.report(
                    level=ReportLevel.INFO,
                    message=f"作者名 [{i}] 拼音已拆分",
                    action=f"{author_str} → {normalized}",
                )
                changed = True

            normalized_authors.append(normalized)

        if changed:
            if "authors" in ctx.item:
                ctx.item["authors"] = normalized_authors
            if "metadata" in ctx.item and isinstance(ctx.item["metadata"], dict):
                if "authors" in ctx.item["metadata"]:
                    ctx.item["metadata"]["authors"] = normalized_authors

    def _split_pinyin(self, name: str) -> str:
        """简单的拼音拆分逻辑

        检测模式：姓 + 连续小写字母（>3个） → 姓 + 拆分后的名
        例如：Zhang Jianbei → Zhang Jian Bei
        """
        # 匹配：首字母大写 + 空格 + 连续小写字母（>4个）
        match = re.match(r'^([A-Z][a-z]+)\s+([a-z]{5,})$', name)
        if match:
            last_name, given_name = match.groups()
            # 简单拆分：每2-3个字母为一个音节
            # 这里用简化规则，实际应该用拼音词典
            syllables = []
            i = 0
            while i < len(given_name):
                # 尝试3个字母
                if i + 3 <= len(given_name):
                    syllables.append(given_name[i:i+3].capitalize())
                    i += 3
                elif i + 2 <= len(given_name):
                    syllables.append(given_name[i:i+2].capitalize())
                    i += 2
                else:
                    syllables.append(given_name[i:].capitalize())
                    i = len(given_name)

            return f"{last_name} {' '.join(syllables)}"

        return name


# 注册规则
register_rule(CorrectCreatorsCase())
register_rule(CorrectCreatorsPinyin())
