# Scholar AI MCP 能力地图（agent 上手入口）

> 给 Claude / Codex 的单文件导航：文献助手有什么工具、对应什么代码、怎么按场景串起来。
> 真实工具清单以 MCP `list_tools` 和 `agent_mcp_server/src/lit_assistant_mcp/server.py`
> 注册口径为准；本文件的工具名索引由测试约束，避免静默漂移。

## 三跳定位法（工具 → 代码）

任一工具的实现都能三跳读到：

1. **注册口**：`agent_mcp_server/src/lit_assistant_mcp/server.py`，搜 `name="<工具名>"`，看签名与一句话 docstring。
2. **委托实现**：按前缀分流——
   - `source.*` → `tools/source.py`（只读源码检查，不碰后端）
   - `literature.*` → `tools/runtime.py`（HTTP 调后端）/ 实验类在 `tools/experimental.py`
   - `workflow.* / artifact.*` → `tools/workflow.py` + `workflow_runtime/`
3. **后端真源**：`literature.*` 落到 `runtime.py` 里的 `endpoint=`，对应 FastAPI 路由在 `literature_assistant/core/`（用 `source.inspect_routes` 反查）。

## 连上先做什么

```text
literature.config_status        # 后端通不通（GET /health）
literature.health_check         # workflow 就绪度（被动诊断，不触发副作用）
literature.list_projects        # 拿 project_id（GET /resources/projects）
```

后端没起时 `literature.*` 返回有界的 "backend unavailable"，需用户手动开 `文献助手` 桌面端；`source.*` 不依赖后端，始终可用。

## 典型链路（按研究动作）

| 动作 | 工具链 |
|---|---|
| 入库 | `literature.project_scan_folder` → `literature.list_materials` → `literature.get_material_chunks` |
| 问答取证 | `literature.search_refs` → `literature.evidence_pack_build` → `literature.evidence_integrity_gate` |
| 写作 | `evidence_pack_build` → `literature.outline_generate` → `literature.academic_writing_lint` → `literature.figures_generate` → `literature.export_docx` |
| 引用核对 | `literature.citations_sources` → `literature.citations_detect_overlap` |
| 读源码 | `source.inspect_routes` → `source.read_symbols` → `source.read_file` → `source.find_references` |
| agent 协作交接 | `agent_request_create` → `agent_progress` → `agent_result` / `agent_fail` → `agent_handoff_card` |

---

## 分组工具清单

### 1. 源码检查 source.*（`tools/source.py`，只读、不依赖后端）

| 工具 | 作用 |
|---|---|
| `source.list_tree` | 列允许目录下的文件树 |
| `source.search` | 在允许源码里搜字面文本 |
| `source.read_file` | 读单个允许的源码文件 |
| `source.read_symbols` | 抽取 Python 顶层符号 |
| `source.inspect_routes` | 不导入模块、静态扫 FastAPI 路由装饰器 |
| `source.find_references` | 有界静态查标识符/字面量引用 |
| `source.explain_entrypoints` | 从入口文件勾勒 import 可达图 |

### 2. 配置与健康 / Zotero（`tools/runtime.py`）

| 工具 | 作用 | 后端 |
|---|---|---|
| `literature.config_status` | 后端健康 | `GET /health` |
| `literature.health_check` | 被动 workflow 就绪诊断 | `/api/health/check` |
| `literature.zotero_attachment_health` | 只读 Zotero 附件健康 | `/api/zotero/attachment-health` |

### 3. 项目与材料（`tools/runtime.py`）

| 工具 | 作用 | 后端 |
|---|---|---|
| `literature.list_projects` | 列项目 | `/resources/projects` |
| `literature.list_materials` | 列项目材料 | `/resources/materials` |
| `literature.read_material` | 读材料记录 | `/resources/material/{id}` |
| `literature.get_material_chunks` | 读材料分块 | `/resources/material/{id}/chunks` |
| `literature.project_scan_folder` | 提交项目源文件夹入库为 runtime job（scan_mode=fast/legacy） | 见 runtime.py |

### 4. 检索与证据（核心问答链）

| 工具 | 作用 | 后端 |
|---|---|---|
| `literature.search_refs` | 检索分块、只回 refs | `/resources/chunks/search-refs` |
| `literature.evidence_pack_build` | 构建证据包 | `/api/evidence-pack/build` |
| `literature.evidence_integrity_gate` | 读证据完整性投影（按 session/job/project 过滤） | 见 runtime.py |
| `literature.knowledge_context_receipt` | 知识上下文回执 | `/api/knowledge/context-receipt` |

### 5. 知识库 / Wiki / 词典 / 评分规则（`/api/knowledge/*`、`/api/wiki/*`）

| 工具 | 作用 |
|---|---|
| `literature.knowledge_packages` / `knowledge_runtime_conformance` | 知识包列表 / 运行时一致性 |
| `literature.wiki_status` / `wiki_search` / `wiki_import` | Wiki 状态 / 搜索 / 导入 |
| `literature.skill_package_status` / `skill_package_search` | 技能包状态 / 搜索 |
| `literature.source_vault_status` / `source_vault_search` / `source_vault_read` | 源码保险库三件套 |
| `literature.academic_english_status` / `academic_english_search` | 学术英语库 |
| `literature.bridge_lexicon_status` / `bridge_lexicon_read` / `bridge_lexicon_search` | 跨语言桥接词典 |
| `literature.scoring_rules_status` / `scoring_rules_read` / `scoring_rules_search` | 评分规则 |
| `literature.product_docs_status` / `product_docs_read` / `product_docs_search` | 产品文档 |

### 6. OCR（`/api/pdf-backend/ocr-*`，部分实验门控）

| 工具 | 作用 |
|---|---|
| `literature.ocr_status` / `ocr_engines` / `ocr_health` / `ocr_execution_probe` | OCR 状态 / 引擎 / 健康 / 执行探针 |
| `literature.ocr_material` | 对材料跑 OCR（实验门控） |

### 7. 图表 / 引用 / 写作 / 导出

| 工具 | 作用 |
|---|---|
| `literature.figures_candidates` / `figures_generate` | 图表候选 / 生成 |
| `literature.citations_sources` / `citations_detect_overlap` | 引用来源 / 重叠检测 |
| `literature.outline_generate` | 大纲生成 |
| `literature.academic_writing_lint` | 学术写作 lint |
| `literature.journal_style_spec_draft` / `journal_style_spec_confirm` | 期刊风格规范草拟 / 确认 |
| `literature.export_annotations_markdown` / `export_docx` / `export_project_pack` | 导出批注 / DOCX / 项目包 |
| `literature.translate_pack` / `prepare_visual_review` | 翻译包 / 视觉复审（实验门控） |

### 8. Agent 桥接与协作（`/api/agent-bridge/*`）

| 工具 | 作用 |
|---|---|
| `literature.agent_bridge_status` | 桥接状态 |
| `literature.agent_workspace_status` / `agent_workspace_requirement` | agent 工作区状态 / 需求 |
| `literature.agent_request_create` / `agent_request_list` / `agent_request_read` | 请求创建 / 列表 / 读取 |
| `literature.agent_resource_read` | 读桥接资源 |
| `literature.agent_progress` / `agent_result` / `agent_fail` | 进度 / 结果 / 失败上报 |
| `literature.agent_handoff_card` | 交接卡 |
| `literature.single_paper_task_create` / `single_paper_completion_check` | 单篇任务创建 / 完成检查 |

### 9. Workflow 护栏与回放

| 工具 | 作用 |
|---|---|
| `literature.workflow_passport` | workflow 护照 |
| `literature.workflow_refresh_receipt` | 刷新回执 |
| `literature.workflow_replay_lineage` / `workflow_replay_index` | 回放血缘 / 索引 |
| `literature.research_action_lifecycle` | 研究动作生命周期 |
| `literature.behavior_eval_pack` | 行为评测包 |

### 10. 工作流引擎与产物（`tools/workflow.py`）

| 工具 | 作用 |
|---|---|
| `workflow.create_plan` | 创建计划 |
| `workflow.write_json_workflow` / `run_json_workflow` | 写 / 跑 JSON workflow |
| `workflow.run_python_sandbox` | 有界 Python 沙箱（实验门控） |
| `artifact.write_markdown` / `read_artifact` / `list_artifacts` | 产物读写列举 |

---

## 完整工具名索引

```text
artifact.list_artifacts
artifact.read_artifact
artifact.write_markdown
literature.academic_english_search
literature.academic_english_status
literature.academic_writing_lint
literature.agent_bridge_status
literature.agent_fail
literature.agent_handoff_card
literature.agent_progress
literature.agent_request_create
literature.agent_request_list
literature.agent_request_read
literature.agent_resource_read
literature.agent_result
literature.agent_workspace_requirement
literature.agent_workspace_status
literature.behavior_eval_pack
literature.bridge_lexicon_read
literature.bridge_lexicon_search
literature.bridge_lexicon_status
literature.citations_detect_overlap
literature.citations_sources
literature.config_status
literature.evidence_integrity_gate
literature.evidence_pack_build
literature.export_annotations_markdown
literature.export_docx
literature.export_project_pack
literature.figures_candidates
literature.figures_generate
literature.get_material_chunks
literature.health_check
literature.journal_style_spec_confirm
literature.journal_style_spec_draft
literature.knowledge_context_receipt
literature.knowledge_packages
literature.knowledge_runtime_conformance
literature.list_materials
literature.list_projects
literature.ocr_engines
literature.ocr_execution_probe
literature.ocr_health
literature.ocr_material
literature.ocr_status
literature.outline_generate
literature.prepare_visual_review
literature.product_docs_read
literature.product_docs_search
literature.product_docs_status
literature.project_scan_folder
literature.read_material
literature.research_action_lifecycle
literature.scoring_rules_read
literature.scoring_rules_search
literature.scoring_rules_status
literature.search_refs
literature.single_paper_completion_check
literature.single_paper_task_create
literature.skill_package_search
literature.skill_package_status
literature.source_vault_read
literature.source_vault_search
literature.source_vault_status
literature.translate_pack
literature.wiki_import
literature.wiki_search
literature.wiki_status
literature.workflow_passport
literature.workflow_refresh_receipt
literature.workflow_replay_index
literature.workflow_replay_lineage
literature.zotero_attachment_health
source.explain_entrypoints
source.find_references
source.inspect_routes
source.list_tree
source.read_file
source.read_symbols
source.search
workflow.create_plan
workflow.run_json_workflow
workflow.run_python_sandbox
workflow.write_json_workflow
```

---

## 安全边界（所有工具硬约束）

不得通过 MCP/source/workflow 读取或导出：`.env*`、credential stores、runtime state、logs、
browser profiles、rollback snapshots、`.claude/`、`.codex/`。实验类工具（OCR 生成、视觉复审、
翻译包、项目包、Python 沙箱）由 `LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1` 门控。
