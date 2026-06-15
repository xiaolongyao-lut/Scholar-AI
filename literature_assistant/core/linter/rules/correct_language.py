# -*- coding: utf-8 -*-
"""语言检测和标准化规则"""

import re
from literature_assistant.core.linter.rule_base import ItemRule, ApplyContext, ReportLevel, register_rule


class RequireLanguage(ItemRule):
    """自动检测并添加语言字段

    基于标题文本检测语言：
    - 中文
    - 英文
    - 日文
    - 韩文
    """

    def __init__(self):
        super().__init__(
            rule_id="require-language",
            name="自动检测语言",
            description="基于标题自动检测并添加语言字段",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        current_lang = metadata.get("language")

        # 如果已有语言且不为空，跳过
        if current_lang and isinstance(current_lang, str) and current_lang.strip():
            return

        # 获取标题用于检测
        title = ctx.item.get("title_en") or ctx.item.get("title", "")
        if not title or not isinstance(title, str):
            return

        # 检测语言
        detected = detect_language(title)

        if detected:
            ctx.report(
                level=ReportLevel.INFO,
                message=f"检测到语言: {detected}",
                action=f"添加语言字段",
            )
            if "metadata" not in ctx.item:
                ctx.item["metadata"] = {}
            ctx.item["metadata"]["language"] = detected


class CorrectLanguageCode(ItemRule):
    """语言代码标准化

    标准化为 BCP 47 格式：
    - zh → zh-CN
    - en → en-US
    - ja → ja-JP
    - ko → ko-KR
    """

    # 语言代码映射
    LANGUAGE_MAP = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "chinese": "zh-CN",
        "en": "en-US",
        "english": "en-US",
        "ja": "ja-JP",
        "japanese": "ja-JP",
        "ko": "ko-KR",
        "korean": "ko-KR",
    }

    def __init__(self):
        super().__init__(
            rule_id="correct-language-code",
            name="语言代码标准化",
            description="标准化语言代码为 BCP 47 格式",
        )

    async def apply(self, ctx: ApplyContext) -> None:
        metadata = ctx.item.get("metadata", {})
        current_lang = metadata.get("language")

        if not current_lang or not isinstance(current_lang, str):
            return

        # 标准化
        normalized = self.LANGUAGE_MAP.get(current_lang.lower())

        if normalized and normalized != current_lang:
            ctx.report(
                level=ReportLevel.INFO,
                message="语言代码已标准化",
                action=f"{current_lang} → {normalized}",
            )
            ctx.item["metadata"]["language"] = normalized


def detect_language(text: str) -> str | None:
    """检测文本语言

    Returns:
        语言代码（zh-CN, en-US, ja-JP, ko-KR）或 None
    """
    if not text:
        return None

    # 统计各种字符
    chinese_count = len(re.findall(r'[一-鿿]', text))
    japanese_count = len(re.findall(r'[぀-ゟ゠-ヿ]', text))  # 平假名 + 片假名
    korean_count = len(re.findall(r'[가-힯]', text))
    english_count = len(re.findall(r'[a-zA-Z]', text))

    total = len(text)
    if total == 0:
        return None

    # 计算比例
    chinese_ratio = chinese_count / total
    japanese_ratio = japanese_count / total
    korean_ratio = korean_count / total
    english_ratio = english_count / total

    # 优先级：中文 > 日文 > 韩文 > 英文
    if chinese_ratio > 0.3:
        return "zh-CN"
    if japanese_ratio > 0.2:
        return "ja-JP"
    if korean_ratio > 0.3:
        return "ko-KR"
    if english_ratio > 0.5:
        return "en-US"

    return None


# 注册规则
register_rule(RequireLanguage())
register_rule(CorrectLanguageCode())
