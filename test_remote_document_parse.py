#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试远程文档解析后端（Mock API 调用）"""

import sys
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent / "literature_assistant" / "core"))

from pdf_backends.remote_document_parse_backend import (
    RemoteDocumentParseBackend,
    DocumentParseProvider,
    create_mineru_provider,
    create_mistral_provider,
)


def test_mineru_provider():
    """测试 MinerU provider 创建"""
    provider = create_mineru_provider("test_key")
    assert provider.name == "mineru"
    assert provider.api_key == "test_key"
    assert "mineru.net" in provider.base_url
    print("✓ MinerU provider 创建")


def test_mistral_provider():
    """测试 Mistral provider 创建"""
    provider = create_mistral_provider("test_key")
    assert provider.name == "mistral"
    assert provider.api_key == "test_key"
    assert "mistral.ai" in provider.base_url
    assert provider.model == "mistral-ocr-latest"
    print("✓ Mistral provider 创建")


async def test_mineru_parse_mock():
    """测试 MinerU 解析流程（Mock）"""
    provider = create_mineru_provider("mock_key")
    backend = RemoteDocumentParseBackend(provider)

    # Mock HTTP 响应
    mock_client = AsyncMock()

    # 1. 申请上传 URL
    mock_client.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "code": 0,
            "data": {
                "file_urls": ["https://mock-upload-url"],
                "batch_id": "mock_batch_123",
            },
        },
    )

    # 2. 上传文件
    mock_client.put.return_value = MagicMock(status_code=200)

    # 3. 轮询结果 - 第一次返回处理中，第二次返回成功
    poll_responses = [
        MagicMock(
            status_code=200,
            json=lambda: {"code": 0, "data": {"state": "processing"}},
        ),
        MagicMock(
            status_code=200,
            json=lambda: {
                "code": 0,
                "data": {
                    "state": "success",
                    "full_zip_url": "https://mock-zip-url",
                },
            },
        ),
    ]
    mock_client.get.side_effect = poll_responses

    # 4. 下载 zip（包含 full.md）
    mock_zip = io.BytesIO()
    with zipfile.ZipFile(mock_zip, "w") as zf:
        zf.writestr("full.md", "# Test PDF\n\nThis is a test.")
    mock_zip.seek(0)

    poll_responses.append(
        MagicMock(status_code=200, content=mock_zip.read())
    )

    with patch.object(backend, "_get_client", return_value=mock_client):
        # 模拟 PDF 文件
        test_pdf = Path(__file__).parent / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4\ntest")

        try:
            text, blocks, markdown = await backend.parse_async(test_pdf)

            assert "Test PDF" in text
            assert markdown is not None
            assert "Test PDF" in markdown
            assert blocks is None
            print("✓ MinerU 解析流程（Mock）")
        finally:
            test_pdf.unlink()


async def test_mistral_parse_mock():
    """测试 Mistral OCR 流程（Mock）"""
    provider = create_mistral_provider("mock_key")
    backend = RemoteDocumentParseBackend(provider)

    # Mock HTTP 响应
    mock_client = AsyncMock()
    mock_client.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "pages": [
                {"markdown": "# Page 1\n\nContent of page 1."},
                {"markdown": "# Page 2\n\nContent of page 2."},
            ]
        },
    )

    with patch.object(backend, "_get_client", return_value=mock_client):
        test_pdf = Path(__file__).parent / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4\ntest")

        try:
            text, blocks, markdown = await backend.parse_async(test_pdf)

            assert "Page 1" in text
            assert "Page 2" in text
            assert markdown is not None
            assert "Page 1" in markdown
            assert blocks is None
            print("✓ Mistral OCR 解析流程（Mock）")
        finally:
            test_pdf.unlink()


def main():
    print("=" * 70)
    print("远程文档解析后端单元测试（Mock）")
    print("=" * 70)
    print()

    test_mineru_provider()
    test_mistral_provider()

    import asyncio
    asyncio.run(test_mineru_parse_mock())
    asyncio.run(test_mistral_parse_mock())

    print()
    print("=" * 70)
    print("✅ 所有测试通过")
    print("=" * 70)


if __name__ == "__main__":
    main()
