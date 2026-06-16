# -*- coding: utf-8 -*-
"""摘要智能提取服务

从 PDF 文本中智能提取 Abstract/摘要，替代简单的前 200 字截断。
"""

from __future__ import annotations

import re
from typing import Optional


__all__ = ["extract_abstract", "extract_abstract_enhanced"]


def extract_abstract(text: str, max_length: int = 500) -> str:
    """基础版：智能提取摘要

    优先提取 Abstract 章节，失败则智能截取前 N 字。

    Args:
        text: PDF 全文
        max_length: 最大长度（字符数）

    Returns:
        提取的摘要文本
    """
    if not text or not text.strip():
        return ""

    # 1. 尝试提取 Abstract 章节（英文）
    patterns_en = [
        r"(?i)\bAbstract\b[:\s]*\n(.{100,2000}?)(?:\n\n|\n[A-Z]|Introduction|Keywords)",
        r"(?i)\bAbstract\b[:\s]*(.{100,2000}?)(?:\n\n|\nIntroduction|\nKeywords)",
    ]

    for pattern in patterns_en:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # 清理多余空白
            abstract = re.sub(r"\s+", " ", abstract)
            return abstract[:max_length]

    # 2. 尝试提取摘要章节（中文）
    patterns_zh = [
        r"摘\s*要[：:\s]*\n(.{100,2000}?)(?:\n\n|关键词|引言)",
        r"摘\s*要[：:\s]*(.{100,2000}?)(?:\n\n|关键词|引言)",
    ]

    for pattern in patterns_zh:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            abstract = re.sub(r"\s+", " ", abstract)
            return abstract[:max_length]

    # 3. Fallback：智能截取前 N 字（按段落）
    return _smart_truncate(text, max_length)


def _smart_truncate(text: str, max_length: int) -> str:
    """智能截断：按段落边界截取"""
    paragraphs = text.split("\n\n")
    content = []
    current_length = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 跳过标题类段落（全大写、很短）
        if len(para) < 20 or para.isupper():
            continue

        if current_length + len(para) > max_length:
            # 最后一个段落截断
            remaining = max_length - current_length
            if remaining > 50:  # 至少保留 50 字
                content.append(para[:remaining] + "...")
            break

        content.append(para)
        current_length += len(para)

    return "\n\n".join(content)


def extract_abstract_enhanced(
    text: str,
    metadata: Optional[dict] = None,
    max_length: int = 500,
) -> dict:
    """增强版：提取摘要 + 元数据

    返回结构化信息：摘要、来源、置信度。

    Args:
        text: PDF 全文
        metadata: PDF 元数据（可选）
        max_length: 最大长度

    Returns:
        {
            "abstract": str,      # 摘要文本
            "source": str,        # 来源（"abstract" | "fallback"）
            "confidence": float,  # 置信度（0-1）
            "language": str,      # 语言（"en" | "zh" | "mixed"）
        }
    """
    abstract = extract_abstract(text, max_length)

    # 检测来源
    if re.search(r"(?i)\bAbstract\b", text[:2000]):
        source = "abstract"
        confidence = 0.9
    elif re.search(r"摘\s*要", text[:2000]):
        source = "abstract"
        confidence = 0.85
    else:
        source = "fallback"
        confidence = 0.5

    # 检测语言
    zh_count = len(re.findall(r"[一-鿿]", abstract))
    en_count = len(re.findall(r"[a-zA-Z]", abstract))

    if zh_count > en_count * 2:
        language = "zh"
    elif en_count > zh_count * 2:
        language = "en"
    else:
        language = "mixed"

    return {
        "abstract": abstract,
        "source": source,
        "confidence": confidence,
        "language": language,
    }
