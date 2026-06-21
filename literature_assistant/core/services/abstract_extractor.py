# -*- coding: utf-8 -*-
"""摘要智能提取服务

从 PDF 文本中智能提取 Abstract/摘要，替代简单的前 200 字截断。
"""

from __future__ import annotations

import re
from typing import Optional


__all__ = ["extract_abstract", "extract_abstract_enhanced"]


_EN_ABSTRACT_HEADING = r"(?:abstract|a\s+b\s+s\s+t\s+r\s+a\s+c\s+t)"
_EN_STOP_HEADING = (
    r"(?:keywords?|key\s+words|introduction|"
    r"\d+(?:\.\d+)*\.?\s+introduction|"
    r"acknowledg(?:e)?ments?|references)"
)
_ZH_STOP_HEADING = r"(?:关键词|关键字|引言|绪论|参考文献)"


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_trailing_sections(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if re.match(rf"(?i)^(?:{_EN_STOP_HEADING})\b", line):
            break
        if re.match(rf"^{_ZH_STOP_HEADING}", line):
            break
        if re.match(r"(?i)^©\s*\d{4}\b", line):
            break
        lines.append(raw_line)
    return "\n".join(lines).strip()


def _extract_section(
    text: str,
    *,
    heading_pattern: str,
    stop_pattern: str,
    min_chars: int,
    flags: int = re.IGNORECASE,
) -> str | None:
    pattern = re.compile(
        rf"(?ims)(?:^|\n)\s*{heading_pattern}\s*[:：]?\s*\n?\s*(.*?)"
        rf"(?=(?:\n\s*(?:{stop_pattern})\b)|\Z)",
        flags,
    )
    match = pattern.search(text)
    if not match:
        return None
    section = _normalize_whitespace(_strip_trailing_sections(match.group(1)))
    if len(section) < min_chars:
        return None
    return section


def _extract_preface_before_keywords(text: str, *, min_chars: int) -> str | None:
    match = re.search(
        rf"(?ims)^(.*?)(?=\n\s*keywords?\s*:?\s*(?:\n|$)|\n\s*{_ZH_STOP_HEADING})",
        text,
    )
    if not match:
        return None
    lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    metadata_pattern = re.compile(
        r"(?i)(contents lists available|journal homepage|article history|"
        r"\breceived\b|\bsubmitted\b|\brevised\b|\baccepted\b|"
        r"\bavailable online\b|\bpublished\b)"
    )
    last_metadata_idx = -1
    for idx, line in enumerate(lines):
        if metadata_pattern.search(line):
            last_metadata_idx = idx
    if last_metadata_idx >= 0:
        lines = lines[last_metadata_idx + 1 :]

    content: list[str] = []
    for line in lines:
        if metadata_pattern.search(line):
            continue
        if len(line) < 35 and not content:
            continue
        content.append(line)
    candidate = _normalize_whitespace("\n".join(content))
    if len(candidate) < min_chars:
        return None
    return candidate


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

    if not isinstance(max_length, int) or max_length < 1:
        raise ValueError("max_length must be a positive integer")

    # 1. 尝试提取 Abstract 章节（英文）
    abstract = _extract_section(
        text,
        heading_pattern=_EN_ABSTRACT_HEADING,
        stop_pattern=_EN_STOP_HEADING,
        min_chars=50,
    )
    if abstract:
        return abstract[:max_length]

    # 2. 尝试提取摘要章节（中文）
    abstract = _extract_section(
        text,
        heading_pattern=r"摘\s*要",
        stop_pattern=_ZH_STOP_HEADING,
        min_chars=20,
        flags=0,
    )
    if abstract:
        return abstract[:max_length]

    # 3. Some publisher first pages omit "Abstract" but place the abstract-like
    # preface immediately before Keywords. Treat that block as abstract evidence.
    abstract = _extract_preface_before_keywords(text, min_chars=120)
    if abstract:
        return abstract[:max_length]

    # 4. Fallback：智能截取前 N 字（按段落）
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
    if re.search(rf"(?i)(?:\bAbstract\b|{_EN_ABSTRACT_HEADING})", text[:2000]):
        source = "abstract"
        confidence = 0.92
    elif re.search(r"摘\s*要", text[:2000]):
        source = "abstract"
        confidence = 0.85
    elif _extract_preface_before_keywords(text[:3000], min_chars=120):
        source = "abstract"
        confidence = 0.75
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
