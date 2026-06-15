# -*- coding: utf-8 -*-
"""Linter 规则引擎

负责批量运行规则、收集报告、应用修复。
"""

import asyncio
from typing import Any

from .rule_base import ApplyContext, LinterRule, PrepareContext, ReportLevel


class LinterEngine:
    """Linter 规则引擎"""

    def __init__(self, rules: list[LinterRule]):
        """
        Args:
            rules: 要执行的规则列表
        """
        self.rules = rules

    async def lint_and_fix(
        self,
        items: list[dict[str, Any]],
        debug: bool = False,
    ) -> list[dict[str, Any]]:
        """对一批文献条目执行 lint 和修复

        Args:
            items: 文献条目列表（WritingMaterial 的 dict 表示）
            debug: 是否启用调试日志

        Returns:
            修复后的文献条目列表，每个条目附带 '_linter_reports' 字段
        """
        def debug_log(msg: str) -> None:
            if debug:
                print(f"[LinterEngine] {msg}")

        debug_log(f"开始处理 {len(items)} 个条目，{len(self.rules)} 个规则")

        # 1. 准备阶段：让所有规则预加载数据
        prepare_ctx = PrepareContext(items=items, debug=debug_log)
        rule_options: dict[str, dict[str, Any]] = {}

        for rule in self.rules:
            debug_log(f"准备规则: {rule.id}")
            try:
                options = await rule.prepare(prepare_ctx)
                if options is False:
                    debug_log(f"规则 {rule.id} 返回 False，跳过")
                    continue
                if options is True or options is None:
                    options = {}
                rule_options[rule.id] = options
            except Exception as e:
                debug_log(f"规则 {rule.id} 准备失败: {e}")
                rule_options[rule.id] = {}

        # 2. 应用阶段：对每个条目应用所有规则
        results: list[dict[str, Any]] = []

        for item in items:
            item_reports: list[dict[str, Any]] = []

            for rule in self.rules:
                if rule.id not in rule_options:
                    continue  # 规则在准备阶段被跳过

                # 创建应用上下文
                ctx = ApplyContext(
                    item=item,
                    options=rule_options[rule.id],
                    debug=debug_log,
                )

                try:
                    await rule.apply(ctx)

                    # 收集报告
                    for report in ctx.reports:
                        item_reports.append({
                            "rule_id": rule.id,
                            "rule_name": rule.name,
                            "level": report.level.value,
                            "message": report.message,
                            "action": report.action,
                        })

                except Exception as e:
                    debug_log(f"规则 {rule.id} 应用失败: {e}")
                    item_reports.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "level": ReportLevel.ERROR.value,
                        "message": f"规则执行失败: {str(e)}",
                        "action": None,
                    })

            # 附加报告到条目
            item["_linter_reports"] = item_reports
            results.append(item)

        debug_log(f"处理完成，共修复 {len(results)} 个条目")
        return results


async def lint_materials(
    materials: list[dict[str, Any]],
    rule_ids: list[str] | None = None,
    debug: bool = False,
) -> list[dict[str, Any]]:
    """便捷函数：对文献列表执行 lint

    Args:
        materials: 文献列表
        rule_ids: 要执行的规则 ID 列表（None 表示执行所有已注册的规则）
        debug: 是否启用调试日志

    Returns:
        修复后的文献列表
    """
    from .rule_base import get_all_rules, get_rule

    if rule_ids is None:
        # 执行所有已注册的规则
        all_rules = get_all_rules()
        rules = list(all_rules.values())
    else:
        # 执行指定的规则
        rules = []
        for rule_id in rule_ids:
            rule = get_rule(rule_id)
            if rule:
                rules.append(rule)
            elif debug:
                print(f"[lint_materials] 未找到规则: {rule_id}")

    if not rules:
        if debug:
            print("[lint_materials] 没有可执行的规则")
        return materials

    engine = LinterEngine(rules)
    return await engine.lint_and_fix(materials, debug=debug)
