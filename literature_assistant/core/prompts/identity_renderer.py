"""Identity header renderer.

Public API:
    ``render_identity_header(entry_id, context=None) -> str``

Per D-ID-P0-5, any template-read or rendering failure degrades to a
minimal safe string (never raises) so the upstream LLM call still
proceeds. Capability flags are rendered as advisory prose hints using the
template-layer hard guard (D-ID-P0-2): prefer ``默认 / 若 / 跟随``,
avoid declarative ``必须 / 应该 / 不允许 / 不要`` commands.
"""

from __future__ import annotations

import logging
from importlib.resources import files
from typing import Any, Mapping, Optional

from .capability_matrix import EntryCapabilities, get_capabilities

logger = logging.getLogger(__name__)

_IDENTITY_PKG = "literature_assistant.core.prompts.identity"


def _safe_read(resource_path: str) -> str:
    """Read a .txt resource from the identity package; empty string on failure."""
    try:
        return (
            files(_IDENTITY_PKG)
            .joinpath(resource_path)
            .read_text(encoding="utf-8")
            .strip()
        )
    except Exception as exc:
        logger.warning("identity_renderer: failed to read %s: %s", resource_path, exc)
        return ""


def _render_capabilities(caps: EntryCapabilities) -> str:
    """Render the capability bitmap into the '可用能力' prose block."""
    lines = ["# 可用能力（默认状态，运行时可能被用户覆盖）"]

    if caps.mcp_tools:
        lines.append(
            "- 跟随用户配置使用 MCP 工具；具体可用工具由运行时 `mcp_server_ids` 决定"
        )
    if caps.cross_session_memory:
        lines.append(
            "- 默认接续同一会话的历史 turn；若 session 中断，跟随用户重连"
        )
    if caps.long_term_memory:
        lines.append(
            "- 默认从项目长期记忆中召回相关条目作为参考；若记忆暂不可用，跟随当前证据回答"
        )
    if caps.project_meta:
        lines.append("- 默认拿到 project_id / 文献集合等元信息作为上下文")
    if caps.multi_agent:
        visibility = {
            "messages_only": "仅看到其他 agent 公开发出的文字",
            "full": "可看到其他 agent 的完整状态",
            "solo": "无其他参与者",
        }.get(caps.visibility_model, "其他参与者可见性未声明")
        lines.append(
            f"- 多 agent 协同模式（{visibility}）；默认不复述其他 agent 已说过的内容"
        )
    if caps.json_strict:
        lines.append(
            "- 输出格式严格，跟随下文 JSON Schema；自由文本会破坏下游解析"
        )

    if len(lines) == 1:
        # 沉默式默认：未声明任何能力时，给一行兜底
        lines.append("- 默认无额外能力声明；专注当前任务输入")

    return "\n".join(lines)


def _render_context_meta(context: Mapping[str, Any]) -> str:
    """Render the per-call context block (project / session / turn)."""
    keys_in_order = ("project_id", "session_id", "turn_index")
    lines: list[str] = []
    for k in keys_in_order:
        v = context.get(k)
        if v is None or v == "":
            continue
        lines.append(f"- {k}: {v}")
    if not lines:
        return ""
    return "# 当前任务上下文\n" + "\n".join(lines)


def render_identity_header(
    entry_id: str,
    context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render the identity header for ``entry_id``.

    Returns an empty string if the entry is unknown or all resources fail
    to load. The caller concatenates the returned header with the existing
    task template (newline-separated) before formatting.
    """
    context = context or {}
    try:
        caps = get_capabilities(entry_id)
    except KeyError as exc:
        logger.warning("identity_renderer: %s", exc)
        return ""

    try:
        if caps.is_extractive:
            return _safe_read("extractive_minimal/_shared.txt")

        root = _safe_read("root.txt")
        sub = _safe_read(f"conversational_subidentity/{entry_id}.txt")
        caps_block = _render_capabilities(caps)
        ctx_block = _render_context_meta(context)

        parts = [p for p in (root, sub, caps_block, ctx_block) if p]
        return "\n\n".join(parts)
    except Exception as exc:
        logger.warning(
            "identity_renderer: render failed for %s: %s", entry_id, exc
        )
        return ""
