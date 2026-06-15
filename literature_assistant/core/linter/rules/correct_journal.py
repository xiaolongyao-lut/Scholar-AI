# -*- coding: utf-8 -*-
"""期刊名称规则"""

from literature_assistant.core.linter.rule_base import FieldRule, ApplyContext, ReportLevel, register_rule
from literature_assistant.core.linter.sentence_case import to_sentence_case


class CorrectPublicationTitleCase(FieldRule):
    """期刊名大小写标准化

    使用 Title Case：
    - SCIENCE → Science
    - nature methods → Nature Methods
    """

    def __init__(self):
        super().__init__(
            rule_id="correct-publication-title-case",
            target_field="journal",
            name="期刊名大小写",
            description="将期刊名转换为 Title Case",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        journal = metadata.get("publicationTitle") or metadata.get("journal", "")

        if not journal or not isinstance(journal, str):
            return

        # 检查是否全大写
        if journal == journal.upper() and len(journal) > 3:
            # 转换为 Title Case
            normalized = to_title_case(journal)

            ctx.report(
                level=ReportLevel.INFO,
                message="期刊名已转换为 Title Case",
                action=f"{journal[:30]}... → {normalized[:30]}...",
            )

            if "publicationTitle" in metadata:
                ctx.item["metadata"]["publicationTitle"] = normalized
            elif "journal" in metadata:
                ctx.item["metadata"]["journal"] = normalized


class CorrectPublicationTitleAlias(FieldRule):
    """期刊别名标准化

    常见期刊缩写 → 全称：
    - J. Am. Chem. Soc. → Journal of the American Chemical Society
    - Nat. Methods → Nature Methods
    """

    # 常见期刊缩写映射（示例）
    JOURNAL_ALIASES = {
        "J. Am. Chem. Soc.": "Journal of the American Chemical Society",
        "JACS": "Journal of the American Chemical Society",
        "Nat. Methods": "Nature Methods",
        "Nat. Commun.": "Nature Communications",
        "Proc. Natl. Acad. Sci.": "Proceedings of the National Academy of Sciences",
        "PNAS": "Proceedings of the National Academy of Sciences",
        "Phys. Rev. Lett.": "Physical Review Letters",
        "PRL": "Physical Review Letters",
        "J. Phys. Chem.": "Journal of Physical Chemistry",
        "Angew. Chem.": "Angewandte Chemie",
        "Chem. Rev.": "Chemical Reviews",
        "Acc. Chem. Res.": "Accounts of Chemical Research",
    }

    def __init__(self):
        super().__init__(
            rule_id="correct-publication-title-alias",
            target_field="journal",
            name="期刊别名",
            description="将期刊缩写展开为全称",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        journal = metadata.get("publicationTitle") or metadata.get("journal", "")

        if not journal or not isinstance(journal, str):
            return

        # 查找别名
        full_name = self.JOURNAL_ALIASES.get(journal.strip())

        if full_name:
            ctx.report(
                level=ReportLevel.INFO,
                message="期刊缩写已展开",
                action=f"{journal} → {full_name}",
            )

            if "publicationTitle" in metadata:
                ctx.item["metadata"]["publicationTitle"] = full_name
            elif "journal" in metadata:
                ctx.item["metadata"]["journal"] = full_name


def to_title_case(text: str) -> str:
    """转换为 Title Case

    每个单词首字母大写，但保留特殊词（of, and, the 等）小写
    """
    # 小写词列表（介词、连词、冠词）
    small_words = {
        'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for',
        'in', 'of', 'on', 'or', 'the', 'to', 'with'
    }

    words = text.lower().split()
    result = []

    for i, word in enumerate(words):
        # 第一个词和最后一个词总是大写
        # 或者不在小写词列表中的词
        if i == 0 or i == len(words) - 1 or word not in small_words:
            result.append(word.capitalize())
        else:
            result.append(word)

    return ' '.join(result)


# 注册规则
register_rule(CorrectPublicationTitleCase())
register_rule(CorrectPublicationTitleAlias())
