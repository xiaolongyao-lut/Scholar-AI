# -*- coding: utf-8 -*-
"""
RAG Citation Auditor
Role: 验证 LLM 返回的引用 quote 是否真实存在于源文档中
Spec: RAG_ADVANCED_EVOLUTION.md §引用溯源审计
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _normalize_chunk_id(value: Any) -> str:
    return str(value or "").strip().strip("[]")


def _source_text(chunk: Dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("content", "text", "compressed_text", "quote", "source_text", "claim"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)

class CitationAuditor:
    """引用审计员：解决 RAG 幻觉的最后一道防线"""

    def audit(self, response_data: Dict[str, Any], source_chunks: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
        """
        审计生成结果：
        返回：(修改后的结果, 是否通过审计)
        """
        evidence = response_data.get("evidence", [])
        if not evidence:
            return response_data, True

        # 构建 ID -> 内容的快速映射，兼容检索、压缩和本地兜底的字段名。
        chunk_map: dict[str, str] = {}
        for chunk in source_chunks:
            chunk_id = _normalize_chunk_id(chunk.get("chunk_id"))
            if chunk_id:
                chunk_map[chunk_id] = _source_text(chunk)

        audit_failed = False
        failures = []

        for item in evidence:
            chunk_ids = item.get("chunk_ids", [])
            quote = str(item.get("quote", "")).strip()

            if not quote or quote == "string":
                continue

            # 只要有一个 chunk_id 匹配且包含该 quote 就算通过
            found = False
            for cid in chunk_ids:
                source_content = chunk_map.get(_normalize_chunk_id(cid), "")
                if quote in source_content:
                    found = True
                    break

            if not found:
                audit_failed = True
                failures.append(f"Quote not found in source for ID {chunk_ids}")
                item["audit_status"] = "failed"
                logger.warning(f"🛡️ 审计报警: 引用幻觉! Quote '{quote[:30]}...' 不存在于 {chunk_ids}")
            else:
                item["audit_status"] = "passed"

        if audit_failed:
            limitations = response_data.get("limitations", "")
            response_data["limitations"] = f"【🛡️ 溯源警告】部分引用匹配失败 ({len(failures)}条)。" + limitations
            response_data["status"] = "audit_warning"

        return response_data, not audit_failed

def get_auditor() -> CitationAuditor:
    return CitationAuditor()
