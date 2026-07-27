# -*- coding: utf-8 -*-
"""多模态 AI OCR 后端：兼容 MinerU / Mistral / 其他 Vision API"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Mapping, Protocol, TypeGuard

import httpx

from . import StructuredBlock

__all__ = ["MultimodalOcrBackend", "OcrProviderConfig"]

logger = logging.getLogger("MultimodalOcrBackend")


class _CloseableDocument(Protocol):
    """Minimum resource capability required after opening a PDF."""

    def close(self) -> None: ...


class _PageIterable(Protocol):
    """Iterator-style page access retained by compatible PyMuPDF releases."""

    def __iter__(self) -> Iterator[object]: ...


class _PageSequence(Protocol):
    """Sequence-style page access exposed by compatible test doubles."""

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> object: ...


class _PageCountLoader(Protocol):
    """Explicit page-loader API exposed by current PyMuPDF releases."""

    @property
    def page_count(self) -> int: ...

    def load_page(self, index: int) -> object: ...


def _call_runtime_method(
    target: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """Call a checked method on PyMuPDF's partially typed runtime surface."""

    method = getattr(target, method_name, None)
    if not callable(method):
        raise TypeError(f"PyMuPDF object must expose callable {method_name}")
    result: object = method(*args, **kwargs)
    return result


def _is_closeable_document(value: object) -> TypeGuard[_CloseableDocument]:
    """Narrow an opened value before validating page access."""

    return callable(getattr(value, "close", None))


def _has_page_iterator(value: object) -> TypeGuard[_PageIterable]:
    return callable(getattr(value, "__iter__", None))


def _has_page_sequence(value: object) -> TypeGuard[_PageSequence]:
    return callable(getattr(value, "__len__", None)) and callable(
        getattr(value, "__getitem__", None)
    )


def _has_page_count_loader(value: object) -> TypeGuard[_PageCountLoader]:
    """Narrow an opened value to the explicit page-loader API."""

    page_count = getattr(value, "page_count", None)
    return (
        isinstance(page_count, int)
        and not isinstance(page_count, bool)
        and page_count >= 0
        and callable(getattr(value, "load_page", None))
    )


def _iter_document_pages(document: object) -> Iterator[object]:
    """Yield pages from every supported PyMuPDF document surface."""

    if _has_page_count_loader(document):
        for index in range(document.page_count):
            yield document.load_page(index)
        return
    if _has_page_sequence(document):
        for index in range(len(document)):
            yield document[index]
        return
    if _has_page_iterator(document):
        yield from document
        return
    raise TypeError("PyMuPDF document does not expose a supported page contract")


class OcrProviderConfig:
    """OCR Provider 配置

    Args:
        name: 提供商名称 ("mineru" | "mistral" | "openai" | "claude")
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称
        timeout: 请求超时（秒）
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url or self._default_base_url(name)
        self.model = model or self._default_model(name)
        self.timeout = timeout

    @staticmethod
    def _default_base_url(name: str) -> str:
        """默认 API base URL"""
        defaults = {
            "mineru": "https://mineru.net/api/v1",
            "mistral": "https://api.mistral.ai/v1",
            "openai": "https://api.openai.com/v1",
            "claude": "https://api.anthropic.com/v1",
        }
        return defaults.get(name, "")

    @staticmethod
    def _default_model(name: str) -> str:
        """默认模型名称"""
        defaults = {
            "mineru": "pdf-ocr",
            "mistral": "pixtral-12b-2409",
            "openai": "gpt-4o",
            "claude": "claude-3-5-sonnet-20241022",
        }
        return defaults.get(name, "")


class MultimodalOcrBackend:
    """多模态 AI OCR 后端（统一接口）

    支持多个 Vision API 提供商：
    - MinerU: PDF OCR 专用 API
    - Mistral: Pixtral 多模态模型
    - OpenAI: GPT-4 Vision
    - Claude: Claude 3.5 Sonnet Vision
    """

    name = "multimodal_ocr"
    supports_blocks = False  # 大多数 Vision API 返回纯文本

    def __init__(self, config: OcrProviderConfig):
        """初始化多模态 OCR 后端

        Args:
            config: Provider 配置
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _close_client(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def parse(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """同步解析入口（内部调用异步方法）"""
        return asyncio.run(self.parse_async(source_path))

    async def parse_async(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """异步解析 PDF（调用多模态 Vision API）

        Args:
            source_path: PDF 文件路径

        Returns:
            (text, None, None) - 纯文本结果

        Raises:
            httpx.HTTPError: API 请求失败
            ValueError: 不支持的 provider
        """
        try:
            if self.config.name == "mineru":
                text = await self._parse_mineru(source_path)
            elif self.config.name == "mistral":
                text = await self._parse_mistral(source_path)
            elif self.config.name == "openai":
                text = await self._parse_openai(source_path)
            elif self.config.name == "claude":
                text = await self._parse_claude(source_path)
            else:
                raise ValueError(f"Unsupported OCR provider: {self.config.name}")

            logger.info(
                "multimodal_ocr_success provider=%s path=%s length=%d",
                self.config.name,
                source_path.name,
                len(text),
            )
            return text, None, None

        except Exception as exc:
            logger.error(
                "multimodal_ocr_failed provider=%s path=%s err=%s",
                self.config.name,
                source_path.name,
                exc,
            )
            raise
        finally:
            await self._close_client()

    async def _parse_mineru(self, pdf_path: Path) -> str:
        """MinerU API 解析"""
        client = self._get_client()

        # 上传 PDF 文件
        with pdf_path.open("rb") as f:
            pdf_bytes = f.read()

        # MinerU 接口：POST /parse
        response = await client.post(
            f"{self.config.base_url}/parse",
            json={
                "file": base64.b64encode(pdf_bytes).decode("utf-8"),
                "filename": pdf_path.name,
                "extract_images": False,  # 只提取文字
            },
        )
        response.raise_for_status()

        result: object = response.json()
        if not isinstance(result, Mapping):
            raise ValueError("MinerU response must be a JSON object")
        text = result.get("text", "")
        if not isinstance(text, str):
            raise ValueError("MinerU response field 'text' must be a string")
        return text

    async def _parse_mistral(self, pdf_path: Path) -> str:
        """Mistral Pixtral 多模态解析"""
        # 1. PDF 转图片
        images = self._pdf_to_images(pdf_path)

        # 2. 调用 Mistral Vision API
        client = self._get_client()
        all_text = []

        for i, img_bytes in enumerate(images):
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            response = await client.post(
                f"{self.config.base_url}/chat/completions",
                json={
                    "model": self.config.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract all text from this image. Return only the text content, no explanations.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": f"data:image/png;base64,{img_b64}",
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()

            result = response.json()
            page_text = result["choices"][0]["message"]["content"]
            all_text.append(page_text)

        return "\n\n".join(all_text)

    async def _parse_openai(self, pdf_path: Path) -> str:
        """OpenAI GPT-4 Vision 解析（同 Mistral 逻辑）"""
        images = self._pdf_to_images(pdf_path)
        client = self._get_client()
        all_text = []

        for img_bytes in images:
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            response = await client.post(
                f"{self.config.base_url}/chat/completions",
                json={
                    "model": self.config.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract all text from this image. Return only the text content.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{img_b64}"
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()

            result = response.json()
            page_text = result["choices"][0]["message"]["content"]
            all_text.append(page_text)

        return "\n\n".join(all_text)

    async def _parse_claude(self, pdf_path: Path) -> str:
        """Claude 3.5 Sonnet Vision 解析"""
        images = self._pdf_to_images(pdf_path)
        client = self._get_client()
        all_text = []

        for img_bytes in images:
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            response = await client.post(
                f"{self.config.base_url}/messages",
                json={
                    "model": self.config.model,
                    "max_tokens": 4096,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": img_b64,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": "Extract all text from this image. Return only the text content.",
                                },
                            ],
                        }
                    ],
                },
                headers={
                    "anthropic-version": "2023-06-01",
                    "x-api-key": self.config.api_key,
                },
            )
            response.raise_for_status()

            result = response.json()
            page_text = result["content"][0]["text"]
            all_text.append(page_text)

        return "\n\n".join(all_text)

    @staticmethod
    def _pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[bytes]:
        """PDF 转图片（PNG bytes）

        Args:
            pdf_path: PDF 文件路径
            dpi: 分辨率（默认 200）

        Returns:
            每页的 PNG 图片字节列表
        """
        try:
            import pymupdf
        except ImportError as exc:
            raise ImportError(
                "pymupdf is required for PDF to image conversion. "
                "Install it with: pip install pymupdf"
            ) from exc

        opened_document = _call_runtime_method(pymupdf, "open", str(pdf_path))
        if not _is_closeable_document(opened_document):
            raise TypeError("PyMuPDF open() must return a closeable document")
        document = opened_document
        images: list[bytes] = []

        try:
            for page in _iter_document_pages(document):
                pix = _call_runtime_method(page, "get_pixmap", dpi=dpi)
                img_bytes = _call_runtime_method(pix, "tobytes", "png")
                if not isinstance(img_bytes, bytes):
                    raise TypeError("PyMuPDF Pixmap.tobytes() must return bytes")
                images.append(img_bytes)
        finally:
            document.close()

        return images
