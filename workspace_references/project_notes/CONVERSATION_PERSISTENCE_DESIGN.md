# 会话持久化设计需求（Conversation Persistence / Resume / Rewind / Fork）

**版本**: v1.0  
**日期**: 2026-04-18  
**状态**: Ready for Implementation  
**适用范围**: Modular 项目本地运行时、后端 API、前端工作台

---

## 1. 背景

当前 Modular 已经具备 `WritingRuntime`、`WritingRuntimeRepository`、`CanonicalEventStore`、`RecoveryConsole` 等会话/事件/恢复底座，但仍缺少一个对终端型 AI 工作流真正可用的“完整会话持久化”能力。

目标是让 Modular 具备接近 Claude Code 的以下体验：

1. 会话会被**本地自动保存**。
2. 保存内容不是摘要，而是**整段 session**：
   - 用户提问
   - 助手回复
   - 工具调用
   - 工具结果
   - 关键上下文元数据
3. 会话与**当前工作区**绑定，能够直接 `resume`。
4. 支持从历史节点进行 `rewind`。
5. 支持从任意历史节点 `fork` 出新分支继续工作。

这项能力是后续实现“可恢复 agent 工作流”“会话级审计”“失败后继续执行”“多分支试错”的基础设施，不应再依赖临时日志、手工复制 prompt 或外部聊天记录。

---

## 2. 对标与成熟方案约束

本需求必须参考成熟方案，而不是闭门造车。实现前必须先复核以下一手资料：

1. Anthropic Claude Code 官方文档：
   - Common workflows / Resume conversation
   - Checkpointing
2. Anthropic Agent SDK 官方文档：
   - Session persistence
   - Fork session
3. 本仓库现有能力：
   - `writing_runtime.py`
   - `repositories/writing_runtime_repository.py`
   - `canonical_event_store.py`
   - `recovery_console.py`
   - `python_adapter_server.py`

基于上述资料，Modular 的实现应吸收以下成熟模式：

1. **本地优先**：会话默认保存在本地，不依赖远端服务。
2. **追加式日志**：完整 transcript 使用 append-only 方式记录，避免覆盖写造成损坏。
3. **索引与正文分离**：使用轻量索引加快检索，同时保留完整原始记录用于恢复。
4. **检查点驱动 rewind/fork**：rewind 与 fork 不是靠猜，而是靠明确的 checkpoint 与 parent/child 指针。
5. **工作区绑定**：从产品体验上，会话与当前工作区绑定，进入工作区即可看到该工作区的最近会话。

---

## 3. 目标与非目标

### 3.1 目标

1. 在本地完整保存会话历史与工具执行轨迹。
2. 在同一工作区内快速恢复最近会话。
3. 支持从历史 checkpoint 回退会话状态。
4. 支持从历史 checkpoint 分叉出新会话分支。
5. 在系统异常退出、前端刷新、后端重启后，仍可恢复会话。
6. 基于现有 runtime/repository/recovery 体系扩展，不平地起一套平行系统。

### 3.2 非目标

1. 不在 MVP 中实现跨设备同步。
2. 不在 MVP 中实现任意 shell 副作用的百分百回滚。
3. 不在 MVP 中替代 Git 分支管理。
4. 不在 MVP 中实现云端会话搜索或团队共享会话。

---

## 4. 术语定义

### 4.1 会话（Session）

一次连续的 AI 协作上下文，包含消息流、工具流、checkpoint、工作区绑定信息。

### 4.2 工作区（Workspace）

用户当前工作的目录上下文。产品语义上按“当前目录”绑定；工程实现上允许采用更稳定的 `workspace_root`：

1. 若当前目录位于 Git 仓库内，优先使用 Git 根目录。
2. 否则使用启动时的当前目录。

### 4.3 Turn

一次用户输入及其对应的一轮助手输出，期间可包含多个工具调用。

### 4.4 Checkpoint

某个可恢复的历史节点，至少对应：

1. transcript 截断位置
2. 工具结果截断位置
3. 工作区文件快照或快照清单

### 4.5 Fork

从某个 checkpoint 派生出新的会话分支，新旧分支后续互不污染。

---

## 5. 用户故事

1. 作为用户，我关闭 Modular 或机器重启后，重新进入同一工作区时，能够继续上一次未完成的会话。
2. 作为用户，我可以查看某次会话里自己说了什么、AI 回了什么、调用了哪些工具、工具返回了什么。
3. 作为用户，我可以在 AI 走偏后回到某个历史节点，而不是重新描述全部上下文。
4. 作为用户，我可以从某个关键节点分叉两条不同思路并行尝试。
5. 作为用户，我希望会话按当前工作区隔离，不被其他目录的历史干扰。
6. 作为开发者，我希望这个能力建立在现有 runtime/recovery 架构上，而不是额外维护第二套状态机。

---

## 6. 功能需求

### FR-1 本地完整会话持久化

系统必须在本地自动持久化完整 session，至少包含：

1. 用户消息
2. 助手消息
3. system/developer 指令快照
4. 工具调用请求
5. 工具调用结果
6. 模型、模式、关键设置
7. 关联 artifact 与关键输出引用
8. 会话创建时间、最后活跃时间、工作区路径

要求：

1. 每个 turn 完成后必须落盘。
2. 每次工具调用完成后必须落盘。
3. 后端异常退出后，已成功返回给前端的数据不得丢失。

### FR-2 工作区绑定

会话必须与工作区绑定。

要求：

1. 同一工作区默认只展示该工作区的会话列表。
2. “继续最近会话”默认命中该工作区最近活跃且未归档的会话。
3. 会话元数据中必须保存：
   - `workspace_root`
   - `workspace_key`
   - `entry_cwd`
4. `workspace_key` 必须基于规范化绝对路径稳定生成。

### FR-3 Resume

系统必须支持恢复历史会话。

要求：

1. 可按 `session_id` 精确恢复。
2. 可按当前工作区恢复最近活跃会话。
3. 恢复后前端可继续展示完整 transcript。
4. 恢复后新的 turn 必须接在原会话 head 后追加，而不是重建会话。
5. 恢复时不得重新执行历史工具调用；历史工具结果应从持久化记录重放。

### FR-4 Rewind

系统必须支持将会话回退到某个 checkpoint。

要求：

1. 可按 `checkpoint_id` 回退。
2. 可按 `turn_id` 自动找到最近 checkpoint 回退。
3. 回退模式至少包含：
   - `conversation_only`
   - `workspace_only`
   - `conversation_and_workspace`
4. 执行 `workspace_only` 或 `conversation_and_workspace` 回退前，系统必须自动创建一次安全回档。
5. 回退完成后必须追加一条 rewind 事件，保证审计链不断裂。

MVP 限制：

1. 仅保证回退通过 Modular 自身文件写入能力产生的文件变更。
2. 任意 shell 命令造成的外部副作用在 MVP 中只要求“显式标记为不可保证完全回退”。

### FR-5 Fork

系统必须支持从任意 checkpoint 分叉出新会话。

要求：

1. 新会话必须保存 `parent_session_id`、`forked_from_turn_id`、`forked_from_checkpoint_id`。
2. fork 后的新分支默认继承：
   - 截止 fork 点的 transcript
   - 截止 fork 点的工具记录
   - 可选的工作区快照恢复
3. fork 之后新旧分支互不覆盖。
4. 前端必须能区分“原会话”和“分叉会话”。

### FR-6 工具调用与结果持久化

工具记录必须是第一类数据，而不是仅写进日志文本。

每条工具调用至少要保存：

1. `tool_call_id`
2. `turn_id`
3. 工具名
4. 请求参数
5. 开始时间 / 结束时间
6. 状态：`started` / `succeeded` / `failed` / `cancelled`
7. 结果 payload 或结果引用
8. 错误信息

大体量结果要求：

1. 超过阈值的结果不得直接塞入索引表。
2. 必须写入 sidecar blob 文件，并在 transcript 中保存引用。

### FR-7 崩溃恢复

系统必须支持崩溃恢复。

要求：

1. 前端刷新后可重新拉取当前会话 head。
2. 后端重启后可恢复会话索引与 transcript。
3. 若 transcript 写入中断，系统必须能检测损坏并恢复到最后一个完整事件。
4. 必须提供最小化修复工具或管理命令用于：
   - 校验会话索引
   - 修复损坏 transcript
   - 重建 checkpoint 索引

### FR-8 删除、归档、导出

系统必须支持基本生命周期管理。

要求：

1. 用户可归档会话。
2. 用户可删除单个会话。
3. 用户可导出完整 transcript。
4. 会话本地存储目录必须默认被 Git 忽略。

建议策略：

1. MVP 默认不自动删除历史会话。
2. 可预留可配置保留期能力。

---

## 7. 数据存储需求

## 7.1 存储位置

建议采用工作区本地隐藏目录：

```text
<workspace_root>/.modular/
  sessions/
    index.sqlite3
    transcripts/
      <session_id>.jsonl
    checkpoints/
      <session_id>/
        <checkpoint_id>.json
        files/
    blobs/
      <blob_id>.json
      <blob_id>.txt
```

说明：

1. `index.sqlite3` 用于快速检索工作区会话、checkpoint、分支关系。
2. `transcripts/*.jsonl` 用于保存完整原始事件流。
3. `checkpoints/` 用于 rewind/fork 的精确恢复。
4. `blobs/` 用于大结果和大上下文分离存储。

### 7.2 Transcript 事件模型

每条 transcript 事件至少包含：

```json
{
  "event_id": "evt_xxx",
  "session_id": "session_xxx",
  "turn_id": "turn_xxx",
  "event_kind": "user_message",
  "timestamp": "2026-04-18T01:00:00Z",
  "workspace_key": "sha256:...",
  "payload": {},
  "parent_event_id": "evt_prev"
}
```

`event_kind` 至少包括：

1. `session_created`
2. `user_message`
3. `assistant_message`
4. `tool_call_started`
5. `tool_call_completed`
6. `tool_call_failed`
7. `checkpoint_created`
8. `session_rewound`
9. `session_forked`
10. `session_archived`

### 7.3 索引模型

`index.sqlite3` 至少需要以下逻辑表：

1. `sessions`
2. `turns`
3. `tool_calls`
4. `checkpoints`
5. `session_branches`
6. `artifacts`

### 7.4 会话主表最低字段

1. `session_id`
2. `workspace_key`
3. `workspace_root`
4. `entry_cwd`
5. `title`
6. `status`
7. `created_at`
8. `updated_at`
9. `last_active_turn_id`
10. `parent_session_id`
11. `forked_from_turn_id`
12. `forked_from_checkpoint_id`

---

## 8. 架构接入要求

必须优先扩展现有模块，而不是旁路实现。

### 8.1 后端

优先修改以下模块：

1. `writing_runtime.py`
   - 增加 transcript 记录、head 管理、resume/rewind/fork 编排
2. `repositories/writing_runtime_repository.py`
   - 增加会话索引、turn、tool_call、checkpoint、branch 持久化
3. `canonical_event_store.py`
   - 对接 rewind/fork/recovery 审计事件
4. `recovery_console.py`
   - 增加会话时间线检查与 checkpoint 恢复入口
5. `models/runtime.py`
   - 增加新的 API payload
6. `python_adapter_server.py`
   - 暴露会话查询、resume、rewind、fork 接口

### 8.2 前端

优先修改以下模块：

1. `frontend/src/types/runtime.ts`
2. `frontend/src/services/writingBackend.ts`
3. `frontend/src/pages/Workbench.tsx`
4. 如有需要，新增会话抽屉 / 会话历史面板

---

## 9. API 需求

基于现有 `/runtime/*` 能力扩展，至少需要以下接口：

1. `POST /runtime/session`
   - 创建会话
   - 新增 `workspace_root` / `entry_cwd` 入参
2. `GET /runtime/sessions`
   - 按 `workspace_key` 列出会话
3. `GET /runtime/session/current`
   - 返回当前工作区最近会话
4. `POST /runtime/session/{session_id}/resume`
   - 恢复历史会话 head
5. `GET /runtime/session/{session_id}/timeline`
   - 拉取完整 transcript / turn 列表
6. `GET /runtime/session/{session_id}/checkpoints`
   - 列出可回退节点
7. `POST /runtime/session/{session_id}/rewind`
   - 回退到指定 checkpoint
8. `POST /runtime/session/{session_id}/fork`
   - 从指定 checkpoint 或 turn 创建新分支
9. `POST /runtime/session/{session_id}/archive`
10. `DELETE /runtime/session/{session_id}`

要求：

1. 所有接口都必须返回稳定 ID，不允许前端自行拼 session id。
2. rewind/fork 响应体必须包含新 head 信息。
3. timeline 接口必须支持分页或 cursor，避免长会话一次性拉爆。

---

## 10. 前端体验需求

前端至少需要以下交互：

1. 当前工作区最近会话提示
2. 会话历史列表
3. 会话标题、最后活跃时间、分支标记
4. resume 按钮
5. rewind 到某个 turn/checkpoint 的入口
6. fork 当前节点的入口
7. 会话归档与删除入口
8. transcript 中可查看工具调用与结果摘要

要求：

1. 默认视图只展示当前工作区会话。
2. fork 出来的会话必须有可见的 branch 提示。
3. rewind 操作必须在 UI 上显示风险提示，尤其是涉及工作区文件恢复时。

---

## 11. 非功能需求

### 11.1 可靠性

1. 所有索引写入必须具备事务性。
2. transcript 写入必须具备断电/异常中断后的可恢复性。
3. 关键索引必须使用 SQLite WAL 或等价可靠策略。

### 11.2 性能

1. 当前工作区最近会话查询应在本地低延迟完成。
2. 长会话 timeline 不得阻塞主 UI。
3. 大工具结果必须与主索引分离。

### 11.3 安全与隐私

1. 会话存储默认仅保存在本地。
2. `.modular/` 必须默认加入 `.gitignore` 或等效忽略机制。
3. 删除会话时必须同步删除 transcript、checkpoint、blob 引用。

---

## 12. 分阶段实施建议

### Phase 1: 持久化底座

1. 建立工作区本地目录结构
2. 建立 `index.sqlite3`
3. 为 session/turn/tool_call 落地 append-only transcript
4. 打通当前工作区最近会话查询

### Phase 2: Resume

1. 前后端接入最近会话恢复
2. 展示会话历史列表
3. 恢复 transcript 与工具记录

### Phase 3: Checkpoint + Rewind

1. 自动生成 checkpoint
2. 增加 rewind API
3. 增加工作区恢复能力
4. 接入 recovery 审计链

### Phase 4: Fork + 生命周期管理

1. 实现分支会话
2. 增加 archive / delete / export
3. 增加 UI 分支标记与筛选

---

## 13. 验收标准

满足以下条件才算完成：

1. 在同一工作区创建会话并执行多轮工具调用后，关闭后端再启动，仍可恢复完整 transcript。
2. transcript 中可以看到用户消息、助手消息、工具调用、工具结果。
3. 在当前工作区可以直接恢复最近会话。
4. 从中间 checkpoint 执行 rewind 后，会话 head 正确回退。
5. 从中间 checkpoint 执行 fork 后，新分支独立可继续对话。
6. 原始分支与 fork 分支后续记录互不污染。
7. `.modular/` 默认不会被 Git 提交。
8. 长工具结果不会把索引库写爆。
9. 后端异常中断后，不会把完整会话结构损坏到无法恢复。

---

## 14. 对其他 AI 的执行约束

下面这段要求必须原样纳入执行提示，不能省略：

```text
在开始实现前，必须先做两件事：
1. 创建回档快照到 `.rollback_snapshots/conversation-persistence-<timestamp>/`
2. 搜索并阅读官方/一手资料中的成熟方案，再决定结构和接口，至少覆盖：
   - Anthropic Claude Code: resume conversation / checkpointing
   - Anthropic Agent SDK: session persistence / fork session
   - 当前仓库已有的 WritingRuntime / WritingRuntimeRepository / CanonicalEventStore / RecoveryConsole

实现约束：
1. 优先扩展现有 runtime / repository / recovery 体系，不要平行再起一套会话系统。
2. transcript 必须完整保存用户消息、助手消息、工具调用、工具结果。
3. 会话必须与当前工作区绑定。
4. 必须支持 resume / rewind / fork。
5. 涉及回退文件时，执行前必须自动创建安全回档。
6. MVP 不要承诺完全回滚任意 shell 副作用；对这类情况必须显式标记限制。

完成后必须验证：
1. 当前工作区最近会话恢复
2. 长 transcript 分页读取
3. rewind / fork 行为正确
4. 本地会话目录不会进入 Git
```

---

## 15. 建议验证清单

建议至少补以下测试：

1. `tests/test_runtime_session_persistence.py`
2. `tests/test_runtime_workspace_binding.py`
3. `tests/test_runtime_resume_flow.py`
4. `tests/test_runtime_checkpoint_rewind.py`
5. `tests/test_runtime_session_fork.py`
6. `tests/test_runtime_transcript_blob_spill.py`

---

## 16. 结论

这不是一个“聊天记录保存”小功能，而是 Modular 进入可恢复 agent 工作流所必需的会话基础设施升级。

实现上必须坚持四个原则：

1. 本地完整持久化
2. 工作区绑定
3. checkpoint 驱动的 rewind / fork
4. 基于现有 runtime/recovery 底座演进
