# -*- coding: utf-8 -*-
"""统一的终端日志工具

为桌面应用提供结构化、易读的终端日志输出。
"""

import sys
from datetime import datetime
from typing import Literal


# 确保 Windows 终端支持 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


LogLevel = Literal["INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG"]


class TerminalLogger:
    """终端日志器"""

    # ANSI 颜色代码
    COLORS = {
        "INFO": "\033[36m",      # 青色
        "SUCCESS": "\033[32m",   # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "DEBUG": "\033[90m",     # 灰色
        "RESET": "\033[0m",      # 重置
        "BOLD": "\033[1m",       # 粗体
    }

    def __init__(self, component: str):
        """
        Args:
            component: 组件名称（如 "Linter API", "任务中心", "PDF 解析"）
        """
        self.component = component

    def _format_message(self, level: LogLevel, message: str, details: dict | None = None) -> str:
        """格式化日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = self.COLORS.get(level, "")
        reset = self.COLORS["RESET"]
        bold = self.COLORS["BOLD"]

        # 主消息
        main = f"{color}[{timestamp}] [{self.component}] {bold}{level}{reset}{color}: {message}{reset}"

        # 详细信息
        if details:
            lines = [main]
            for key, value in details.items():
                lines.append(f"  {color}├─ {key}: {value}{reset}")
            return "\n".join(lines)

        return main

    def info(self, message: str, **details) -> None:
        """信息日志"""
        print(self._format_message("INFO", message, details or None))

    def success(self, message: str, **details) -> None:
        """成功日志"""
        print(self._format_message("SUCCESS", message, details or None))

    def warning(self, message: str, **details) -> None:
        """警告日志"""
        print(self._format_message("WARNING", message, details or None))

    def error(self, message: str, **details) -> None:
        """错误日志"""
        print(self._format_message("ERROR", message, details or None))

    def debug(self, message: str, **details) -> None:
        """调试日志"""
        print(self._format_message("DEBUG", message, details or None))

    def separator(self, char: str = "─", length: int = 60) -> None:
        """打印分隔线"""
        print(f"\033[90m{char * length}\033[0m")


# 预定义的日志器实例
linter_logger = TerminalLogger("Linter")
task_logger = TerminalLogger("任务中心")
pdf_logger = TerminalLogger("PDF 解析")
rag_logger = TerminalLogger("RAG 检索")
discussion_logger = TerminalLogger("讨论生成")


# 使用示例
if __name__ == "__main__":
    logger = TerminalLogger("测试组件")

    logger.info("这是一条信息日志")
    logger.success("操作成功", count=5, time="2.3s")
    logger.warning("发现潜在问题", file="test.pdf")
    logger.error("操作失败", reason="文件不存在")
    logger.debug("调试信息", var="test_value")

    logger.separator()
    logger.info("分隔线之后的内容")
