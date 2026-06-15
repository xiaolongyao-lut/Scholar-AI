# -*- coding: utf-8 -*-
"""新旧 Linter 系统适配器

将新的规则系统集成到现有的 API 路由中，保持向后兼容。
"""

from typing import Any

from .linter import lint_materials as new_lint_materials
from .metadata_linter import LinterIssue, LinterResult


async def lint_materials_with_new_engine(
    materials: list[dict[str, Any]],
    preferred_case: str = "title",
) -> list[LinterResult]:
    """使用新 linter 引擎检查文献，返回兼容旧格式的结果

    Args:
        materials: 文献列表
        preferred_case: 大小写风格（"title" 或 "sentence"）

    Returns:
        LinterResult 列表
    """
    # 运行新 linter
    fixed_materials = await new_lint_materials(materials, debug=False)

    # 转换为旧格式的 LinterResult
    results: list[LinterResult] = []

    for original, fixed in zip(materials, fixed_materials):
        reports = fixed.get("_linter_reports", [])

        # 收集所有问题
        issues: list[LinterIssue] = []

        for report in reports:
            # 确定字段名
            field = _extract_field_from_report(report["rule_id"])

            # 获取修复前后的值
            current, suggested = _extract_values_from_action(report.get("action"), original, fixed, field)

            issues.append({
                "field": field,
                "severity": report["level"],
                "message": report["message"],
                "current": current,
                "suggested": suggested,
            })

        # 统计错误和警告
        has_errors = any(issue["severity"] == "error" for issue in issues)
        has_warnings = any(issue["severity"] == "warning" for issue in issues)

        results.append({
            "material_id": str(original.get("material_id", "")),
            "title": str(original.get("title", "")),
            "issues": issues,
            "has_errors": has_errors,
            "has_warnings": has_warnings,
        })

    return results


def _extract_field_from_report(rule_id: str) -> str:
    """从规则 ID 提取字段名"""
    if "title" in rule_id and "short" not in rule_id:
        return "title_en"
    elif "short-title" in rule_id:
        return "short_title"
    elif "creators" in rule_id or "authors" in rule_id:
        return "authors"
    elif "date" in rule_id:
        return "publication_date"
    elif "doi" in rule_id:
        return "doi"
    elif "journal" in rule_id or "publication-title" in rule_id:
        return "journal"
    else:
        return "unknown"


def _extract_values_from_action(
    action: str | None,
    original: dict[str, Any],
    fixed: dict[str, Any],
    field: str,
) -> tuple[str | None, str | None]:
    """从修复动作中提取修复前后的值

    Args:
        action: 修复动作描述（格式：'old... → new...'）
        original: 原始文献数据
        fixed: 修复后文献数据
        field: 字段名

    Returns:
        (current, suggested) 元组
    """
    if not action:
        # 没有 action，从数据中提取
        current = _get_field_value(original, field)
        suggested = _get_field_value(fixed, field)
        return (current, suggested)

    # 解析 action 字符串
    if " → " in action:
        parts = action.split(" → ", 1)
        current = parts[0].strip()
        suggested = parts[1].strip() if len(parts) > 1 else None
        return (current, suggested)

    # 回退：从数据中提取
    current = _get_field_value(original, field)
    suggested = _get_field_value(fixed, field)
    return (current, suggested)


def _get_field_value(material: dict[str, Any], field: str) -> str | None:
    """从文献数据中获取字段值"""
    # 优先从顶层获取
    value = material.get(field)
    if value is not None:
        return str(value) if not isinstance(value, str) else value

    # 从 metadata 获取
    metadata = material.get("metadata", {})
    if isinstance(metadata, dict):
        value = metadata.get(field)
        if value is not None:
            return str(value) if not isinstance(value, str) else value

    return None
