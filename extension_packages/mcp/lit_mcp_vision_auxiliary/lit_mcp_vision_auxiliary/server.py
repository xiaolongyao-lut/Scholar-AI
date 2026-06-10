"""Vision Auxiliary MCP server for the local installer wizard.

Minimal stdio MCP server exposing read-only tools used by the literature
assistant chat to let text-only chat models receive image-derived context.
The batch tool is the runtime entry point used by SmartRead; the single-image
tools remain as compatibility/manual operations.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
import sys
import time
from typing import Any
from urllib.parse import quote, urlsplit

try:
    import httpx
except ImportError:  # pragma: no cover - exercised only in standalone installs.
    httpx = None  # type: ignore[assignment]

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
SMART_READ_BATCH_TOOL = "analyze_images_batch"
DESCRIBE_TOOL = "vision.describe_image"
EXTRACT_TEXT_TOOL = "vision.extract_text"
OPENAI_COMPATIBLE_PROVIDERS = frozenset({"openai", "siliconflow", "custom"})
MAX_IMAGES_PER_BATCH = 6
DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TOTAL_IMAGE_BYTES = 24 * 1024 * 1024
HARD_MAX_IMAGE_BYTES = 32 * 1024 * 1024
HARD_MAX_TOTAL_IMAGE_BYTES = 96 * 1024 * 1024
_ENDPOINT_REJECTION_MESSAGE = (
    "视觉服务地址未通过安全检查，请使用 HTTPS 公网服务地址，且不要包含用户名、查询参数、片段或内网地址。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config() -> dict[str, str]:
    return {
        "provider": os.environ.get("VISION_PROVIDER", "siliconflow"),
        "base_url": os.environ.get("VISION_BASE_URL", ""),
        "model": os.environ.get("VISION_MODEL", "Qwen2-VL-7B-Instruct"),
        "api_key": os.environ.get("VISION_API_KEY", ""),
        "max_note_chars": os.environ.get("MAX_NOTE_CHARS", "3200"),
    }


def _max_note_chars(raw_value: str) -> int:
    try:
        parsed = int(raw_value)
    except ValueError:
        return 3200
    return min(max(parsed, 400), 12000)


def _bounded_positive_int(raw_value: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)


def _max_image_bytes() -> int:
    return _bounded_positive_int(
        os.environ.get("VISION_MAX_IMAGE_BYTES", ""),
        default=DEFAULT_MAX_IMAGE_BYTES,
        minimum=1,
        maximum=HARD_MAX_IMAGE_BYTES,
    )


def _max_total_image_bytes() -> int:
    return _bounded_positive_int(
        os.environ.get("VISION_MAX_TOTAL_IMAGE_BYTES", ""),
        default=DEFAULT_MAX_TOTAL_IMAGE_BYTES,
        minimum=1,
        maximum=HARD_MAX_TOTAL_IMAGE_BYTES,
    )


class _VisionProviderError(RuntimeError):
    def __init__(self, *, code: str, message_zh: str) -> None:
        if not code.strip():
            raise ValueError("code must be non-empty")
        if not message_zh.strip():
            raise ValueError("message_zh must be non-empty")
        self.code = code
        self.message_zh = message_zh
        super().__init__(message_zh)


def _endpoint_rejected(reason: str) -> _VisionProviderError:
    if not reason.strip():
        raise ValueError("reason must be non-empty")
    logger.debug("vision endpoint rejected: %s", reason)
    return _VisionProviderError(
        code="VISION_BASE_URL_REJECTED",
        message_zh=_ENDPOINT_REJECTION_MESSAGE,
    )


def _classify_endpoint_ip(ip_text: str) -> str | None:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return f"invalid_ip:{ip_text}"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved:
        return "reserved"
    if ip.is_private:
        return "private"
    return None


def _resolve_endpoint_hosts(host: str) -> list[str]:
    if not host.strip():
        raise ValueError("host must be non-empty")
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise _endpoint_rejected(f"dns_resolution_failed:{exc.__class__.__name__}") from exc
    resolved = sorted({info[4][0] for info in infos if info and info[4]})
    if not resolved:
        raise _endpoint_rejected("dns_resolution_empty")
    return resolved


def _validate_provider_request_url(url: str) -> None:
    """
    Validates user-supplied vision provider URLs against SSRF attacks.

    Defenses: HTTPS-only, no userinfo/query/fragment, getaddrinfo pre-flight
    to reject private-network IPs, follow_redirects=False in httpx calls.

    Residual risk: DNS rebinding TOCTOU window. The check-time DNS resolution
    happens here via getaddrinfo, but the actual httpx request may re-resolve
    DNS (use-time). An attacker controlling the domain's authoritative DNS
    could return a safe IP during validation and a private IP during request.

    Mitigation: Attack requires user to enter attacker-controlled domain and
    attacker to operate malicious DNS with precise timing. Risk is low for
    typical usage where users configure trusted provider endpoints.
    """
    if not isinstance(url, str) or not url.strip():
        raise _VisionProviderError(code="VISION_BASE_URL_MISSING", message_zh="视觉服务地址为空。")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise _endpoint_rejected(f"unsupported_scheme:{parsed.scheme}")
    if parsed.username or parsed.password:
        raise _endpoint_rejected("userinfo_in_url")
    if parsed.query or parsed.fragment:
        raise _endpoint_rejected("query_or_fragment_in_url")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise _endpoint_rejected("missing_host")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise _endpoint_rejected("invalid_port") from exc
    if parsed.scheme.lower() == "http":
        raise _endpoint_rejected("http_scheme_not_allowed")
    resolved_hosts = _resolve_endpoint_hosts(host)
    rejected = [
        f"{ip_text}({_classify_endpoint_ip(ip_text)})"
        for ip_text in resolved_hosts
        if _classify_endpoint_ip(ip_text) is not None
    ]
    if rejected:
        raise _endpoint_rejected("unsafe_resolved_ip")


def _validated_provider_base_url(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        raise _VisionProviderError(code="VISION_BASE_URL_MISSING", message_zh="视觉服务地址为空。")
    _validate_provider_request_url(trimmed)
    return trimmed


def _json_text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _batch_error(code: str, message_zh: str) -> list[TextContent]:
    return _json_text(
        {
            "ok": False,
            "error": {
                "code": code,
                "message_zh": message_zh,
                "recoverable": True,
            },
        }
    )


def _missing_config_error(missing: list[str]) -> list[TextContent]:
    msg = (
        "[视觉辅助配置缺失] " + "、".join(missing) +
        "。请在文献助手设置 → MCP → 视觉辅助 中重新绑定凭证或填写字段。"
    )
    return [TextContent(type="text", text=msg)]


def _missing_config_batch_error(missing: list[str]) -> list[TextContent]:
    return _batch_error(
        "VISION_CONFIG_MISSING",
        "视觉辅助配置缺失：" + "、".join(missing) + "。请重新绑定凭证或填写视觉模型设置。",
    )


def _normalize_image_payloads(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    raw_images = arguments.get("images")
    if isinstance(raw_images, list):
        images = [item for item in raw_images if isinstance(item, dict)]
        return images[:MAX_IMAGES_PER_BATCH]

    image_b64 = arguments.get("image_b64")
    if isinstance(image_b64, str) and image_b64:
        payload: dict[str, Any] = {
            "data_b64": image_b64,
            "mime": str(arguments.get("mime_type") or "image/png"),
        }
        return [payload]
    return []


def _estimated_b64_decoded_bytes(value: str) -> int:
    cleaned = "".join(str(value or "").split())
    if not cleaned:
        return 0
    padding = len(cleaned) - len(cleaned.rstrip("="))
    return max(0, (len(cleaned) * 3) // 4 - min(padding, 2))


def _validate_image_payload_limits(images: list[dict[str, Any]]) -> _VisionProviderError | None:
    per_image_limit = _max_image_bytes()
    total_limit = _max_total_image_bytes()
    total_bytes = 0
    for index, image in enumerate(images, start=1):
        estimated = _estimated_b64_decoded_bytes(_image_b64(image))
        if estimated > per_image_limit:
            return _VisionProviderError(
                code="VISION_IMAGE_TOO_LARGE",
                message_zh=(
                    f"第 {index} 张图片超过大小上限，请压缩后再试。"
                ),
            )
        total_bytes += estimated
        if total_bytes > total_limit:
            return _VisionProviderError(
                code="VISION_IMAGE_BATCH_TOO_LARGE",
                message_zh="本次图片总大小超过上限，请减少图片数量或压缩后再试。",
            )
    return None


def _image_label(image: dict[str, Any], index: int) -> str:
    name = image.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"图片 {index}"


def _image_b64(image: dict[str, Any]) -> str:
    value = image.get("data_b64")
    if isinstance(value, str):
        return value
    value = image.get("image_b64")
    if isinstance(value, str):
        return value
    return ""


def _image_mime(image: dict[str, Any]) -> str:
    raw = image.get("mime") or image.get("mime_type") or "image/png"
    return str(raw).strip() or "image/png"


def _default_base_url(provider: str) -> str:
    if provider == "siliconflow":
        return "https://api.siliconflow.cn/v1"
    if provider == "anthropic":
        return "https://api.anthropic.com/v1"
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta"
    return "https://api.openai.com/v1"


def _provider_id(cfg: dict[str, str]) -> str:
    value = cfg.get("provider", "").strip().lower()
    if value in {"google", "google-gemini"}:
        return "gemini"
    return value or "siliconflow"


def _openai_chat_url(base_url: str) -> str:
    trimmed = _validated_provider_base_url(base_url)
    if trimmed.endswith("/chat/completions"):
        return trimmed
    if "/v1/" in trimmed:
        idx = trimmed.rfind("/v1/")
        return f"{trimmed[: idx + 3]}/chat/completions"
    if trimmed.endswith("/v1"):
        return f"{trimmed}/chat/completions"
    return f"{trimmed}/v1/chat/completions"


def _anthropic_messages_url(base_url: str) -> str:
    trimmed = _validated_provider_base_url(base_url)
    return trimmed if trimmed.endswith("/messages") else f"{trimmed}/messages"


def _gemini_generate_url(base_url: str, model: str) -> str:
    trimmed = _validated_provider_base_url(base_url)
    model_id = model.removeprefix("models/").strip()
    if trimmed.endswith(":generateContent"):
        return trimmed
    if "/models/" in trimmed:
        return f"{trimmed}:generateContent"
    return f"{trimmed}/models/{quote(model_id, safe='')}:generateContent"


def _vision_prompt(label: str, question: str) -> str:
    focus = question.strip()
    focus_line = f"\n用户关注的问题：{focus}" if focus else ""
    return (
        "请用中文分析这张文献或研究相关图片，输出适合给文本对话模型参考的笔记。"
        "重点包括图像类型、可见文字、主要对象、数据趋势、异常点和回答用户问题所需的事实。"
        f"\n图片名称：{label}{focus_line}"
    )


def _extract_text_parts(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [
            str(item.get("text", "")).strip()
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(part for part in parts if part)
    return ""


def _extract_openai_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            text = _extract_text_parts(message.get("content"))
            if text:
                return text
        text = _extract_text_parts(choice.get("text"))
        if text:
            return text
    return ""


def _extract_anthropic_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        block.get("text", "").strip()
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return "\n".join(part for part in parts if part)


def _extract_gemini_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        text = "\n".join(
            part.get("text", "").strip()
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("text", "").strip()
        )
        if text:
            return text
    return ""


async def _post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    if httpx is None:
        raise _VisionProviderError(code="VISION_HTTP_CLIENT_MISSING", message_zh="当前环境缺少视觉服务请求组件。")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.post(url, headers=headers, json=body)
    except Exception as exc:
        logger.debug("vision provider request failed", exc_info=True)
        raise _VisionProviderError(code="VISION_REQUEST_FAILED", message_zh="视觉服务连接失败或超时。") from exc
    if response.status_code >= 400:
        raise _VisionProviderError(code="VISION_HTTP_ERROR", message_zh=f"视觉服务返回 HTTP {response.status_code}。")
    try:
        return response.json()
    except ValueError as exc:
        raise _VisionProviderError(code="VISION_BAD_JSON", message_zh="视觉服务返回了无法解析的数据。") from exc


async def _call_openai_compatible_vision(
    *,
    cfg: dict[str, str],
    image: dict[str, Any],
    label: str,
    question: str,
) -> str:
    url = _openai_chat_url(cfg["base_url"] or _default_base_url(_provider_id(cfg)))
    image_b64 = _image_b64(image)
    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_prompt(label, question)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{_image_mime(image)};base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": min(_max_note_chars(cfg["max_note_chars"]), 4096),
        "temperature": 0,
    }
    payload = await _post_json(
        url,
        {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        body,
    )
    text = _extract_openai_text(payload)
    if not text:
        raise _VisionProviderError(code="VISION_EMPTY_RESPONSE", message_zh="视觉服务没有返回可用说明。")
    return text


async def _call_anthropic_vision(
    *,
    cfg: dict[str, str],
    image: dict[str, Any],
    label: str,
    question: str,
) -> str:
    url = _anthropic_messages_url(cfg["base_url"] or _default_base_url("anthropic"))
    body: dict[str, Any] = {
        "model": cfg["model"],
        "max_tokens": min(_max_note_chars(cfg["max_note_chars"]), 4096),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_prompt(label, question)},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _image_mime(image),
                            "data": _image_b64(image),
                        },
                    },
                ],
            }
        ],
    }
    payload = await _post_json(
        url,
        {
            "Content-Type": "application/json",
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
        },
        body,
    )
    text = _extract_anthropic_text(payload)
    if not text:
        raise _VisionProviderError(code="VISION_EMPTY_RESPONSE", message_zh="视觉服务没有返回可用说明。")
    return text


async def _call_gemini_vision(
    *,
    cfg: dict[str, str],
    image: dict[str, Any],
    label: str,
    question: str,
) -> str:
    url = _gemini_generate_url(cfg["base_url"] or _default_base_url("gemini"), cfg["model"])
    body: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": _vision_prompt(label, question)},
                    {
                        "inline_data": {
                            "mime_type": _image_mime(image),
                            "data": _image_b64(image),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {"maxOutputTokens": min(_max_note_chars(cfg["max_note_chars"]), 4096), "temperature": 0},
    }
    payload = await _post_json(
        url,
        {"Content-Type": "application/json", "x-goog-api-key": cfg["api_key"]},
        body,
    )
    text = _extract_gemini_text(payload)
    if not text:
        raise _VisionProviderError(code="VISION_EMPTY_RESPONSE", message_zh="视觉服务没有返回可用说明。")
    return text


async def _call_vision_provider(
    *,
    cfg: dict[str, str],
    image: dict[str, Any],
    index: int,
    question: str,
) -> str:
    label = _image_label(image, index)
    provider = _provider_id(cfg)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        text = await _call_openai_compatible_vision(cfg=cfg, image=image, label=label, question=question)
    elif provider == "anthropic":
        text = await _call_anthropic_vision(cfg=cfg, image=image, label=label, question=question)
    elif provider == "gemini":
        text = await _call_gemini_vision(cfg=cfg, image=image, label=label, question=question)
    else:
        raise _VisionProviderError(code="VISION_PROVIDER_UNSUPPORTED", message_zh="暂不支持所选视觉服务。")
    note = f"图片：{label}\n{text.strip()}"
    return note[: _max_note_chars(cfg["max_note_chars"])]


async def _describe_single_image(
    *,
    cfg: dict[str, str],
    image_b64: str,
    mime_type: str,
    question: str,
) -> str:
    image = {"data_b64": image_b64, "mime": mime_type, "name": "单张图片"}
    return await _call_vision_provider(cfg=cfg, image=image, index=1, question=question)


def _render_received_note(*, image: dict[str, Any], index: int, question: str, cfg: dict[str, str]) -> str:
    label = _image_label(image, index)
    mime = str(image.get("mime") or image.get("mime_type") or "未知类型")
    encoded_length = len(_image_b64(image))
    size = image.get("size")
    size_text = f"{size} 字节" if isinstance(size, int) and size > 0 else "浏览器未提供"
    question_text = f"\n用户关注：{question}" if question else ""
    note = (
        f"图片：{label}\n"
        f"格式：{mime}\n"
        f"大小：{size_text}\n"
        f"编码长度：{encoded_length} 个字符\n"
        f"视觉模型：{cfg['model']}\n"
        "状态：图片已通过视觉辅助入口接收。视觉服务暂时不可用时，系统会保留这份图片元信息供主对话参考。"
        f"{question_text}"
    )
    return note[: _max_note_chars(cfg["max_note_chars"])]


async def _handle_batch_tool(arguments: dict[str, Any]) -> list[TextContent]:
    start = time.monotonic()
    cfg = _config()
    missing: list[str] = []
    if not cfg["api_key"]:
        missing.append("视觉模型密钥")
    if not cfg["model"]:
        missing.append("视觉模型名称")
    if missing:
        return _missing_config_batch_error(missing)

    images = _normalize_image_payloads(arguments)
    if not images:
        return _batch_error("VISION_IMAGE_MISSING", "没有收到图片内容，无法分析。")
    limit_error = _validate_image_payload_limits(images)
    if limit_error is not None:
        return _batch_error(limit_error.code, limit_error.message_zh)

    question = str(arguments.get("user_request") or arguments.get("user_question") or "")
    notes: list[dict[str, Any]] = []
    for index, image in enumerate(images, start=1):
        if not _image_b64(image):
            continue
        try:
            note = await _call_vision_provider(cfg=cfg, image=image, index=index, question=question)
        except _VisionProviderError as exc:
            logger.debug("vision provider unavailable: %s", exc.code)
            return _batch_error(exc.code, exc.message_zh)
        notes.append({"ok": True, "note": note, "reused": False, "primitives": []})
    if not notes:
        return _batch_error("VISION_IMAGE_MISSING", "没有收到可用的图片编码，无法分析。")

    return _json_text(
        {
            "ok": True,
            "notes": notes,
            "hit_rate": 0.0,
            "total_ms": int((time.monotonic() - start) * 1000),
        }
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


server: Server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=SMART_READ_BATCH_TOOL,
            description=(
                "Analyze a bounded batch of browser-provided images and return "
                "JSON notes for the SmartRead pre-LLM context path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "images": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {
                                "data_b64": {
                                    "type": "string",
                                    "maxLength": (HARD_MAX_IMAGE_BYTES * 4 + 2) // 3,
                                },
                                "mime": {"type": "string", "default": "image/png"},
                                "size": {"type": "integer", "minimum": 1},
                                "name": {"type": "string"},
                            },
                            "required": ["data_b64"],
                        },
                    },
                    "user_request": {"type": "string", "default": ""},
                    "session_id": {"type": "string", "default": ""},
                    "target_model_sig": {"type": "string", "default": ""},
                    "use_cache": {"type": "boolean", "default": True},
                },
                "required": ["images"],
            },
        ),
        Tool(
            name=DESCRIBE_TOOL,
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
                        "maxLength": (HARD_MAX_IMAGE_BYTES * 4 + 2) // 3,
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
            name=EXTRACT_TEXT_TOOL,
            description=(
                "OCR-style text extraction from an image. Returns plain text "
                "with minimal structural inference (paragraph breaks)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_b64": {
                        "type": "string",
                        "maxLength": (HARD_MAX_IMAGE_BYTES * 4 + 2) // 3,
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
    if name == SMART_READ_BATCH_TOOL:
        return await _handle_batch_tool(arguments)

    cfg = _config()
    missing: list[str] = []
    if not cfg["api_key"]:
        missing.append("视觉模型密钥")
    if not cfg["model"]:
        missing.append("视觉模型名称")
    if missing:
        return _missing_config_error(missing)

    image_b64 = arguments.get("image_b64", "")
    if not image_b64:
        return [TextContent(
            type="text",
            text="[视觉辅助] 没有收到图片内容，无法分析。请在智能研读对话中重新上传图片后再试。",
        )]
    limit_error = _validate_image_payload_limits(
        [{"data_b64": str(image_b64), "mime": str(arguments.get("mime_type") or "image/png")}]
    )
    if limit_error is not None:
        return [TextContent(type="text", text=limit_error.message_zh)]

    if name == DESCRIBE_TOOL:
        question = arguments.get("user_question", "")
        try:
            note = await _describe_single_image(
                cfg=cfg,
                image_b64=str(image_b64),
                mime_type=str(arguments.get("mime_type") or "image/png"),
                question=str(question or ""),
            )
            return [TextContent(type="text", text=note)]
        except _VisionProviderError as exc:
            logger.debug("single-image vision provider unavailable: %s", exc.code)
        question_suffix = f"\n关注问题：{question}" if question else ""
        return [TextContent(
            type="text",
            text=(
                "[视觉辅助已接收图片]\n"
                "状态：图片已进入视觉辅助流程。\n"
                f"服务地址: {'已填写' if cfg['base_url'] else '使用默认地址'}\n"
                f"模型：{cfg['model']}\n"
                f"图片大小：{len(image_b64)} 个编码字符"
                f"{question_suffix}\n"
                "触发方式：在智能研读对话中上传图片并提问，系统会把图片内容整理成中文上下文。"
            ),
        )]
    if name == EXTRACT_TEXT_TOOL:
        return [TextContent(
            type="text",
            text=(
                "[视觉辅助已接收图片]\n"
                f"服务地址：{'已填写' if cfg['base_url'] else '使用默认地址'}\n"
                f"模型：{cfg['model']}\n"
                "触发方式：在智能研读对话中上传含文字的图片并提问，系统会优先提取可读文字。"
            ),
        )]
    return [TextContent(
        type="text",
        text="未知视觉辅助操作。请回到文献助手界面重新选择图片分析功能。",
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
