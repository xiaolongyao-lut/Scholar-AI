# LLM-Wiki 参考项目对照索引

> LMWR-225 · Wave 0 治理产物

本文件记录执行 LLM-Wiki 集成计划时已研究的参考项目及其可借鉴点，供后续切片执行者快速定位。

## 本地借鉴库（只读）

路径前缀：`C:\Users\xiao\Downloads\llmwiki借鉴库\`

| 参考项目 | 本地路径 | 可借鉴点 | 对应任务 |
| --- | --- | --- | --- |
| PaperQA2 | `paper-qa-main` | 科学文献 RAG、metadata-aware retrieval、in-text citations、RCS、contradiction detection | LMWR-299~313 |
| OpenKB | `OpenKB-main` | short/long document split、PageIndex tree、wiki compilation、lint/watch/chat/save | LMWR-314~343 |
| llm-wiki-compiler | `llm-wiki-compiler-main` | two-phase compile、hash skip、query --save、chunk-aware query、paragraph source markers | LMWR-314~343 |
| obsidian-llm-wiki-local | `obsidian-llm-wiki-local-master` | draft approval/reject、hand-edit protection、git undo、local-first provider、inline citation toggle | LMWR-269~283 |
| TheKnowledge | `TheKnowledge-main` | source immutability、citation density、wiki validator、draft/finalize、MCP gateway | LMWR-254~298 |
| WikiLoom | `wikiloom-main` | stable chunk_id、chunk store、hybrid linking、duplicates、linked-page expansion | LMWR-254~268 |
| Keppi | `keppi-master` | graph build、blast radius、semantic search、MCP graph tools | LMWR-359~388 |
| OmegaWiki | `OmegaWiki-main` | research entity model、typed edges、papers/concepts/claims/experiments lifecycle | LMWR-239~253 |
| SwarmVault | `swarmvault-main` | context packs、doctor、retrieval manifest、review queues、graph share | LMWR-374~403 |

## 本地 `github/` RAG 参考库（只读）

路径前缀：`C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\github\`

| 参考项目 | 本地路径 | 可借鉴点 | 对应任务 |
| --- | --- | --- | --- |
| LightRAG | `LightRAG-1.4.15` | graph RAG、entity/relation extraction、query modes、reranker as first-class capability | LMWR-359~388 |
| RAG-Anything | `RAG-Anything-1.2.10` | multimodal document parsing、image/table/equation processors | LMWR-404~418 |
| nano-graphrag | `nano-graphrag-0.0.8` | 轻量 GraphRAG storage/query 边界 | LMWR-359~373 |
| Knowledge-Base-Gateway | `Knowledge-Base-Gateway-1.2.2026.10009` | Zotero/EndNote/Obsidian 本地科研库接入 | LMWR-419~433 |
| WeKnora | `WeKnora-main` | Wiki Mode、knowledge graph UI、observability、agent orchestration | LMWR-404~418 |
| Quivr | `quivr-core-0.0.33` | 文档知识库 API 与 retrieval 应用边界 | LMWR-389~403 |
| open-webui | `open-webui-0.8.12` | 知识库 UI、用户权限、模型/检索配置体验 | LMWR-404~418 |

## 网上成熟方案链接

| 项目 | 链接 |
| --- | --- |
| Karpathy LLM-Wiki gist | `https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f` |
| PaperQA2 upstream | `https://github.com/Future-House/paper-qa` |
| OpenKB upstream | `https://github.com/VectifyAI/OpenKB` |
| LightRAG upstream | `https://github.com/HKUDS/LightRAG` |
| RAG-Anything upstream | `https://github.com/HKUDS/RAG-Anything` |
| Microsoft GraphRAG | `https://github.com/microsoft/graphrag` |

## 约束说明

- `github/` 目录和 `llmwiki借鉴库` 均为**只读**参考，不复制外部代码，不改变外部参考库。
- 借鉴思路后必须按本项目的 import/path/test 约束重新实现。
