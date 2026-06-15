# -*- coding: utf-8 -*-
"""Linter 后台任务

将 Linter 检查作为后台任务运行，支持进度显示和取消。
"""

from __future__ import annotations

import asyncio
from typing import Any

from literature_assistant.core.terminal_logger import linter_logger
from literature_assistant.core.linter import lint_materials as new_lint_materials


class LinterTask:
    """Linter 后台任务"""

    def __init__(self, task_id: str, project_id: str, material_ids: list[str] | None = None):
        """
        Args:
            task_id: 任务 ID
            project_id: 项目 ID
            material_ids: 要检查的文献 ID 列表（None = 全部）
        """
        self.task_id = task_id
        self.project_id = project_id
        self.material_ids = material_ids
        self.cancelled = False

    async def execute(self, update_progress: callable) -> dict[str, Any]:
        """执行 Linter 检查

        Args:
            update_progress: 进度更新回调 (current, total, message)

        Returns:
            结果字典
        """
        linter_logger.info("开始 Linter 任务", task_id=self.task_id, project_id=self.project_id)

        try:
            # 1. 获取文献列表
            from literature_assistant.core.routers.linter_router import _get_writing_store

            store = _get_writing_store()
            materials = store.list_materials(project_id=self.project_id)

            if self.material_ids:
                materials = [m for m in materials if m.material_id in self.material_ids]

            total = len(materials)
            if total == 0:
                linter_logger.warning("没有文献需要检查")
                return {"checked": 0, "issues": 0, "results": []}

            update_progress(0, total, "准备检查...")

            # 2. 转换为 payload
            from literature_assistant.core.routers.linter_router import _material_linter_payload

            payloads = [_material_linter_payload(m) for m in materials]

            # 3. 批量检查（显示进度）
            results = []
            for i, payload in enumerate(payloads):
                if self.cancelled:
                    linter_logger.warning("任务被取消", task_id=self.task_id)
                    break

                # 单个文献检查
                fixed = await new_lint_materials([payload], debug=False)
                results.extend(fixed)

                # 更新进度
                current = i + 1
                progress_pct = int((current / total) * 100)
                update_progress(current, total, f"已检查 {current}/{total} 条文献")

                linter_logger.debug("检查进度", current=current, total=total, progress=f"{progress_pct}%")

                # 允许其他任务运行
                await asyncio.sleep(0)

            # 4. 统计结果
            total_issues = sum(len(r.get("_linter_reports", [])) for r in results)

            linter_logger.success("Linter 任务完成",
                                 checked=len(results),
                                 total_issues=total_issues)

            return {
                "checked": len(results),
                "total": total,
                "issues": total_issues,
                "results": results,
            }

        except Exception as e:
            linter_logger.error("Linter 任务失败", error=str(e))
            raise

    def cancel(self):
        """取消任务"""
        self.cancelled = True
        linter_logger.info("收到取消请求", task_id=self.task_id)
