# 2026-04-29 只读科研资料连接器设计（TASK-160）

## 目标

为本仓补齐 **Zotero / EndNote / Obsidian 本地科研资料入口** 的只读设计，使其可以进入现有项目资料与检索链，但**不**写回外部资料源、**不**把连接器直接耦合进默认主运行时、**不**要求本轮实现 live connector。

本设计的定位是：

- 为后续实现提供边界与合同；
- 复用仓库已经存在的 `source_folder`、`scan-folder`、`citation_anchors`、`folder_traversal`、`extract_literature_context`；
- 先解决“如何安全接入”，再考虑“如何做深度图推理/TOLF”。

## 已确认约束

1. **只读原则**：不得写入 Zotero / EndNote / Obsidian 源资料。
2. **不接默认主链**：连接器设计本轮只做文档与接口边界，不进入默认 runtime。
3. **本地优先**：优先读取本地文件夹、导出文件、附件目录、notes/markdown，而不是依赖在线服务。
4. **证据优先**：所有连接器输出都必须保留来源追溯字段，供后续引用链、证据表、chunk 级定位使用。
5. **复用现有扫描链**：当前项目已经有 `source_folder` + `/resources/project/{id}/scan-folder` 的入口，应避免为连接器平地另起一套资料入库体系。

## 当前仓库里的可复用锚点

### 1. 资料入口已存在 project-scoped source folder

当前后端已经支持：

- 项目级 `source_folder`
- `/resources/project/{project_id}/source-folder`
- `/resources/project/{project_id}/scan-folder`

对应前端已在 `frontend/src/pages/KnowledgeBase.tsx` 中提供：

- 文献文件夹路径展示与编辑
- 扫描文献文件夹按钮
- 扫描结果摘要（indexed / skipped / failed）

这说明连接器设计最自然的落点，不是新增“第二个文献入口”，而是把连接器产出 **挂接到现有 source-folder / scan-folder 模型**。

### 2. 已存在轻量遍历与内容提取合同

当前仓库已有：

- `my-project/src/folder_traversal.py`
  - `collect_folder_records(...)`
  - `traverse_folder(...)`
- `my-project/src/extraction_pipeline.py`
  - `extract_literature_context(...)`
  - `prepare_chat_context(...)`

这两层已经说明：

- 系统具备递归遍历本地资料目录的能力；
- 可以从 JSON / JSONL / CSV / TXT 以及若干已知科研产物格式中提取轻量上下文；
- 能保留 `source_root`、`path`、`relative_path`、`record_type`、`source_file` 等 provenance 字段。

因此连接器不应绕开这条链，而应把外部资料源统一“翻译”为这条链能消费的规范化输入。

## 总体架构

```text
外部科研资料源（只读）
    ↓
Connector Adapter（Zotero / EndNote / Obsidian）
    ↓
Connector Snapshot / Manifest（项目本地 staging）
    ↓
现有 source_folder / scan-folder / folder_traversal / extraction_pipeline
    ↓
materials / chunks / citation anchors / evidence UI / TOLF deep mode
```

核心原则：

- **外部源保持原状**；
- **项目内生成只读快照/清单**；
- **现有扫描链只吃项目内 staging 目录**；
- **后续 deep mode / TOLF 只消费统一规范化后的证据单元**。

## 推荐的 staging 方案

建议后续实现时，将连接器规范化结果写入：

- `{project.source_folder}/.scholarai/connectors/{connector_name}/{snapshot_id}/`

其中只保存：

- 连接器 manifest
- 规范化 metadata
- 可引用 excerpt / note / annotation 快照
- 附件路径引用（不复制大文件，除非用户明确选择导入）

### 为什么要 staging

因为它同时满足三件事：

1. **不碰外部资料源**：所有可变状态只发生在项目自己的 `.scholarai/` 目录；
2. **复用现有扫描链**：`scan-folder` 继续扫本项目 source folder；
3. **保证可审计**：可以记录 snapshot 时间、来源 connector、过滤条件、是否只包含 notes/annotations/fulltext。

## 规范化记录模型

后续建议为三类资料源统一一个 connector-level record 合同：

|字段|说明|
|---|---|
|`connector`|`zotero` / `endnote` / `obsidian`|
|`library_id`|外部资料库标识（可空）|
|`entry_id`|条目标识；要求稳定且可重扫复用|
|`entry_type`|`paper` / `note` / `annotation` / `attachment` / `markdown_note` / `export_record`|
|`title`|主标题|
|`authors`|作者列表|
|`year`|年份|
|`tags`|标签 / collection / vault tags|
|`source_path`|原始本地路径（只读引用）|
|`attachment_paths`|附件路径列表|
|`page`|页码（如有）|
|`excerpt`|用于检索/引用的正文片段|
|`fulltext_available`|是否具备全文/正文可用性|
|`note_text`|笔记正文（如有）|
|`annotation_text`|批注文本（如有）|
|`provenance`|来源追溯：connector、snapshot_id、relative path、export source、timestamps|

注意：

- `excerpt` 与 `annotation_text` 是后续 evidence 与 citation UI 的关键；
- `page` 是当前设计中必须保留的最小引用定位字段；
- `bbox` 若未来补齐 PDF 几何定位，可追加，但不是本切片的硬前提。

## 三类连接器的建议边界

### Zotero（优先级最高）

#### 推荐的读取顺序

1. **本地附件/导出目录**（首选）
2. 本地 notes / annotations 导出
3. 本地 outline / metadata 补充文件
4. 可选：本地 API / sqlite 索引（仅在用户显式允许时）

#### 为什么 Zotero 要先做

- 与本仓“文献助手”的真实使用场景最贴近；
- 当前 repo 历史信息已表明用户有明确的 Zotero 文献库；
- 已知 `jasminum-outline.json` 之类 outline 只能提供大纲和页码线索，但**不足以构成完整结构化元数据**，因此设计上必须允许“元数据不完整，但证据仍可进入系统”。

#### 推荐首版 ingest 单元

- 论文条目 metadata
- PDF 附件路径
- note
- annotation
- outline（如有）

#### 不建议首版做的事

- 写回 Zotero note/tag/collection
- 自动重组 Zotero 库结构
- 强依赖 Zotero 在线服务

### EndNote（首版走 export-first）

EndNote 结构和安装形态通常比 Zotero 更分散，首版不建议碰 live 数据库。

#### 推荐首版只支持

- XML / RIS / BibTeX / plain-text export
- 与 export 同目录的 PDF / 附件文件夹

#### 推荐策略

- **先吃用户导出的静态文件**，而不是直接解析 live library 数据库；
- 这样做最符合“只读 + 可审计 + 易回滚”。

### Obsidian（首版走 vault scan）

#### 推荐读取对象

- Markdown 正文
- frontmatter
- tags
- wikilinks / backlinks
- 嵌入的附件路径

#### 适合的使用方式

Obsidian 更像“研究笔记与个人洞见源”，不完全等于论文主文档源。

因此更适合作为：

- note / synthesis / reading note 入口；
- 与 Zotero / EndNote 条目做双向关联（仅内部关联，不写回）。

#### 首版不要做

- 自动改写 Markdown
- 自动写入 wiki link
- 自动插入 AI 生成内容回 vault

## 模式分层：fast / balanced / deep

参考 `Knowledge-Base-Gateway` 的启发，建议把连接器统一暴露成三档读取策略：

|模式|目标|读取范围|成本/速度|适用场景|
|---|---|---|---|---|
|`fast`|快速确认是否有相关资料|metadata + 标题 + tags + note 标题|最快|问题探索、选题、粗召回|
|`balanced`|形成可引用的轻量证据包|metadata + notes + annotations + markdown note excerpt|中等|问答、比较、写作准备|
|`deep`|为 chunk / TOLF / 证据链准备原料|balanced + attachment/fulltext path + page-level excerpt|最重|深度综述、代表证据链、TOLF deep mode|

设计重点：

- `fast` / `balanced` 可以先于 TOLF 存在；
- `deep` 模式才需要更强的全文/页码/attachment 处理；
- 不论哪一档，都不允许写回外部资料源。

## 与现有项目 API/UI 的衔接建议

### 保守方案（推荐首版）

不新增复杂 connector API，而是在项目层新增“connector snapshot”动作：

- `POST /resources/project/{project_id}/connector/preview`
- `POST /resources/project/{project_id}/connector/snapshot`
- `GET /resources/project/{project_id}/connector/status`

它们的职责分别是：

- `preview`：只读预览将读到多少 item / note / attachment，不写项目状态；
- `snapshot`：把 connector 结果写到 `.scholarai/connectors/...` staging；
- `status`：返回最近一次 snapshot 的 connector、时间、模式、条目数、错误数。

完成 snapshot 后，仍由现有的 `scan-folder` 执行正式入库。这样可以保持：

- connector ≠ ingestion
- connector 负责只读抽取
- scan-folder 负责项目内 ingestion

### 为什么不直接把 connector 做成 scan-folder 的替代品

因为当前 `KnowledgeBase.tsx`、项目 `source_folder`、chunk store 的交互已经存在。最小风险路径是：

- **connector 产 staging**
- **scan-folder 吃 staging**

而不是把 scan-folder 改造成“能直接读三种外部库”的巨型入口。

## 数据安全与治理约束

后续实现必须满足以下 invariants：

1. **禁止写回外部源**：无 note 写回、无 annotation 修改、无 tag 修改、无 collection 操作。
2. **禁止静默复制整个资料库**：除非用户明确导入，否则只保存 manifest / excerpt / path reference。
3. **所有 connector 动作都要有 provenance**：包括 connector 类型、snapshot 时间、模式、来源路径、失败记录。
4. **路径权限显式**：只能读取用户显式选定或项目配置允许的目录。
5. **支持 dry-run / preview**：让用户先看会读什么，再执行 snapshot。

## 推荐的分阶段落地顺序

### Phase A：设计与合同（本切片）

- 定义 connector snapshot contract
- 定义 staging 目录规范
- 定义三档 mode 语义
- 明确只读 hard boundary

### Phase B：Zotero export-first 最小实现

- 先支持附件 + note/annotation export + outline 兼容
- 只做 `preview` + `snapshot`
- 继续复用 `scan-folder`

### Phase C：Obsidian vault 只读接入

- 读取 Markdown / frontmatter / wikilinks
- 支持把 note 作为项目 material/evidence source

### Phase D：EndNote export-first

- 从静态导出入手，不碰 live DB

### Phase E：与 TOLF / 深证据链联动

- 只有当 connector snapshot 合同稳定后，再考虑把 deep mode 接到 TOLF 单元图与代表单元精排。

## 不在本设计内解决的问题

- 如何把引用自动格式化为 APA / MLA / GB/T 7714
- 如何把 bbox 级 PDF 几何定位做到生产可用
- 如何把 Obsidian / Zotero 的内部链接关系同步回原库
- 如何直接解析所有 EndNote live 数据库存储格式

这些都应作为后续独立任务，而不是在第一版 connector 设计里一口吞掉。

## 结论

`TASK-160` 的推荐方向不是“直接把 Zotero / EndNote / Obsidian 接进主运行时”，而是：

- 保持外部资料源只读；
- 在项目 `source_folder/.scholarai/connectors/` 下做 staging snapshot；
- 继续复用现有 `scan-folder`、`folder_traversal`、`extract_literature_context`；
- 让 connector 成为 **证据源适配层**，而不是新的主检索引擎。

这样既能保护用户资料，又能用最小结构改动，为后续 evidence table、citation chain、academic output UI 和 TOLF deep mode 提供统一上游输入。
