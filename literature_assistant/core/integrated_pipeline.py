# Entrypoint for integrated pipeline
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from literature_assistant.core.modules.pipeline_observer import PipelineObserver
    from literature_assistant.core.project_paths import output_path
else:
    from project_paths import output_path


def _build_help_parser() -> argparse.ArgumentParser:
    """
    Build the lightweight CLI parser used for help-only invocation.

    Why:
        `pipeline_core` imports the full retrieval/runtime stack, which can emit
        embedding probe warnings during import. The `--help` path should stay a
        side-effect-free CLI contract check.
    """

    parser = argparse.ArgumentParser(description="文献处理器 - 模块化流水线总控")
    parser.add_argument("pdf", help="输入 PDF 文件路径")
    parser.add_argument("--goal", default="提取文献核心结论与实验数据", help="写作目标/关注点")
    parser.add_argument("--out", default=str(output_path()), help="输出根目录")
    return parser


def _should_print_help(argv: list[str]) -> bool:
    """
    Return whether the current argv requests help before runtime imports.

    Why:
        Help output is part of the CLI surface and should not depend on live
        embedding/rerank configuration or import-time initialization.
    """

    if not argv:
        return False
    return any(arg in {"-h", "--help"} for arg in argv)


def run_pipeline(
    pdf_path: str,
    goal: str,
    output_dir: str | None = None,
    observer: PipelineObserver | None = None,
) -> dict[str, Any]:
    """Run the lazily imported pipeline with its public typed contract."""

    if TYPE_CHECKING:
        from literature_assistant.core.pipeline_core import run_pipeline as _run
    else:
        from pipeline_core import run_pipeline as _run

    return _run(pdf_path, goal, output_dir, observer)


def main() -> None:
    """Lazy re-export from pipeline_core to avoid heavy imports at module level."""
    if TYPE_CHECKING:
        from literature_assistant.core.pipeline_core import main as _main
    else:
        from pipeline_core import main as _main

    _main()


if __name__ == "__main__":
    if _should_print_help(sys.argv[1:]):
        _build_help_parser().print_help()
        raise SystemExit(0)

    main()
