# -*- coding: utf-8 -*-
"""远程文档解析后端：MinerU / Mistral 等多模态文档理解 API

与传统 OCR 不同，这些 API 不仅识别文字，还能返回 Markdown、表格、公式、
图片区域和版面结构，更适合学术论文 PDF。

架构：
    PDF 输入
      ↓
    OCRNeedClassifier（分类器）
      ├─ 文本型 → PyMuPDFBackend
      └─ 扫描型/复杂 → RemoteDocumentParseBackend
           ├─ MinerU（论文优先，Markdown+结构）
           ├─ Mistral OCR（英文论文）
           └─ PaddleOCR（本地保底，可选）
      ↓
    ExtractedDocumentPayload(text, blocks, markdown_full)
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from . import StructuredBlock

__all__ = [
    "RemoteDocumentParseBackend",
    "DocumentParseProvider",
    "create_mineru_provider",
    "create_mistral_provider",
]

logger = logging.getLogger("RemoteDocumentParseBackend")


class DocumentParseProvider:
    """文档解析 Provider 配置

    Args:
        name: 提供商名称 ("mineru" | "mistral")
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称（Mistral 使用）
        timeout: 请求超时（秒）
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
    ):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url or self._default_base_url(name)
        self.model = model or self._default_model(name)
        self.timeout = timeout

    @staticmethod
    def _default_base_url(name: str) -> str:
        defaults = {
            "mineru": "https://mineru.net/api",
            "mistral": "https://api.mistral.ai",
        }
        return defaults.get(name, "")

    @staticmethod
    def _default_model(name: str) -> str:
        defaults = {
            "mistral": "mistral-ocr-latest",
        }
        return defaults.get(name, "")


def create_mineru_provider(api_key: str) -> DocumentParseProvider:
    """创建 MinerU provider 配置"""
    return DocumentParseProvider(name="mineru", api_key=api_key)


def create_mistral_provider(api_key: str) -> DocumentParseProvider:
    """创建 Mistral OCR provider 配置"""
    return DocumentParseProvider(name="mistral", api_key=api_key)


class RemoteDocumentParseBackend:
    """远程文档解析后端（统一接口）

    支持多个文档理解 API 提供商：
    - MinerU: 精准解析 API，支持批量、表格、公式、Markdown 输出
    - Mistral: 专用 OCR API (/v1/ocr)，页级 Markdown 输出
    """

    name = "remote_document_parse"
    supports_blocks = False  # 当前返回纯文本 + markdown_full

    def __init__(self, provider: DocumentParseProvider):
        """初始化远程文档解析后端

        Args:
            provider: Provider 配置
        """
        self.provider = provider
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.provider.timeout,
                headers={
                    "Authorization": f"Bearer {self.provider.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _close_client(self):
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
        """异步解析 PDF（调用远程文档理解 API）

        Args:
            source_path: PDF 文件路径

        Returns:
            (text, None, markdown_full) - 文本 + Markdown

        Raises:
            httpx.HTTPError: API 请求失败
            ValueError: 不支持的 provider 或解析失败
        """
        try:
            if self.provider.name == "mineru":
                text, markdown = await self._parse_mineru(source_path)
            elif self.provider.name == "mistral":
                text, markdown = await self._parse_mistral(source_path)
            else:
                raise ValueError(f"Unsupported provider: {self.provider.name}")

            logger.info(
                "remote_parse_success provider=%s path=%s text_len=%d md_len=%d",
                self.provider.name,
                source_path.name,
                len(text),
                len(markdown) if markdown else 0,
            )
            return text, None, markdown

        except Exception as exc:
            logger.error(
                "remote_parse_failed provider=%s path=%s err=%s",
                self.provider.name,
                source_path.name,
                exc,
            )
            raise
        finally:
            await self._close_client()

    async def _parse_mineru(self, pdf_path: Path) -> tuple[str, str]:
        """MinerU 标准精准解析 API（v4 批量接口）

        流程：
        1. POST /api/v4/file-urls/batch 申请批量上传 URL
        2. PUT file_urls[0] 上传文件
        3. 轮询 GET /api/v4/extract-results/batch/{batch_id}
        4. 下载 full_zip_url
        5. 解压提取 full.md

        参考：https://mineru.net/apiManage/docs
        """
        client = self._get_client()

        # 1. 申请上传 URL
        response = await client.post(
            f"{self.provider.base_url}/v4/file-urls/batch",
            json={"file_num": 1},
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") != 0:
            raise ValueError(f"MinerU申请上传失败: {result.get('msg')}")

        file_urls = result["data"]["file_urls"]
        batch_id = result["data"]["batch_id"]

        if not file_urls:
            raise ValueError("MinerU未返回上传URL")

        upload_url = file_urls[0]

        # 2. 上传文件
        with pdf_path.open("rb") as f:
            pdf_bytes = f.read()

        upload_response = await client.put(upload_url, content=pdf_bytes)
        upload_response.raise_for_status()

        logger.info("mineru_upload_success batch_id=%s size=%d", batch_id, len(pdf_bytes))

        # 3. 轮询解析结果（最多等待 3 分钟）
        max_wait = 180
        poll_interval = 5
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            poll_response = await client.get(
                f"{self.provider.base_url}/v4/extract-results/batch/{batch_id}"
            )
            poll_response.raise_for_status()
            poll_result = poll_response.json()

            if poll_result.get("code") != 0:
                raise ValueError(f"MinerU轮询失败: {poll_result.get('msg')}")

            state = poll_result["data"].get("state")
            if state == "success":
                full_zip_url = poll_result["data"].get("full_zip_url")
                if not full_zip_url:
                    raise ValueError("MinerU未返回full_zip_url")

                # 4. 下载 zip
                zip_response = await client.get(full_zip_url)
                zip_response.raise_for_status()

                # 5. 解压提取 full.md
                with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
                    if "full.md" not in zf.namelist():
                        raise ValueError("MinerU zip中缺少full.md")

                    markdown = zf.read("full.md").decode("utf-8")
                    # 简单从 Markdown 提取纯文本
                    text = self._markdown_to_text(markdown)

                logger.info("mineru_extract_success batch_id=%s md_len=%d", batch_id, len(markdown))
                return text, markdown

            elif state == "failed":
                raise ValueError(f"MinerU解析失败: {poll_result['data'].get('error')}")

        raise TimeoutError(f"MinerU解析超时（>{max_wait}s），batch_id={batch_id}")

    async def _parse_mistral(self, pdf_path: Path) -> tuple[str, str]:
        """Mistral 专用 OCR API

        使用 POST /v1/ocr，模型 mistral-ocr-latest
        返回 pages[].markdown

        参考：https://docs.mistral.ai/api/endpoint/ocr
        """
        client = self._get_client()

        # 读取文件为 base64
        with pdf_path.open("rb") as f:
            pdf_bytes = f.read()

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        # 调用 /v1/ocr
        response = await client.post(
            f"{self.provider.base_url}/v1/ocr",
            json={
                "model": self.provider.model,
                "document": {
                    "type": "base64",
                    "content": pdf_b64,
                },
                "table_format": "markdown",
            },
        )
        response.raise_for_status()

        result = response.json()
        pages = result.get("pages", [])

        if not pages:
            raise ValueError("Mistral OCR未返回页面内容")

        # 拼接所有页的 markdown
        page_markdowns = [page.get("markdown", "") for page in pages]
        markdown = "\n\n".join(page_markdowns)
        text = self._markdown_to_text(markdown)

        logger.info("mistral_ocr_success pages=%d md_len=%d", len(pages), len(markdown))
        return text, markdown

    @staticmethod
    def _markdown_to_text(markdown: str) -> str:
        """简单从 Markdown 提取纯文本（移除格式标记）"""
        import re

        # 移除代码块
        text = re.sub(r"```[\s\S]*?```", "", markdown)
        # 移除行内代码
        text = re.sub(r"`[^`]+`", "", text)
        # 移除链接
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # 移除图片
        text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", text)
        # 移除标题标记
        text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
        # 移除粗体/斜体
        text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^\*]+)\*", r"\1", text)
        # 移除多余空白
        text = re.sub(r"\n\n+", "\n\n", text)
        return text.strip()


# 兼容性别名（标记为 deprecated）
MultimodalOcrBackend = RemoteDocumentParseBackend
OcrProviderConfig = DocumentParseProvider
