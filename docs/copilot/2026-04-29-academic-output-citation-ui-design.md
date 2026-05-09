# 2026-04-29 学术输出与引用 UI 设计（TASK-161）

## 目标

为本仓定义一套面向 **论文写作 / 综述输出 / 证据驱动草稿** 的 UI 设计切片，使输出能够稳定携带：

- source anchors
- evidence table
- citation chain
- 可追溯的 draft ↔ material ↔ chunk / excerpt 关系

本设计的重点不是“做一个更花哨的编辑器”，而是让学术输出真正具备：

1. **证据先于文案**
2. **引用可定位**
3. **草稿与资料库双向可追溯**
4. **后续能承接 TOLF / deep evidence chain**

## 当前仓库已有的 UI / 数据锚点

### 1. 知识库入口已经存在

`frontend/src/pages/KnowledgeBase.tsx` 已具备：

- project-level `source_folder`
- 文献文件夹扫描按钮
- materials 与 chunk 数量统计
- 上传与批量入库摘要

这意味着“学术输出工作台”的资料底座不需要重做，应该在此基础上继续扩展，而不是另起一套资料页。

### 2. 草稿编辑器已经具备 citation anchor 基础设施

当前前后端已经形成最小闭环：

- `models/resources.py` 定义 `CitationAnchorPayload`
- `writing_resources.py` 负责 `citation_anchors` 的归一化与持久化
- `frontend/src/lib/citationAnchors.ts` 定义 token 解析与 anchor range 定位
- `frontend/src/components/DraftStudio.tsx` 在保存/创建草稿时写回 `citation_anchors`
- `frontend/src/components/writing/WritingCanvas.tsx` 支持：
  - 插入 citation token
  - 聚焦 anchor
  - 保存 anchor
- `frontend/src/components/writing/ReferenceDrawer.tsx` 已能按 material 展示 anchor 数量并跳转回文中位置

换句话说，项目已经不是“零引用能力”，而是有了一个可工作的 **anchor spine**。Wave 7 应该做的是把它提升为真正的 academic output UI，而不是推倒重来。

## 当前短板

虽然已有 `citation_anchors`，但它目前仍偏“编辑器内部标记”，距离学术写作工作台还有三段距离：

1. **缺证据表视图**：现在可以插 anchor，但还看不到“每条主张到底由哪些证据支持”。
2. **缺引用链视图**：现在能从 material 找 anchor，不能完整显示“草稿句子 → anchor → source excerpt / page / chunk”。
3. **缺写作质量状态**：现在知道 anchor 数量，但不知道哪些段落无引、哪些引证不足、哪些证据冲突。

## 设计原则

1. **Anchor 只是索引，不是终点**。
   - `[^cite:material:shortid]` 这种 token 适合作为内部稳定锚点；
   - 对用户最终展示时，应该被渲染为更可读的引用 chip、证据表行、导出引用样式。

2. **证据对象要先于排版对象**。
   - 不是先写段落、最后补引用；
   - 而是先绑定 evidence row，再生成/编辑文字表达。

3. **UI 先支持“审计式写作”，再支持“自动写作”**。
   - 如果 evidence 没有准备好，就应该显示 gap，而不是让模型把空白写得很像真的。

4. **与现有 `DraftStudio` 兼容**。
   - 首版设计应落在 `DraftStudio` / `WritingCanvas` / `ReferenceDrawer` 的增量扩展上。

## 建议的整体工作台布局

```text
左栏：项目 / 章节 / 证据覆盖状态
中栏：Draft Canvas（可编辑草稿）
右栏：Evidence / Citation / Review 三标签
底栏：状态条（保存、运行中、证据缺口、导出就绪）
```

### 左栏：章节与证据覆盖导航

在现有章节导航上增加每节的 evidence 状态：

- `green`：有充分 source anchors，且无显著 gap
- `amber`：可写，但 evidence 不足或分布不均
- `red`：存在无引主张或关键段落无 anchor
- `purple`：存在冲突证据，需要 review

#### 推荐显示项

- section 标题
- 当前草稿字数
- anchor 数量
- evidence coverage 百分比
- gap / conflict 数量

这样左栏不再只是 outline，而成为“章节写作健康度面板”。

## 中栏：Draft Canvas 的增强方向

当前 `WritingCanvas.tsx` 已经能：

- 插入 citation token
- 聚焦到 anchor 所在文本
- 显示当前 anchor 数与选中 anchor

建议继续增强为以下三个层次：

### 层 1：保持当前 token 机制，但 UI 语义升级

内部仍保留 `[^cite:material:shortid]` 作为稳定存储格式；
UI 中则把它呈现为：

- inline citation chip
- hover source preview
- click 后打开右栏 Evidence / Citation 面板

### 层 2：段落级 evidence coverage 高亮

为每个段落计算：

- anchor 数量
- 绑定的 material 数量
- 是否存在未引用长段落

推荐样式：

- 段落左侧细线或角标状态
- hover 提示 `2 anchors / 1 gap / 0 conflict`

### 层 3：claim-aware 编辑（后续）

后续可以把段落拆成 claim block，但本切片先不要求复杂 AST。首版只需支持：

- 句段选区 → 插入 source anchor
- anchor → 定位 material / excerpt
- 段落 → 聚合 evidence summary

## 右栏标签设计

建议将当前右侧工具区从“只有助手/历史/灵感”扩展为更偏 academic workflow 的信息结构。

### Tab A：Evidence

这是 Wave 7 的核心新增视图。

每一行 evidence row 代表一个“可引用证据单元”，推荐字段：

|字段|说明|
|---|---|
|`evidence_id`|稳定 ID|
|`material_id`|来源 material|
|`chunk_id`|来源 chunk（如有）|
|`page`|页码（如有）|
|`excerpt`|证据摘录|
|`anchor_count`|当前被多少 anchor 引用|
|`used_in_sections`|被哪些 section 使用|
|`status`|`unused` / `used` / `weak` / `conflict`|
|`score`|检索/重排/人工确认后的排序分数|

#### 交互动作

- 插入到当前草稿
- 预览来源
- 标记为“核心证据”
- 查看被哪些段落引用

### Tab B：Citation Chain

这一栏解决“从文案追到证据”的问题。

建议按当前 draft 中 anchor 的顺序展示：

```text
段落 3
  └─ Anchor #5
      └─ material: xxx
      └─ chunk/page: xxx
      └─ excerpt: xxx
      └─ status: anchored / weak / conflict
```

这会比当前单纯的 `ReferenceDrawer` 更适合审稿式检查，也更贴近“引用链”这个目标。

### Tab C：Review

Review 标签不负责生成，而负责暴露写作质量风险：

- 无引主张（uncited claim）
- 证据过度集中（同一 material 被过度依赖）
- 证据冲突
- 段落过长且无 anchor
- source anchors 存在但没有 page / chunk / excerpt backing

Review 是“不要自信乱写”的最后一道提示层。

## source anchors / evidence table / citation chain 的数据合同建议

当前 `CitationAnchorPayload` 只有：

- `id`
- `materialId`
- `token`
- `startOffset`
- `endOffset`
- `ordinal`

它足够做编辑器 round-trip，但还不够支撑 evidence table / citation chain。

### 建议新增 view-model（不是要求立刻改后端 schema）

#### `EvidenceRowPayload`

|字段|说明|
|---|---|
|`evidence_id`|稳定证据 ID|
|`material_id`|来源 material|
|`chunk_id`|来源 chunk（可空）|
|`page`|页码（可空）|
|`excerpt`|证据摘录|
|`score`|排序分数|
|`provenance`|source path / record type / snapshot id|
|`anchor_ids`|绑定到该证据的 anchor 列表|
|`status`|`unused` / `used` / `weak` / `conflict`|

#### `CitationChainPayload`

|字段|说明|
|---|---|
|`anchor_id`|anchor 稳定 ID|
|`section_id`|所属 section|
|`paragraph_index`|段落序号|
|`material_id`|关联 material|
|`evidence_id`|关联 evidence row|
|`claim_excerpt`|文中 claim 片段|
|`source_excerpt`|来源证据片段|
|`page`|页码（可空）|
|`confidence`|可选质量分|

设计重点：

- 不要求立刻把这些字段并入草稿存储；
- 可以先由 UI 侧根据 materials / chunks / anchors 做聚合 view-model；
- 等 view 稳定后，再决定是否把它们升格成后端 API 合同。

### 2026-04-30 后端导出合同落地状态

`/resources/project/{project_id}/export` 已将上述 view-model 的稳定子集升格为后端导出合同：

- JSON 导出新增 additive fields：`evidence_rows`、`citation_chain`、`review_findings`。
- Markdown 导出追加 `## 证据表`、`## 引用链`，存在审计风险时追加 `## 审计提示`。
- 数据仍从既有 `materials`、`drafts`、`citation_anchors` 派生，不改变 `writing_resources.py` 的持久化 schema。
- `chunk_id`、`page`、`score`、`confidence` 先保持 nullable；等 chunk/page provenance 稳定后再单独升级。

## 推荐的主流程

### 流程 1：资料到草稿

1. 用户在 `KnowledgeBase` 配置 source folder 或导入资料
2. 系统完成 scan / chunk / material 建立
3. 用户在 `DraftStudio` 选择 section
4. 右栏 Evidence tab 显示候选 evidence rows
5. 用户将 evidence 插入草稿，形成 anchor
6. 草稿保存时把 `citation_anchors` 持久化

### 流程 2：从文中回看来源

1. 用户点击文中 citation chip 或右栏 anchor
2. `WritingCanvas` 聚焦到 anchor token
3. 右栏 Citation Chain 高亮对应 evidence row
4. 用户看到 source excerpt / page / material 标题

### 流程 3：写作审计

1. Review tab 扫描当前 section
2. 标出无引段落 / 证据过弱段落 / 冲突段落
3. 用户决定补证据、调整表达、或保留并注明 limitation

## 与 TOLF / 深证据链的关系

本设计必须支持“先不用 TOLF，也能工作；以后接 TOLF，不需要推翻”。

因此建议：

- `Evidence` tab 的输入先来自现有 materials / chunks / retrieval hits；
- 未来若接 TOLF，则把：
  - fish cluster representative
  - evidence gate 结果
  - representative rerank 结果
  映射为同一套 evidence row / citation chain 视图；
- UI 不应硬编码“证据一定来自某种检索器”。

换句话说，UI 合同应该是 **retriever-agnostic / TOLF-compatible**。

## 导出层建议

最终论文输出不应该把原始 token 暴露给用户。

推荐分两层：

1. **编辑器内部表示**：`[^cite:material:shortid]`
2. **导出表示**：
   - Markdown footnote / inline citation
   - DOCX footnote / endnote
   - 审稿视图中的 source anchor chip

当前 Wave 7 只做设计，因此导出合同先定义目标，不要求实现。

## 分阶段落地建议

### Phase A：UI 文档与 view-model 定义（本切片）

- 明确 Evidence / Citation Chain / Review 三个视图
- 明确 anchor spine 与 view-model 的关系

### Phase B：DraftStudio 增量实现

- 保留当前编辑器结构
- 新增 Evidence tab
- 新增 Citation Chain tab
- 为段落增加 evidence coverage 状态

### Phase C：Review 规则最小实现

- 无引段落提示
- anchor 失配提示
- 证据过度集中提示

### Phase D：导出与样式映射

- Markdown / DOCX / 审稿视图

### Phase E：与 deep mode / TOLF 对接

- 将 TOLF 输出映射为 evidence rows / citation chains

## 不在本设计内解决的问题

- 自动生成完整 bibliography 格式
- 自动判断学术规范是否完全符合目标期刊模板
- 自动处理所有 citation style 细节
- 对每个 claim 做严格 NLP 级事实抽取

这些都可以是后续增量，但不应该阻塞当前 academic output UI 的基本闭环。

## 结论

`TASK-161` 的正确方向，不是再做一个“普通富文本编辑器”，而是把现有：

- `KnowledgeBase`
- `DraftStudio`
- `WritingCanvas`
- `ReferenceDrawer`
- `CitationAnchorPayload`

这条已经存在的骨架，升级为一个真正的 **evidence-first academic writing workspace**。

首版最重要的不是自动写得多好，而是让用户和后续 agent 都能明确看到：

- 这段话用了什么证据
- 这条引用落在哪里
- 哪些地方还缺证据
- 哪些证据彼此冲突

当这些基础能力成立后，后续不论接普通 retrieval、deep mode，还是 TOLF representative evidence chain，UI 都能稳定承接，而不会变成“写得越多，越说不清证据从哪来”。
