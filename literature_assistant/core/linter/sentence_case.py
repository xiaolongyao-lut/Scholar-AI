# -*- coding: utf-8 -*-
"""Sentence Case 转换工具

参考 Zotero Format Metadata 插件的实现：
https://github.com/northword/zotero-format-metadata/blob/main/src/modules/rules/correct-title-sentence-case.ts

核心逻辑来自 Zotero.Utilities.sentenceCase，增强了对化学元素、专有名词的支持。
"""

import re
from typing import Optional

from .special_words import (
    ALL_SPECIAL_WORDS,
    CHEMICAL_ELEMENTS_FILTERED,
    FUNCTION_WORDS,
    LOCALITY_WORDS,
)


def escape_regex(text: str) -> str:
    """转义正则表达式特殊字符"""
    return re.escape(text)


def to_sentence_case(text: str, locale: str = "en-US") -> str:
    """转换为 Sentence Case

    Args:
        text: 输入文本
        locale: 语言区域（用于大小写转换）

    Returns:
        转换后的文本

    规则：
    1. 句首首字母大写
    2. Sub-sentence 开头（. ? ! 后）首字母大写
    3. 保护特殊标签内容（<nocase>, <sup>, <sub>, <i>, <b>）
    4. 保护化学元素
    5. 保护专有名词（国家、城市、月份等）
    6. 保护内部有大写的词（如 iPhone, LaTeX）
    7. 全大写文本转为小写（除了保护的词）
    """
    preserve: list[dict[str, int]] = []  # 需要保护的文本区间
    allcaps = text == text.upper()

    # 1. 保护 sub-sentence 开头（. ? ! 后的首字母）
    # 注意：Python re 不支持 \p{Lu}，需要用 [A-Z] 或其他方式
    for match in re.finditer(r'([.?!]\s+)(<[^>]+>)?([A-Z])', text):
        end, markup, char = match.groups()
        markup = markup or ""
        i = match.start()
        # 排除缩写（如 U.S.A.）
        prefix = text[:i + len(end)]
        if not re.search(r'([A-Z]\.){2,}$', prefix):
            start_pos = i + len(end) + len(markup)
            preserve.append({"start": start_pos, "end": start_pos + len(char)})

    # 2. 保护句首首字母
    match = re.match(r'^([""'']?)(<[^>]+>)?([A-Z])', text)
    if match:
        prefix, markup, char = match.groups()
        markup = markup or ""
        offset = len(prefix) + len(markup)
        preserve.append({"start": offset, "end": offset + len(char)})

    # 3. 保护 nocase 标签
    for match in re.finditer(r'<span class="nocase">.*?</span>|<nc>.*?</nc>', text, re.IGNORECASE):
        preserve.append({"start": match.start(), "end": match.end(), "description": "nocase"})

    # 4. 保护格式化标签内容（sup, sub, i, b, em, strong）
    for match in re.finditer(r'<(i|b|em|strong|sup|sub)(?:\s[^>]*)?>.*?</\1>', text, re.IGNORECASE):
        preserve.append({"start": match.start(), "end": match.end(), "description": "formatting-tag"})

    # 5. 用占位符遮罩 HTML 标签
    masked = text
    for match in re.finditer(r'<[^>]+>', text):
        preserve.append({"start": match.start(), "end": match.end(), "description": "markup"})
        masked = masked[:match.start()] + "�" * (match.end() - match.start()) + masked[match.end():]

    # 6. 处理词语转换
    def process_word(match: re.Match) -> str:
        word = match.group(0)

        # 全大写文本转小写
        if allcaps:
            return word.lower()

        # 去除占位符后的实际文本
        unmasked = word.replace("�", "")

        # 单字母 'A' 转小写
        if len(unmasked) == 1:
            return word.lower() if unmasked == "A" else word

        # 保护内部有大写的词（如 iPhone, LaTeX）
        if re.search(r'.[A-Z]', unmasked):
            return word

        # 保护标识符或全大写缩写（如 API, HTTP, DNA）
        # 标识符：字母+数字组合
        if re.match(r'^[a-zA-Z]+[0-9][a-zA-Z0-9]*$', unmasked):
            return word
        # 全大写缩写
        if re.match(r'^[A-Z0-9]+$', unmasked) and len(unmasked) > 1:
            return word

        # 保护化学元素
        if unmasked in CHEMICAL_ELEMENTS_FILTERED:
            return word

        # 其他词转小写
        return word.lower()

    # 匹配单词、复合词、缩写
    # 简化的模式：匹配字母、数字、占位符、连接符组成的词
    masked = re.sub(
        r'[�\w]+([�\w\-_]*)',
        process_word,
        masked,
    )

    # 7. 处理冒号/分号后的 'A'
    masked = re.sub(r'[;:]�*\s+�*A\s', lambda m: m.group(0).lower(), masked)
    # 处理破折号后的 'A'
    masked = re.sub(r'[–—]�*(?:\s+�*)?A\s', lambda m: m.group(0).lower(), masked)

    # 8. 保护 function word 后的专有名词
    # 构建特殊词汇的正则模式
    special_words_escaped = [escape_regex(w) for w in ALL_SPECIAL_WORDS]
    special_pattern = "|".join(special_words_escaped)

    if special_pattern:
        # 方法1: 直接匹配并保护所有专有名词（无论前面是否有 function word）
        for special_word in ALL_SPECIAL_WORDS:
            # 使用单词边界匹配
            pattern = r'\b' + re.escape(special_word) + r'\b'
            # 查找所有匹配位置
            for match in re.finditer(pattern, masked, re.IGNORECASE):
                # 恢复为正确的大小写
                start = match.start()
                end = match.end()
                masked = masked[:start] + special_word + masked[end:]

    # 9. 恢复保护的区间
    for region in preserve:
        start = region["start"]
        end = region["end"]
        masked = masked[:start] + text[start:end] + masked[end:]

    # 10. 确保首字母大写
    if masked and len(masked) > 0:
        # 找到第一个字母
        for i, char in enumerate(masked):
            if char.isalpha():
                if char.islower():
                    masked = masked[:i] + char.upper() + masked[i+1:]
                break

    return masked


def detect_case_style(text: str) -> str:
    """检测标题的大小写风格

    Returns:
        "title": Title Case（大部分词首字母大写）
        "sentence": Sentence case（只有首词大写）
        "original": 其他格式（混合或全小写）
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    words = text.split()
    if not words:
        return "original"

    # 只统计纯英文单词（忽略标点、数字、中文、单字母）
    english_words = [
        w for w in words
        if w and len(w) > 1 and w[0].isalpha() and any(c.isalpha() and c.islower() for c in w[1:])
    ]

    if not english_words:
        return "original"

    capitalized_count = sum(1 for w in english_words if w[0].isupper())

    # Sentence case: 只有第一个词大写
    if capitalized_count == 1 and english_words[0][0].isupper():
        return "sentence"

    # Title Case: 大部分词首字母大写（>= 60%）
    if capitalized_count >= len(english_words) * 0.6:
        return "title"

    return "original"


def keep_original_title(language: str, disabled_languages: str) -> bool:
    """判断是否保持原标题（不转换为 Sentence Case）

    Args:
        language: 文献语言（如 'zh-CN', 'en-US'）
        disabled_languages: 禁用语言列表（逗号分隔，如 'zh,ja,ko'）

    Returns:
        True 表示保持原样，False 表示需要转换
    """
    normalized_lang = language.lower()
    disabled_list = [
        item.strip().lower()
        for item in disabled_languages.split(",")
        if item.strip()
    ]

    for disabled in disabled_list:
        if normalized_lang == disabled or normalized_lang.startswith(f"{disabled}-"):
            return True

    return False
