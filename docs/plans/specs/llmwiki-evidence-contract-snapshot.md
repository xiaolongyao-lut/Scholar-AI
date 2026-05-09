# RAG Evidence Contract 快照

> LMWR-226 · Wave 0 治理产物  
> 冻结时间：2026-05-03

本文件冻结 `EvidenceReference` 的当前字段和兼容边界，作为 LLM-Wiki 集成前的基线快照。
Wiki 层在引入 `WikiEvidenceRef` 时必须保持向后兼容。

## `EvidenceReference`（TypedDict）

来源：`literature_assistant/core/evidence_packer.py`

### 必填字段

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `chunk_id` | `str` | chunk 唯一标识，来自 vector store |
| `material_id` | `str` | 文档/材料唯一标识 |
| `text` | `str` | chunk 原文 |
| `compressed_text` | `str` | 压缩摘要（可为空字符串） |
| `quote` | `str` | 直接引文（可为空字符串） |
| `label` | `str` | 展示标签 |

### 可选字段（`NotRequired`）

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `score` | `float \| str` | 检索评分 |
| `page` | `int \| str` | 原始文档页码 |
| `source` | `str` | 来源描述文本 |
| `source_label` | `str` | 单一来源标签（deprecated，请用 `source_labels`） |
| `source_labels` | `list[str]` | 多来源标签列表 |
| `source_hint` | `str` | 额外来源提示 |
| `rank` | `int` | 检索排名 |
| `query_overlap_tokens` | `list[str]` | 与 query 重叠 token 列表 |

## 兼容边界约定

1. `WikiEvidenceRef` 必须可从 `EvidenceReference` 无损转换。
2. `chunk_id` 和 `material_id` 是最小必须字段；`text`/`compressed_text`/`quote` 至少一个非空。
3. `source_labels` 优先于 `source_label`；两者共存时以 `source_labels` 为准。
4. 新 Wiki 字段（如 `citation_target`、`page_store_path`）只能添加，不能删除现有字段。
5. 序列化时需支持 JSON roundtrip，不依赖 Python 对象身份。

## 当前使用场景

| 文件 | 用途 |
| --- | --- |
| `literature_assistant/core/evidence_packer.py` | 构建 `EvidenceReference` 列表 |
| `literature_assistant/core/retrieval_provenance.py` | normalize/merge/attach source_labels |
| `literature_assistant/core/main_rag_workflow.py` | `RAGResult.evidence_refs` 字段 |
| `literature_assistant/core/citation_auditor.py` | quote-in-source 检查 |
| `frontend/src/lib/evidenceReferences.ts` | 前端展示 |
| `tests/test_evidence_packer.py` | 当前回归测试 |

## 相关测试

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\test_evidence_packer.py -q
```
