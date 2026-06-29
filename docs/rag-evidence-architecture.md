# RAG 与证据架构

[English](rag-evidence-architecture.en.md) · [项目首页](../README.md) · [Claude / Codex 工具箱](claude-codex-toolbox.md)

Scholar AI 的 RAG 不是单次向量检索，而是一条从本地材料到可复查证据包的链路。它服务于桌面端智能研读、综述写作、Word 导出，也服务于 Claude / Codex 通过 MCP 调用本地文献能力。

```text
PDF / Markdown / OCR 材料
        -> 资源入库与文本抽取
        -> 结构化切块与本地索引
        -> 关键词 + 向量 + rerank 混合检索
        -> refs / evidence pack / integrity gate
        -> 研读、综述、写作导出、MCP 工具调用
```

## 架构层次

| 层次 | 代码入口 | 作用 |
|---|---|---|
| 材料入库与切块 | `literature_assistant/core/routers/resources_router/` | 管理项目、材料、PDF 文本抽取、结构化切块、`doc_store` 和 `chunk_store` |
| 本地检索 | `literature_assistant/core/routers/resources_router/_search_helpers.py`、`literature_assistant/core/hybrid_search_runtime.py` | 对项目 chunk 做关键词、标题、内容匹配和多文档去重排序 |
| 向量索引 | `literature_assistant/core/chunk_vector_store.py` | 调用配置的 embedding 服务，维护带 manifest 校验的本地 embedding cache |
| 重排序 | `literature_assistant/core/reranker_client.py`、`literature_assistant/core/rerank_runtime_config.py`、`literature_assistant/core/rerank_cache.py` | 通过用户配置的 rerank 服务提升候选 chunk 排序，并保留失败降级路径 |
| 证据包 | `literature_assistant/core/routers/evidence_router.py`、`literature_assistant/core/evidence_pack.py` | 将检索结果整理成带 ref、chunk、页码/locator、来源和完整性状态的证据包 |
| 分析链 | `literature_assistant/core/analysis_chain_rag_builder.py` | 把问题、回答和证据片段组织成可复查的分析链，LLM 失败时回退到确定性版本 |

## 证据链路

| 工具或 API | 产出 |
|---|---|
| `literature.list_projects` / `literature.list_materials` | 找到本地文献项目和材料 |
| `literature.get_material_chunks` | 读取页码级或结构化 chunk |
| `literature.search_refs` | 返回可读取 ref、chunk、score、locator 和来源摘要 |
| `literature.evidence_pack_build` | 将检索结果整理成证据包 |
| `literature.evidence_integrity_gate` | 检查证据包完整性，标记 locator、ref、覆盖范围等风险 |
| `literature.knowledge_context_receipt` | 为外部模型加载的 bounded context 生成 receipt |

## 降级与边界

- 没有 embedding 或 rerank 凭证时，本地关键词/文本检索仍可工作。
- embedding cache 带 manifest 校验，避免模型、维度或 chunk 内容变化后复用错误向量。
- rerank 失败时保留检索结果和诊断状态，而不是让文献工作流中断。
- MCP 工具返回的是脱敏、限长、带 ref 的工具结果；provider key、本机数据库和运行时配置不作为工具参数暴露。
- 证据包只证明“哪些材料支持了哪些候选结论”，不替代人工对论文原文、图表和引用语境的判断。
