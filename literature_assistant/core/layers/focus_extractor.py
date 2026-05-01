# -*- coding: utf-8 -*-
"""
Focus Points Extractor (Sprint 1)
Role: 自动从文献中提取关键专业标签，构建可扩展的关注点库

输入：本地文献文件夹（PDF/Markdown）
输出：focus_points.json（包含数千个去重的关键概念）

使用方式：
    python -m layers.focus_extractor \
      --doc-folder "./papers" \
      --output "focus_points.json" \
      --batch-size 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, List, Set

import httpx

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FocusExtractor:
    """从文献中自动提取关键概念标签"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "ep-your-ark-endpoint",
        timeout: float = 60.0
    ):
        """
        初始化提取器
        
        Args:
            api_key: 聊天模型 API key
            base_url: API 基础 URL
            model: 使用的大模型名称
            timeout: HTTP 超时时间（秒）
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        
        # 防卡死客户端
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2)
        )
        
        # 已提取的关注点
        self.extracted_points: Set[str] = set()
        self.failed_documents: List[str] = []
    
    async def extract_from_document(
        self,
        doc_path: str,
        max_tokens: int = 3000
    ) -> List[str]:
        """
        从单篇文献中提取关键标签
        
        Args:
            doc_path: 文档路径
            max_tokens: 截断长度（防止超大文件）
        
        Returns:
            提取的标签列表，例如 ["参数优化", "热输入控制", ...]
        """
        try:
            # 1. 读取文档内容
            content = self._read_document(doc_path, max_tokens)
            if not content or len(content.strip()) < 100:
                logger.warning(f"文档内容过短，跳过: {doc_path}")
                return []
            
            # 2. 调用大模型提取标签
            tags = await self._call_llm_for_tags(content, doc_path)
            
            if tags:
                logger.info(f"✓ 从 {Path(doc_path).name} 提取到 {len(tags)} 个标签")
            
            return tags
            
        except Exception as e:
            logger.error(f"✗ 处理文档失败 {doc_path}: {e}")
            self.failed_documents.append(doc_path)
            return []
    
    def _read_document(self, doc_path: str, max_tokens: int) -> str:
        """读取文档内容并截断"""
        try:
            path = Path(doc_path)
            content = ""

            if path.suffix.lower() == '.md':
                content = path.read_text(encoding='utf-8')
            elif path.suffix.lower() == '.txt':
                content = path.read_text(encoding='utf-8')
            elif path.suffix.lower() == '.pdf':
                # 尝试用 PyPDF2 或 pdfplumber 读取 PDF
                try:
                    import PyPDF2
                    with open(path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages[:5]:  # 只读前 5 页避免超大文件
                            content += page.extract_text()
                except ImportError:
                    logger.warning(f"PyPDF2 未安装，尝试 pdfplumber...")
                    try:
                        import pdfplumber
                        with pdfplumber.open(path) as pdf:
                            for page in pdf.pages[:5]:
                                content += page.extract_text()
                    except ImportError:
                        logger.error(f"未安装 PDF 读取库（PyPDF2 或 pdfplumber），跳过: {path}")
                        return ""
            else:
                logger.warning(f"不支持的文件格式: {path.suffix}")
                return ""

            # 简单的 token 估算（中文按字数，英文按单词）
            # 这里假设平均一个 token ≈ 3-4 个字符
            truncated = content[:max_tokens * 4]

            return truncated

        except Exception as e:
            logger.error(f"读取文件失败 {doc_path}: {e}")
            return ""
    
    async def _call_llm_for_tags(self, content: str, doc_path: str) -> List[str]:
        """调用大模型提取关键标签"""
        
        # 构造提示词
        prompt = f"""你是一名学术研究助手。请仔细阅读下面的学术文献片段，提取其中的 5-10 个核心研究标签或关键概念。

要求：
1. 标签应该是名词短语（2-4 个词为宜）
2. 标签应该代表文献的核心内容、方法或创新点
3. 避免过于通用的词（如"研究"、"分析"）
4. 优先选择具体的工艺参数、材料名称、现象描述

文献内容：
{content[:2000]}

请直接列出标签，每行一个，不需要解释："""
        
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": 300
                }
            )
            
            if response.status_code != 200:
                logger.error(f"API 调用失败 {response.status_code}: {response.text}")
                return []
            
            result = response.json()
            response_text = result['choices'][0]['message']['content']
            
            # 解析响应，提取标签
            tags = self._parse_tags(response_text)
            
            return tags
            
        except httpx.TimeoutException:
            logger.error(f"API 调用超时: {doc_path}")
            return []
        except Exception as e:
            logger.error(f"API 调用异常 {doc_path}: {e}")
            return []
    
    def _parse_tags(self, response_text: str) -> List[str]:
        """从 LLM 响应中解析标签"""
        lines = response_text.strip().split('\n')
        tags = []
        
        for line in lines:
            # 清理行
            line = line.strip()
            
            # 跳过空行和编号
            if not line or line.startswith('#'):
                continue
            
            # 移除常见的前缀（如 "1.", "- ", "* "）
            line = re.sub(r'^[\d\.\-\*\s]+', '', line)
            line = line.strip()
            
            # 移除引号
            line = line.strip('"\'""''')
            
            # 过滤过短或过长的标签
            if 2 <= len(line) <= 50 and line:
                tags.append(line)
        
        return tags
    
    async def batch_extract(
        self,
        doc_folder: str,
        batch_size: int = 5,
        delay_between_batches: float = 2.0
    ) -> Set[str]:
        """
        批量处理文件夹中的所有文献

        Args:
            doc_folder: 文献文件夹路径
            batch_size: 每批处理的文件数
            delay_between_batches: 批次间隔（秒，用于避免 API 限流）

        Returns:
            所有去重后的关注点集合
        """
        doc_folder = Path(doc_folder)

        if not doc_folder.exists():
            logger.error(f"文件夹不存在: {doc_folder}")
            return set()

        # 收集所有支持的文献文件
        doc_files = (
            list(doc_folder.glob('**/*.md')) +
            list(doc_folder.glob('**/*.txt')) +
            list(doc_folder.glob('**/*.pdf'))
        )

        if not doc_files:
            logger.warning(f"文件夹中未找到支持的文献文件 (.md, .txt, .pdf): {doc_folder}")
            return set()

        logger.info(f"发现 {len(doc_files)} 个文献文件")

        # 分批处理
        for batch_idx in range(0, len(doc_files), batch_size):
            batch = doc_files[batch_idx:batch_idx + batch_size]

            logger.info(f"\n[批次 {batch_idx//batch_size + 1}/{(len(doc_files)-1)//batch_size + 1}]")

            # 并发处理本批文件
            tasks = [
                self.extract_from_document(str(doc))
                for doc in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for doc, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(f"处理异常 {doc}: {result}")
                else:
                    self.extracted_points.update(result)

            logger.info(f"累计收集: {len(self.extracted_points)} 个关注点")

            # 批次间延迟
            if batch_idx + batch_size < len(doc_files):
                logger.info(f"等待 {delay_between_batches}s 后继续...")
                await asyncio.sleep(delay_between_batches)

        logger.info(f"\n✓ 提取完成！共 {len(self.extracted_points)} 个去重关注点")

        return self.extracted_points
    
    def save_focus_points(
        self,
        output_path: str,
        include_stats: bool = True
    ) -> None:
        """
        保存关注点库到 JSON 文件
        
        Args:
            output_path: 输出文件路径
            include_stats: 是否包含统计信息
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_points": len(self.extracted_points),
            "points": sorted(list(self.extracted_points)),
        }
        
        if include_stats:
            data["stats"] = {
                "failed_documents": len(self.failed_documents),
                "failed_documents_list": self.failed_documents
            }
        
        output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        logger.info(f"✓ 关注点库已保存: {output_path}")
        logger.info(f"  - 总数: {len(self.extracted_points)}")
        logger.info(f"  - 文件大小: {output_file.stat().st_size / 1024:.1f} KB")
    
    async def close(self) -> None:
        """关闭异步客户端"""
        await self.client.aclose()


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="从文献中自动提取关键概念标签"
    )
    parser.add_argument(
        '--doc-folder',
        required=True,
        help='文献文件夹路径（包含 .md 或 .txt 文件）'
    )
    parser.add_argument(
        '--output',
        default='focus_points.json',
        help='输出 JSON 文件路径（默认: focus_points.json）'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=5,
        help='每批处理的文件数（默认: 5）'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=2.0,
        help='批次间延迟秒数（默认: 2.0）'
    )
    
    args = parser.parse_args()
    
    # 获取 API key
    api_key = os.environ.get('ARK_API_KEY') or os.environ.get('SILICONFLOW_API_KEY')
    if not api_key:
        logger.error("环境变量 ARK_API_KEY 未设置（兼容旧的 SILICONFLOW_API_KEY）")
        return
    
    # 创建提取器并运行
    extractor = FocusExtractor(
        api_key=api_key,
        base_url=os.environ.get('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3'),
        model=os.environ.get('ARK_MODEL', 'ep-your-ark-endpoint')
    )
    
    try:
        # 批量提取
        await extractor.batch_extract(
            args.doc_folder,
            batch_size=args.batch_size,
            delay_between_batches=args.delay
        )
        
        # 保存结果
        extractor.save_focus_points(args.output)
        
        logger.info("✓ 提取流程完成！")
        logger.info(f"  下一步：运行 semantic_router.py 进行向量化")
        
    finally:
        await extractor.close()


if __name__ == '__main__':
    asyncio.run(main())
