# RAG 与证据架构

[English](rag-evidence-architecture.en.md) · [项目首页](../README.md) · [Claude / Codex 工具箱](claude-codex-toolbox.md)

Scholar AI 的 RAG 不是单次向量检索，而是一条从本地材料到可复查证据包的链路。它服务于桌面端智能研读、综述写作、Word 导出，也服务于 Claude / Codex 通过 MCP 调用本地文献能力。

核心结构是：先把本地材料变成可定位 chunk，再按使用场景进入不同检索入口。稳定工具链偏 refs 和证据包；智能研读会在上下文预算内组合混合检索、TOLF 扩散、Wiki 关联扩展和结构化邻居；最终所有结果都要收束成 ref、locator、source label 和完整性状态。

```text
PDF / Markdown / OCR 材料
        │
        ▼
资源入库与文本抽取
        │  project / material metadata
        │  PDF text, OCR fallback, source identity
        ▼
结构化切块与本地索引
        │  doc_store / chunk_store
        │  page, bbox, section_path, chunk_type
        │  embedding cache with manifest validation
        ▼
检索入口
        │  search_refs: stable lexical refs
        │  smart reading: hybrid + TOLF + RRF + structured siblings
        │  evidence pack: project chunks + wiki / knowledge refs
        ▼
受控扩展
        │  bridge lexicon query expansion
        │  TOLF aspect-query diffusion and evidence gate
        │  wiki linked-page expansion
        │  project + wiki weighted RRF
        │  same-section table / formula / figure siblings
        ▼
证据整理与完整性门控
        │  refs, locators, source labels, qrels status
        │  evidence_integrity_gate, context receipt
        ▼
研读、综述、写作导出、MCP 工具调用
```

## 架构层次

| 层次 | 代码入口 | 作用 |
|---|---|---|
| 材料入库与切块 | `literature_assistant/core/routers/resources_router/` | 管理项目、材料、PDF 文本抽取、结构化切块、`doc_store` 和 `chunk_store` |
| 稳定 refs 检索 | `literature_assistant/core/routers/resources_router/endpoints_search_upload.py`、`literature_assistant/core/routers/resources_router/_search_helpers.py` | `search_refs` 对已有 chunk store 做只读检索，返回 ref、score、locator 和来源摘要；不会触发入库副作用 |
| 智能研读上下文 | `literature_assistant/core/routers/intelligent_chat_router.py` | 按会话、项目、材料、上下文预算构造回答上下文，并在开关允许时组合 TOLF、RRF、混合检索和结构化邻居 |
| 混合检索 | `literature_assistant/core/layers/r_layer_hybrid_retriever.py`、`literature_assistant/core/hybrid_search_runtime.py` | BM25 / lexical overlap / dense embedding / optional rerank；缺少 embedding 或 rerank 时保留可用的词面检索 |
| TOLF 扩散 | `literature_assistant/core/tolf_text_selector.py`、`literature_assistant/core/layers/tolf_engine.py`、`literature_assistant/core/tolf_bridge_lexicon_store.py` | 用桥接词典扩展查询，生成 aspect queries，在候选图上做 spreading activation，并用证据门控筛掉弱证据 |
| Wiki 与知识扩展 | `literature_assistant/core/wiki/query.py`、`literature_assistant/core/routers/evidence_router.py`、`literature_assistant/core/source_vault.py` | Wiki-first linked-page expansion、project + wiki weighted RRF、knowledge refs；非项目内容仍通过 bounded resource refs 读取 |
| 结构化邻居 | `literature_assistant/core/rag_structured_sibling_inclusion.py` | 当叙述 chunk 命中时，可补入同 section 或同页的表格、公式、图注 sibling，避免数值证据被长段落挤出上下文 |
| 证据包 | `literature_assistant/core/routers/evidence_router.py`、`literature_assistant/core/evidence_pack.py` | 将检索结果整理成带 ref、chunk、页码/locator、source label、coverage 和完整性状态的证据包 |
| 证据图投影 | `literature_assistant/core/knowledge_graph/projection.py`、`literature_assistant/core/graph_payload.py` | 从 SmartRead 会话或 Wiki graph 投影 session、claim、source、chunk 和 derived_from / contains 关系，供审阅和跳转使用 |
| 分析链 | `literature_assistant/core/analysis_chain_rag_builder.py` | 把问题、回答和证据片段组织成可复查的分析链，LLM 失败时回退到确定性版本 |

## 检索与扩展路径

| 路径 | 何时使用 | 扩展方式 | 边界 |
|---|---|---|---|
| `search_refs` | MCP / API 需要稳定、只读、可引用 refs | 词面评分、多文档去重、locator coverage | 不触发入库，不复制正文，不假装 rerank 已运行 |
| 智能研读上下文 | 桌面端问答、PDF 研读、项目上下文回答 | hybrid retrieval、TOLF、RRF、结构化 sibling inclusion | 受上下文层级和字符预算限制；材料页内提问优先当前 material |
| TOLF 目标导向检索 | 需要找间接证据、机制/方法/结果多面证据时 | bridge lexicon query expansion、aspect queries、spreading activation、EvidenceGate | 候选来自当前项目 chunk；无足够激活时回退到词面重叠证据 |
| Wiki-first / joint recall | Wiki 索引可用且完整性 gate 允许时 | linked-page expansion、project + wiki weighted RRF | Wiki refs 保持 bounded resource，不写回 project chunks |
| 证据包构建 | 写作、综述、MCP 取证链 | 项目 refs、Wiki refs、知识 refs、locator coverage、qrels status | 输出证据包和诊断，不替代人工检查原文语境 |
| 证据图 | 展示研读或 Wiki 关系 | session -> claim -> chunk -> source，Wiki graph 节点关系 | 是投影和审阅面，不是所有 RAG 查询的强制入口 |

## 证据链路

| 工具或 API | 产出 |
|---|---|
| `literature.list_projects` / `literature.list_materials` | 找到本地文献项目和材料 |
| `literature.get_material_chunks` | 读取页码级或结构化 chunk |
| `literature.search_refs` | 返回可读取 ref、score、locator 和来源摘要 |
| `literature.evidence_pack_build` | 将项目 chunk、Wiki refs 和知识 refs 整理成证据包 |
| `literature.evidence_integrity_gate` | 检查证据包完整性，标记 locator、ref、覆盖范围等风险 |
| `literature.knowledge_context_receipt` | 为外部模型加载的 bounded context 生成 receipt |

## 降级与边界

- 没有 embedding 或 rerank 凭证时，本地关键词/文本检索仍可工作。
- embedding cache 带 manifest 校验，避免模型、维度或 chunk 内容变化后复用错误向量。
- rerank 失败时保留检索结果和诊断状态，而不是让文献工作流中断。
- TOLF 和 Wiki 扩展是受控扩展层，不是无边界全库漫游；候选、链接数、上下文长度和完整性 gate 都有上限。
- `search_refs`、智能研读上下文、证据包构建的目标不同，不应把其中一个入口的行为描述成所有 RAG 工具的统一行为。
- MCP 工具返回的是脱敏、限长、带 ref 的工具结果；provider key、本机数据库和运行时配置不作为工具参数暴露。
- 证据包只证明“哪些材料支持了哪些候选结论”，不替代人工对论文原文、图表和引用语境的判断。
