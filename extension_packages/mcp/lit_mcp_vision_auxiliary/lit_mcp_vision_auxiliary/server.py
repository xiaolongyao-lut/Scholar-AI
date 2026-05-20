"""Vision Auxiliary MCP server (dogfood package for the local installer wizard).

Minimal stdio MCP server exposing two read-only tools used by the
literature assistant chat to let text-only chat models "see" images:

- ``vision.describe_image``: returns a structured Chinese note
- ``vision.extract_text``: OCR-style text extraction

This is a **dogfood package** for the installer wizard end-to-end test.
Tool implementations call the configured vision provider when the env
vars are present; if a required env var is missing the tool returns an
error result rather than crashing — this keeps a probe-time list_tools
call cheap (no provider round-trip).

The package itself is the canonical "installable MCP server" the user
selects from the recommended view; it ships with a literature-mcp.json
sibling so the scanner picks it up at HIGH confidence.

Configuration (env, all injected by the installer based on
manifest.config_fields + manifest.required_credentials):

- ``VISION_PROVIDER``: siliconflow / openai / anthropic / gemini
- ``VISION_MODEL``: provider-specific model id
- ``VISION_API_KEY``: the credential resolver injects this from the
  credential the user bound at install time
- ``MAX_NOTE_CHARS``: optional, default 3200
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    # The MCP SDK lives in the project's main venv; this package piggybacks.
    # If installed standalone, callers should `pip install mcp`.
    raise SystemExit(
        "lit-mcp-vision-auxiliary requires the mcp SDK. "
        "Install with `pip install mcp`."
    )


logger = logging.getLogger("lit-mcp-vision-auxiliary")


SERVER_NAME = "lit-mcp-vision-auxiliary"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config() -> dict[str, str]:
    return {
        "provider": os.environ.get("VISION_PROVIDER", "siliconflow"),
        "model": os.environ.get("VISION_MODEL", "Qwen2-VL-7B-Instruct"),
        "api_key": os.environ.get("VISION_API_KEY", ""),
        "max_note_chars": os.environ.get("MAX_NOTE_CHARS", "3200"),
    }


def _missing_config_error(missing: list[str]) -> list[TextContent]:
    msg = (
        "[视觉辅助配置缺失] " + "、".join(missing) +
        "。请在文献助手设置 → MCP → 视觉辅助 中重新绑定凭证或填写字段。"
    )
    return [TextContent(type="text", text=msg)]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


server: Server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="vision.describe_image",
            description=(
                "Generate a structured Chinese note describing an image so a "
                "text-only chat model can answer questions about it. "
                "Input: base64 image data + optional user question."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_b64": {
                        "type": "string",
                        "description": "Base64-encoded image bytes (no data: prefix).",
                    },
                    "mime_type": {
                        "type": "string",
                        "description": "Image MIME type (image/png, image/jpeg, etc.).",
                        "default": "image/png",
                    },
                    "user_question": {
                        "type": "string",
                        "description": (
                            "Optional user question; helps the vision model "
                            "focus the description on relevant aspects."
                        ),
                        "default": "",
                    },
                },
                "required": ["image_b64"],
            },
        ),
        Tool(
            name="vision.extract_text",
            description=(
                "OCR-style text extraction from an image. Returns plain text "
                "with minimal structural inference (paragraph breaks)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_b64": {
                        "type": "string",
                        "description": "Base64-encoded image bytes.",
                    },
                    "mime_type": {
                        "type": "string",
                        "default": "image/png",
                    },
                },
                "required": ["image_b64"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    cfg = _config()
    missing: list[str] = []
    if not cfg["api_key"]:
        missing.append("VISION_API_KEY")
    if not cfg["model"]:
        missing.append("VISION_MODEL")
    if missing:
        return _missing_config_error(missing)

    image_b64 = arguments.get("image_b64", "")
    if not image_b64:
        return [TextContent(
            type="text",
            text="[视觉辅助] image_b64 参数缺失或为空,无法分析。",
        )]

    # Real provider dispatch lives in the chat hook (already wired in
    # commit 6a191c59). For dogfood we return a deterministic placeholder
    # so the wizard's end-to-end test does not depend on a live provider.
    if name == "vision.describe_image":
        question = arguments.get("user_question", "")
        question_suffix = f"\n用户问题: {question}" if question else ""
        return [TextContent(
            type="text",
            text=(
                f"[视觉辅助 dogfood 占位回复]\n"
                f"提供方: {cfg['provider']}\n"
                f"模型: {cfg['model']}\n"
                f"图片大小: {len(image_b64)} base64 字符"
                f"{question_suffix}\n"
                f"生产代码请在 chat hook 中实际调用 {cfg['provider']} 的视觉接口。"
            ),
        )]
    if name == "vision.extract_text":
        return [TextContent(
            type="text",
            text=(
                f"[视觉辅助 OCR dogfood 占位回复]\n"
                f"提供方: {cfg['provider']} / 模型: {cfg['model']}\n"
                "实际部署后此处返回 OCR 文本。"
            ),
        )]
    return [TextContent(
        type="text",
        text=f"未知工具: {name}。请确认 MCP 客户端调用的工具名与 list_tools 返回值一致。",
    )]


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
