# -*- coding: utf-8 -*-
"""元数据 Linter：按 Zotero 标准规范化文献元数据（标题/作者/日期/期刊等）。

核心功能：
- 标题大小写规范化（Title Case / Sentence case）
- 作者姓名格式统一
- 日期格式标准化
- 期刊名缩写/全称统一
- 空格/换行符清理
- 重复字段检测
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal, TypedDict

from dateutil import parser as date_parser

CaseStyle = Literal["title", "sentence", "original"]
IssueSeverity = Literal["error", "warning", "info"]

_ALLOWED_FIX_FIELDS = frozenset({"title", "title_en", "authors", "publication_date", "journal", "doi"})
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


class LinterIssue(TypedDict):
    """单个 linter 问题。"""
    field: str
    severity: IssueSeverity
    message: str
    current: str | None
    suggested: str | None


class LinterResult(TypedDict):
    """Linter 检查结果。"""
    material_id: str
    title: str
    issues: list[LinterIssue]
    has_errors: bool
    has_warnings: bool


def _normalize_whitespace(text: str) -> str:
    """清理多余空格、换行符、制表符。"""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _to_title_case(text: str) -> str:
    """转换为 Title Case，保留专有名词和缩写。

    规则：
    - 首字母大写，介词/冠词小写（除非在首尾）
    - 保留全大写缩写（如 DNA, RNA, AI）
    - 保留专有名词（如 Python, JavaScript）
    """
    # 小写词（APA/Chicago 风格）
    lowercase_words = {
        'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'in', 'nor', 'of',
        'on', 'or', 'so', 'the', 'to', 'up', 'yet', 'vs', 'via'
    }

    # 保留全大写缩写（2-5 个字母）
    if re.match(r'^[A-Z]{2,5}$', text):
        return text

    words = text.split()
    result = []
    for i, word in enumerate(words):
        # 保留全大写缩写
        if re.match(r'^[A-Z]{2,5}$', word):
            result.append(word)
        # 首尾单词总是大写
        elif i == 0 or i == len(words) - 1:
            result.append(word.capitalize())
        # 中间小词小写
        elif word.lower() in lowercase_words:
            result.append(word.lower())
        else:
            result.append(word.capitalize())

    return ' '.join(result)


def _to_sentence_case(text: str) -> str:
    """转换为 Sentence case：首字母大写，其余小写（保留专有名词/缩写）。"""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    # 保留全大写缩写
    words = text.split()
    result = []
    for i, word in enumerate(words):
        if re.match(r'^[A-Z]{2,5}$', word):
            result.append(word)
        elif i == 0:
            result.append(word.capitalize())
        else:
            result.append(word.lower())
    return ' '.join(result)


def _detect_case_style(text: str) -> CaseStyle:
    """检测当前大小写风格。"""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    words = text.split()
    if not words:
        return "original"

    # 只统计纯英文单词（忽略标点、数字、中文、缩写）
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
    # Title Case: 大部分词首字母大写
    elif capitalized_count >= len(english_words) * 0.6:
        return "title"

    return "original"


def _normalize_author_name(name: str) -> str:
    """规范化作者姓名：统一为 "Last, First Middle" 或 "Last, F. M." 格式。"""
    if not isinstance(name, str):
        raise TypeError("author name must be a string")

    name = _normalize_whitespace(name)

    # 已经是 "Last, First" 格式
    if ',' in name:
        parts = name.split(',', 1)
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ''
        return f"{last}, {first}" if first else last

    # "First Last" 格式转换
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"

    return name


def _normalize_date(date_str: str) -> tuple[str | None, list[str]]:
    """规范化日期格式为 YYYY-MM-DD 或 YYYY。

    Returns:
        (normalized_date, warnings)
    """
    if not isinstance(date_str, str):
        raise TypeError("date_str must be a string")

    warnings: list[str] = []
    date_str = _normalize_whitespace(date_str)
    if not date_str:
        warnings.append("日期不能为空")
        return None, warnings

    # 已经是 ISO 年/月/日格式，校验月份和日期边界。
    if re.match(r'^\d{4}$', date_str):
        return date_str, warnings
    if re.match(r'^\d{4}-\d{2}$', date_str):
        year, month = [int(part) for part in date_str.split("-")]
        if 1 <= month <= 12:
            return date_str, warnings
        warnings.append(f"无法解析日期格式: {date_str}")
        return None, warnings
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        try:
            date.fromisoformat(date_str)
        except ValueError:
            warnings.append(f"无法解析日期格式: {date_str}")
            return None, warnings
        return date_str, warnings

    try:
        parsed = date_parser.parse(date_str, fuzzy=True, default=date(1900, 1, 1))
    except (TypeError, ValueError, OverflowError):
        parsed = None

    if parsed is not None:
        normalized = parsed.strftime("%Y-%m-%d")
        warnings.append(f"日期已标准化为: {normalized}")
        return normalized, warnings

    # 提取年份
    year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
    if year_match:
        year = year_match.group()
        warnings.append(f"日期已简化为年份: {year}")
        return year, warnings

    warnings.append(f"无法解析日期格式: {date_str}")
    return None, warnings


def _normalize_doi(doi: str) -> str:
    """Normalize DOI strings to the Zotero/Crossref value shape without URL prefixes."""
    if not isinstance(doi, str):
        raise TypeError("doi must be a string")
    return _DOI_PREFIX_RE.sub("", doi.strip()).strip()


def _validate_preferred_case(preferred_case: CaseStyle) -> None:
    if preferred_case not in ("title", "sentence", "original"):
        raise ValueError("preferred_case must be one of: title, sentence, original")


def _validate_authors(authors: list[str] | None) -> list[str] | None:
    if authors is None:
        return None
    if not isinstance(authors, list):
        raise TypeError("authors must be a list of strings")
    normalized: list[str] = []
    for author in authors:
        if not isinstance(author, str):
            raise TypeError("authors must be a list of strings")
        stripped = _normalize_whitespace(author)
        if stripped:
            normalized.append(stripped)
    return normalized


def _validate_fix_fields(fixes: Sequence[str]) -> list[str]:
    if isinstance(fixes, (str, bytes)):
        raise TypeError("fixes must be a sequence of field names")
    normalized: list[str] = []
    for fix in fixes:
        if not isinstance(fix, str):
            raise TypeError("fixes must be a sequence of field names")
        field = fix.strip()
        if field not in _ALLOWED_FIX_FIELDS:
            raise ValueError(f"unsupported linter fix field: {field}")
        normalized.append(field)
    return normalized


def _optional_text_field(material_dict: Mapping[str, Any], field: str) -> str | None:
    value = material_dict.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string when present")
    return value


def lint_material_metadata(
    material_id: str,
    title: str,
    title_en: str | None = None,
    authors: list[str] | None = None,
    publication_date: str | None = None,
    journal: str | None = None,
    doi: str | None = None,
    preferred_case: CaseStyle = "title",
) -> LinterResult:
    """检查单个文献的元数据规范性。

    Args:
        material_id: 文献 ID
        title: 中文标题
        title_en: 英文标题
        authors: 作者列表
        publication_date: 发表日期
        journal: 期刊名
        doi: DOI
        preferred_case: 首选大小写风格（title/sentence/original）

    Returns:
        LinterResult 包含所有问题和建议修复
    """
    if not isinstance(material_id, str) or not material_id.strip():
        raise ValueError("material_id must be a non-empty string")
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    _validate_preferred_case(preferred_case)
    authors = _validate_authors(authors)

    issues: list[LinterIssue] = []

    # 1. 标题清理
    if title:
        normalized_title = _normalize_whitespace(title)
        if normalized_title != title:
            issues.append({
                "field": "title",
                "severity": "warning",
                "message": "标题包含多余空格或换行符",
                "current": title[:50] + "..." if len(title) > 50 else title,
                "suggested": normalized_title[:50] + "..." if len(normalized_title) > 50 else normalized_title,
            })

    # 2. 英文标题大小写
    if title_en:
        normalized_title_en = _normalize_whitespace(title_en)
        current_case = _detect_case_style(normalized_title_en)

        if preferred_case == "title" and current_case != "title":
            suggested = _to_title_case(normalized_title_en)
            issues.append({
                "field": "title_en",
                "severity": "info",
                "message": f"建议使用 Title Case（当前: {current_case}）",
                "current": normalized_title_en[:50] + "..." if len(normalized_title_en) > 50 else normalized_title_en,
                "suggested": suggested[:50] + "..." if len(suggested) > 50 else suggested,
            })
        elif preferred_case == "sentence" and current_case != "sentence":
            suggested = _to_sentence_case(normalized_title_en)
            issues.append({
                "field": "title_en",
                "severity": "info",
                "message": f"建议使用 Sentence case（当前: {current_case}）",
                "current": normalized_title_en[:50] + "..." if len(normalized_title_en) > 50 else normalized_title_en,
                "suggested": suggested[:50] + "..." if len(suggested) > 50 else suggested,
            })

    # 3. 作者格式
    if authors:
        for i, author in enumerate(authors):
            normalized = _normalize_author_name(author)
            if normalized != author:
                issues.append({
                    "field": f"authors[{i}]",
                    "severity": "info",
                    "message": "作者姓名格式建议统一为 'Last, First'",
                    "current": author,
                    "suggested": normalized,
                })

    # 4. 日期格式
    if publication_date:
        normalized_date, warnings = _normalize_date(publication_date)
        if warnings:
            for warning in warnings:
                issues.append({
                    "field": "publication_date",
                    "severity": "warning",
                    "message": warning,
                    "current": publication_date,
                    "suggested": normalized_date,
                })

    # 5. 期刊名清理
    if journal:
        normalized_journal = _normalize_whitespace(journal)
        if normalized_journal != journal:
            issues.append({
                "field": "journal",
                "severity": "info",
                "message": "期刊名包含多余空格",
                "current": journal,
                "suggested": normalized_journal,
            })

    # 6. DOI 格式检查
    if doi:
        doi_clean = _normalize_doi(doi)

        if doi_clean != doi:
            issues.append({
                "field": "doi",
                "severity": "info",
                "message": "DOI 建议移除前缀（保留 10.xxxx/xxx 格式）",
                "current": doi,
                "suggested": doi_clean,
            })

        # 检查 DOI 格式
        if not re.match(r'^10\.\d{4,9}/[^\s]+$', doi_clean):
            issues.append({
                "field": "doi",
                "severity": "warning",
                "message": "DOI 格式不规范（应为 10.xxxx/xxx）",
                "current": doi_clean,
                "suggested": None,
            })

    # 7. 必填字段检查
    if not title or not title.strip():
        issues.append({
            "field": "title",
            "severity": "error",
            "message": "标题不能为空",
            "current": None,
            "suggested": None,
        })

    has_errors = any(issue["severity"] == "error" for issue in issues)
    has_warnings = any(issue["severity"] == "warning" for issue in issues)

    return {
        "material_id": material_id,
        "title": title or "",
        "issues": issues,
        "has_errors": has_errors,
        "has_warnings": has_warnings,
    }


def apply_linter_fixes(
    material_dict: Mapping[str, Any],
    fixes: Sequence[str],
    preferred_case: CaseStyle = "title",
) -> dict[str, Any]:
    """应用 linter 修复建议。

    Args:
        material_dict: 原始 material 字典
        fixes: 要修复的字段列表（如 ["title", "title_en", "authors"]）
        preferred_case: 英文标题大小写风格

    Returns:
        修复后的 material 字典
    """
    if not isinstance(material_dict, Mapping):
        raise TypeError("material_dict must be a mapping")
    _validate_preferred_case(preferred_case)
    fix_fields = set(_validate_fix_fields(fixes))

    result: dict[str, Any] = dict(material_dict)

    if "title" in fix_fields and _optional_text_field(result, "title") is not None:
        result["title"] = _normalize_whitespace(str(result["title"]))

    if "title_en" in fix_fields and _optional_text_field(result, "title_en"):
        normalized = _normalize_whitespace(str(result["title_en"]))
        if preferred_case == "title":
            result["title_en"] = _to_title_case(normalized)
        elif preferred_case == "sentence":
            result["title_en"] = _to_sentence_case(normalized)
        else:
            result["title_en"] = normalized

    if "authors" in fix_fields and "authors" in result:
        authors = _validate_authors(result.get("authors"))
        result["authors"] = [_normalize_author_name(author) for author in (authors or [])]

    if "publication_date" in fix_fields and _optional_text_field(result, "publication_date"):
        normalized_date, _ = _normalize_date(str(result["publication_date"]))
        if normalized_date:
            result["publication_date"] = normalized_date

    if "journal" in fix_fields and _optional_text_field(result, "journal"):
        result["journal"] = _normalize_whitespace(str(result["journal"]))

    if "doi" in fix_fields and _optional_text_field(result, "doi"):
        result["doi"] = _normalize_doi(str(result["doi"]))

    return result
