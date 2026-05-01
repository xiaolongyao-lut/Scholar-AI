# Conversation Persistence MVP — 细化执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `CONVERSATION_PERSISTENCE_DESIGN.md` 的会话持久化需求落地为最小可用闭环（后端已交付 → 前端接入 → 测试 → 验收）。
**Architecture:** 后端优先 + 前端薄接入 + 本地优先存储（SQLite 索引 + JSONL transcript + blob sidecar）。
**Tech Stack:** Python / FastAPI (runtime), React + TypeScript (frontend), SQLite (index), filesystem JSONL (append-only).

---

## 1. 上下文（为什么单独立计划）

本计划从 `docs/superpowers/plans/2026-04-20-latest-unified-plan.md §8` 的建议位置派生，把 U2 / U3 两段抽出为独立推进单元。原因：

1. U2 后端已由 Ralph 在 2026-04-24 交付（`/runtime/sessions` `/resume` `/timeline` `/rewind` `/fork` `/checkpoints` 已 Tank 批准）。
2. U3 前端仍未启动，且与 `Workbench` / `IntelligentChat` 的交互契约变更较大，需独立 scope 控制。
3. 全量设计 `CONVERSATION_PERSISTENCE_DESIGN.md` 跨度大（SQLite schema + blob spill + workspace binding），MVP 先锁定"能恢复 + 能看见时间线 + 能 fork"。

---

## 2. 现状盘点（2026-04-24）

### 2.1 已完成

| 项 | 状态 | 证据 |
|---|---|---|
| `.rollback_snapshots/conversation-persistence-<ts>/` 回档机制 | ✅ 2026-04-24 | unified-plan §U2-1 |
| `writing_runtime.py` session head / timeline cursor / resume 编排 | ✅ 2026-04-24 | unified-plan §U2-2 |
| Transcript JSONL append-only writer + 损坏恢复 | ✅ 2026-04-24 | unified-plan §U2-4 |
| Runtime API：`/runtime/sessions` `/session/current` `/resume` `/timeline` `/checkpoints` `/rewind` `/fork` | ✅ 2026-04-24 | unified-plan §U2-5, `routers/runtime_router.py` |
| Workspace binding：`workspace_root / workspace_key / entry_cwd` | ✅ 2026-04-24 | unified-plan §B-4 |
| 后端 QA 验收套件（`test_writing_runtime.py` + `test_writing_runtime_persistence.py` + `test_session_memory_resume.py` + `test_runtime_router_contract.py`） | ✅ 2026-04-24 | Ralph 修订后 Tank APPROVED |

### 2.2 仍未完成（本计划的执行对象）

| 项 | 预估工作量 | 出处 |
|---|---|---|
| `.modular/sessions/index.sqlite3 + transcripts/*.jsonl + checkpoints + blobs` 完整存储体系 | 中 | unified-plan §U2-3 |
| 持久化 / workspace 隔离 / resume / rewind / fork / blob spill 端到端测试 | 中 | unified-plan §U2（验证栏） |
| 前端 `frontend/src/types/runtime.ts` 扩展 | 小 | unified-plan §U3-1 |
| 前端 `frontend/src/services/writingBackend.ts` 扩展 | 小 | unified-plan §U3-2 |
| `Workbench` session drawer + history + resume/fork/rewind 入口 | 大 | unified-plan §U3-3 |
| archive / delete / export 交互 | 中 | unified-plan §U3-4 |

---

## 3. MVP 范围定义

### 3.1 MVP 做

- S-1 后端存储体系补齐（SQLite 索引 + transcript JSONL + blob sidecar）
- S-2 端到端测试：持久化、workspace 隔离、resume、rewind、fork、blob spill
- S-3 前端 types + service 扩展（纯契约层）
- S-4 `Workbench` 加一个最小 session drawer：列最近 10 条会话 + resume 按钮 + timeline 查看 + fork 按钮
- S-5 `Workbench` 加 rewind 确认弹窗（涉及文件恢复时必须警告）

### 3.2 MVP 不做（推到 Post-MVP）

- ❌ archive / export / delete 交互（保留入口，不实现逻辑）
- ❌ 跨设备同步
- ❌ 工作区搜索 / 跨 workspace 会话合并
- ❌ Cloud sync / team sharing
- ❌ UI 国际化扩展（沿用现有 i18n 架构即可）
- ❌ `IntelligentChat` 页面的独立 session 管理（MVP 只在 `Workbench` 落地）

---

## 4. 任务分解（按 TDD + 小步提交）

### Task S-1：后端存储体系补齐

**Files:**

- Create: `.modular/sessions/` 目录结构约定（约定文档 + 初始化脚本）
- Modify: `repositories/writing_runtime_repository.py`（sqlite index schema + transcript/blob 索引）
- Modify: `writing_runtime.py`（spill 阈值：单条工具结果 > 64KB 写 blob sidecar）
- Test: `tests/test_writing_runtime_blob_spill.py`（新）

**存储布局（强约束，与 `CONVERSATION_PERSISTENCE_DESIGN.md §5-6` 对齐）**：

```
.modular/
  sessions/
    index.sqlite3                      # 会话 / turn / tool_call / checkpoint / branch 索引
    transcripts/
      {session_id}.jsonl               # append-only 原始 transcript（每行一个事件）
    checkpoints/
      {session_id}/
        {checkpoint_id}.json           # 检查点元数据 + 指向 transcript 行号
    blobs/
      {session_id}/
        {blob_id}.bin                  # 大工具结果 spill（> 64KB）
```

**Steps:**

- [ ] **S-1.1**：写失败测试 `tests/test_writing_runtime_blob_spill.py`
  - `test_large_tool_result_spills_to_blob`：工具结果 > 64KB → transcript 只写引用 `{"ref": "blob:...}"}`，实际内容在 `blobs/`
  - `test_blob_read_through_rehydrates_transcript`：resume 时自动 rehydrate
- [ ] **S-1.2**：实现 spill 阈值 + blob writer
- [ ] **S-1.3**：扩展 SQLite schema（tables：`sessions / turns / tool_calls / checkpoints / branches`）
  - DDL 写在 `repositories/writing_runtime_repository.py` 顶部常量或独立 `schema.sql`
  - 用现有 connection helper，不新增 DB driver
- [ ] **S-1.4**：所有新 DDL 走 migration 思路（脚本 `scripts/migrate_modular_sessions.py`）
- [ ] **S-1.5**：跑 `pytest tests/test_writing_runtime*.py -q` 全绿

**验收**：
- `.modular/sessions/index.sqlite3` 存在且 schema 符合设计文档 §5
- 构造 128KB 工具结果 → transcript 行体积 < 1KB（只存 ref）
- blob 目录总大小 ≈ 实际工具结果总和

---

### Task S-2：端到端测试补齐

**Files:**

- Create: `tests/test_conversation_persistence_e2e.py`（新）

**Steps:**

- [ ] **S-2.1**：`test_resume_after_backend_restart` — 起 runtime → 发 3 轮 → kill → 重启 → `/resume?session_id=...` 返回完整 timeline
- [ ] **S-2.2**：`test_workspace_isolation` — 在 workspace A 创建会话 → 切到 workspace B → `/runtime/sessions` 列表只包含 B
- [ ] **S-2.3**：`test_rewind_restores_state` — 到 checkpoint N → `/rewind` → head 回到 N，timeline 只剩 ≤ N
- [ ] **S-2.4**：`test_fork_preserves_parent_child` — 从 checkpoint N `/fork` → 新 session_id，`parent_session_id` 指向原会话，`branch_point` 指向 N
- [ ] **S-2.5**：`test_corrupted_transcript_recovery` — 人为截断 transcript JSONL 末尾几行 → resume 不崩，跳到最后一条完整记录 + 告警

**验收**：`pytest tests/test_conversation_persistence_e2e.py -q` 5/5 绿。

---

### Task S-3：前端 types + service 扩展

**Files:**

- Modify: `frontend/src/types/runtime.ts`
- Modify: `frontend/src/services/writingBackend.ts`
- Create: `frontend/src/services/sessionApi.ts`（独立模块，隔离 session 相关 API 调用）

**契约（对齐后端 OpenAPI，禁止手写 schema）**：

```ts
// frontend/src/types/runtime.ts 追加
export interface SessionSummary {
  session_id: string;
  workspace_key: string;
  entry_cwd: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  checkpoint_count: number;
  parent_session_id?: string;
  branch_point_checkpoint_id?: string;
}

export interface TimelineEvent {
  turn_index: number;
  kind: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  payload: unknown;           // 保持 unknown，消费侧自己做 narrow
  ref?: string;               // blob ref，仅 spill 时存在
}

export interface CheckpointMeta {
  checkpoint_id: string;
  turn_index: number;
  created_at: string;
  label?: string;
}
```

**Steps:**

- [ ] **S-3.1**：从 `frontend/src/generated/openapi.ts` 重新生成 typing（如果后端 OpenAPI 已更新）
- [ ] **S-3.2**：`sessionApi.ts` 暴露 `listSessions / getCurrent / resume / getTimeline / listCheckpoints / rewind / fork`
- [ ] **S-3.3**：在 `writingBackend.ts` re-export，保持单一入口

**验收**：`npm run build` 绿；`tsc --noEmit` 无错。

---

### Task S-4：Workbench Session Drawer（UI）

**Files:**

- Modify: `frontend/src/pages/Workbench.tsx`
- Create: `frontend/src/components/writing/SessionDrawer.tsx`（新）

**UI 约束**：

| 元素 | 规范 |
|---|---|
| 入口 | Workbench 顶部工具栏右侧加 "会话" 按钮（Drawer trigger） |
| 列表 | 默认当前 workspace 最近 10 条，按 `updated_at` 倒序 |
| 单条展示 | session_id 前 8 位 + 首 user prompt 前 40 字 + 更新时间 + turn 数 |
| 分叉标记 | 若 `parent_session_id` 非空，显示 fork 图标 + 指向原会话的链接 |
| Resume | 点击 → `/resume` → 把 timeline 注入当前 workbench 上下文 |
| Timeline 查看 | 展开单条会话 → 显示全部 turns（user / assistant / tool_call / tool_result 四色区分） |
| Fork | timeline 上每个 checkpoint 旁边一个 "fork" 按钮 |
| Rewind | timeline 上每个 checkpoint 旁边一个 "rewind" 按钮 + 二次确认弹窗 |

**Steps:**

- [ ] **S-4.1**：骨架组件 `SessionDrawer.tsx`，打开/关闭 + 列表渲染
- [ ] **S-4.2**：接入 `listSessions`；loading / empty / error 三态
- [ ] **S-4.3**：单条展开 → 拉 timeline；分页（每次 50 行）
- [ ] **S-4.4**：resume 按钮 → 调用 `/resume` → 触发 Workbench 内容刷新（用现有 `WritingContext.dispatch`）
- [ ] **S-4.5**：fork 按钮 → 确认弹窗 → 调用 `/fork` → 跳到新 session
- [ ] **S-4.6**：单元测试 `frontend/tests/SessionDrawer.test.tsx`（至少覆盖列表渲染 + resume 点击）

**验收**：
- 手动：起两个 workspace，分别创建会话 → 切换 workspace → drawer 列表正确隔离
- 自动：`vitest run` 绿

---

### Task S-5：Rewind 安全闸门

**Files:**

- Modify: `frontend/src/components/writing/SessionDrawer.tsx`
- Create: `frontend/src/components/writing/RewindConfirmModal.tsx`（新）

**安全规范（SPEC-SESSION-005 对齐）**：

- rewind 涉及 workspace 文件时，必须先触发后端 `.rollback_snapshots/` 自动回档
- 前端 UI 必须显示：
  1. "即将回退到 turn #N"
  2. "会自动创建 `.rollback_snapshots/rewind-<ts>/` 快照，不会丢失当前状态"
  3. "恢复后当前会话的 turns > N 会被标记为 archived（不删）"

**Steps:**

- [ ] **S-5.1**：实现确认弹窗组件
- [ ] **S-5.2**：接入 drawer 的 rewind 按钮
- [ ] **S-5.3**：后端 `/rewind` 返回 `{rollback_snapshot_path, archived_turns_count}` → 前端成功态显示

**验收**：手动演练一次 rewind，查 `.rollback_snapshots/` 里有新快照。

---

## 5. DoD（Definition of Done）

### 5.1 后端

- [ ] `.modular/sessions/index.sqlite3` schema 与 `CONVERSATION_PERSISTENCE_DESIGN.md §5` 一致
- [ ] blob spill 阈值生效，> 64KB 走 sidecar
- [ ] `tests/test_conversation_persistence_e2e.py` 5 case 全绿
- [ ] `.modular/` 已加入 `.gitignore`（若未有）
- [ ] 后端重启后 `/runtime/sessions` 返回完整列表

### 5.2 前端

- [ ] `npm run build` 绿
- [ ] Workbench 能看到当前 workspace 最近 10 条会话
- [ ] resume / fork / rewind 三按钮功能闭环
- [ ] rewind 前有确认弹窗 + 快照路径提示
- [ ] 长 transcript 分页正常（50 行/页，滚动加载）

### 5.3 集成

- [ ] 手动演练：创建会话 → 3 轮对话 → 关闭前端 → 重启 → 会话列表里可见 → resume 后 timeline 完整
- [ ] 手动演练：fork 出新会话 → 在新会话继续 → drawer 里能看到父子关系图标
- [ ] 手动演练：rewind 到 checkpoint N → 产物文件已从 `.rollback_snapshots/` 恢复

---

## 6. 风险与回滚

| 风险 | 影响 | 应对 |
|---|---|---|
| SQLite schema migration 失败 | 老会话读不出 | `scripts/migrate_modular_sessions.py` 必须 idempotent + dry-run 模式；首次执行前备份 `.modular/` 到 `.rollback_snapshots/` |
| blob spill 阈值误判 | 小工具结果走 sidecar，性能下降 | 阈值可 env 覆盖 `MODULAR_BLOB_SPILL_BYTES`（默认 65536），应急调高 |
| 前端 drawer 在 workspace 切换时状态泄漏 | 看到别人 workspace 的会话 | S-3.1 中 types 必须 require `workspace_key`；UI 侧强制按 key 过滤；S-2.2 测试覆盖 |
| rewind 恢复文件时覆盖用户未提交改动 | 丢数据 | S-5 强制创建 `.rollback_snapshots/` 后才允许继续；UI 文案要显式警告 |

### 6.1 分级回滚

1. **S-4 / S-5 前端**：`git revert` 该 PR → UI 隐藏 drawer，后端 API 仍可用（命令行测试不受影响）
2. **S-1 / S-2 后端**：`git revert` + 恢复 `.modular/sessions/` 备份（migration 运行前的快照）
3. **紧急全关**：env `MODULAR_SESSION_PERSISTENCE=0` → runtime 退化为 in-memory only（不落盘）

---

## 7. 排期建议（team 接手后）

| 阶段 | 负责 | 预估 | 依赖 |
|---|---|---|---|
| S-1 后端存储体系 | Trinity | 1-2 天 | 无（基础已在主干） |
| S-2 E2E 测试 | Tank / Ralph | 0.5 天 | S-1 完成 |
| S-3 前端契约 | Dozer | 0.5 天 | 后端 OpenAPI 确认稳定 |
| S-4 Workbench drawer | Switch + Dozer | 1-1.5 天 | S-3 完成 |
| S-5 Rewind 安全闸 | Switch | 0.5 天 | S-4 完成 |

**关键路径**：S-1 → S-2 → S-3 → S-4 → S-5（严格顺序）

---

## 8. 上游文档与决策引用

- 需求：`CONVERSATION_PERSISTENCE_DESIGN.md`
- 整合计划：`docs/superpowers/plans/2026-04-20-latest-unified-plan.md §5 / §6.2`
- 审批：`.squad/decisions.md → "U2 Conversation Persistence API MVP — Ralph revised"`
- 阻塞追踪：`OPEN_THREADS.md → A7 [conversation-persistence-mvp-followthrough]`
- 相关 charter：`.squad/agents/ralph/history.md` 2026-04-24 条目

---

## 9. Out of scope（明确拒绝）

- 跨设备同步（Cloud / S3 / git remote）
- IntelligentChat 页面的独立 session drawer（等 MVP 在 Workbench 跑稳再扩散）
- 会话内容 semantic search（属于 §U6 Cross-session retrieval，独立计划）
- 导出 markdown / 导出 PDF（属于 Post-MVP）

---

**Created**: 2026-04-24 (Claude, post squad audit)
**Status**: Ready for team pickup (S-1 开始即可)

---

## 10. S-1 Addendum — D 方案（2026-04-25, post-recon）

### 10.1 背景（为什么原 S-1 范围要缩）

Recon 发现 Copilot 在 U1/U2 阶段已经实现了 §S-1 的大部分行为：
`append_transcript_event` (JSONL + fsync + atomic replace)、`_spill_blob`
(atomic `.tmp` + `os.replace`)、`load_transcript(repair=True)`（损坏行修复）、
`rewind_session` 的 `.rollback_snapshots/` 归档、`_prepare_transcript_event`
的 spill 分支 —— 全都落地了。

但 Morpheus 在复核时找到一个**真正的行为缺口**：

> spill 写出去了，`load_transcript` 读回来的是 `{"blob_ref": {...}, "inlined": false}`
> 引用壳，`_hydrate_transcripts_from_repository` 和 `_ensure_transcript_loaded`
> 都**没有 read-through 逻辑**，resume 后时间线里拿到的 payload 是引用而不是
> 原始内容 —— round-trip 没闭环。

因此原 §S-1 的重构范围（表重命名、blob 路径重排、per-session 子目录）
按 CLAUDE.md "Surgical Changes / Simplicity First" 原则 **全部暂缓**，
改做范围收敛后的 D 方案。

### 10.2 D 方案范围（确认要做 / 确认暂缓）

**要做**：

| ID | 任务 | 动因 |
|---|---|---|
| D-1 | spill 阈值 `8192 → 65536` | 对齐 plan §S-1.3 |
| D-2 | 引入环境变量 `MODULAR_BLOB_SPILL_BYTES`，默认 65536 | 运维可调；测试可注入低阈值 |
| D-3 | **blob read-through**：在 `load_transcript` 或 repository 的读取路径里，遇到 `{"blob_ref": ..., "inlined": false}` 时把 blob 内容读回填充 payload | Morpheus 发现的真实缺口 |
| D-4 | 新增 focused regression test `tests/test_writing_runtime_blob_spill.py`：(a) 大 payload 触发 spill (b) resume/load 后 payload 与原文一致 | TDD，锁死行为不回归 |
| D-5 | 新增 `scripts/migrate_modular_sessions.py`：幂等，验证 schema 版本 / `transcripts/` / `blobs/` 存在，不存在就 mkdir，不做 schema 变更 | plan §S-1 里要求有此脚本；占位 + 健康检查 |

**暂缓（写入 §Out of scope，未来触发条件见 §10.4）**：

- 表重命名 `jobs / events / artifacts → turns / tool_calls / branches`
- blob 路径 `blobs/{id}.json → blobs/{session_id}/{id}.bin`
- 数据迁移（要真要改上面两项才需要）
- archive / delete / export / rollback UX 的大翻修

### 10.3 执行顺序（严格 TDD）

1. **先写测试** `tests/test_writing_runtime_blob_spill.py`（D-4）：
   - `test_large_tool_result_spills_to_blob`：payload ≥ 阈值时，磁盘上 JSONL 行里出现 `blob_ref`，blob 文件存在。
   - `test_blob_read_through_rehydrates_transcript`：spill 后调用 `load_transcript` 或走 resume 路径，拿回来的 payload 和写入时的原始字典相等。
   - `test_blob_spill_threshold_env_override`：设 `MODULAR_BLOB_SPILL_BYTES=64`，写一个 200 字节 payload 会触发 spill。
2. **跑测试确认红** —— 至少 `read_through` 和 `env_override` 应失败。
3. **实现 D-1 + D-2**（`_prepare_transcript_event` 读 env 取阈值，默认 65536）。
4. **实现 D-3**（新增 `_rehydrate_event` / 在 `load_transcript` 里展开 `blob_ref`，或在 `_prepare_transcript_event` 的对称读取路径里做 —— 实现时再决定最小侵入点）。
5. **跑测试确认绿 + 全量 `pytest tests/test_writing_runtime_persistence.py` 不回归**。
6. **实现 D-5**（migration 脚本）+ 一条 smoke test（跑一次不报错、第二次幂等）。
7. **更新 `OPEN_THREADS.md` A7 / §S-1 状态**，标记 D 收口。

### 10.4 未来升级到 B 级重构的触发条件（记账给以后）

只要满足任意一条就重开表重命名 / blob 路径重排：

- S-2 E2E 测试或前端实际场景被现有 schema 卡住（查询语义不自然、跨表 join 写不出来）；
- `branch / audit / export` 类新需求必须按 turn/tool_call 粒度做；
- 运维上出现 blob 目录扁平化导致的文件系统压力（单目录 > N 万文件）。

以上任一条触发时，把本节改成正式 S-1b 子计划再执行。

### 10.5 验收 gate

- `pytest tests/test_writing_runtime_blob_spill.py` 全绿（新增 3 case）。
- `pytest tests/test_writing_runtime_persistence.py` 无回归。
- `python scripts/migrate_modular_sessions.py --dry-run` 0 退出。
- `ruff` / mypy（若 CI 跑）无新警告。

---

**D-plan appended**: 2026-04-25 (Claude, after Morpheus recon)
**Status**: ✅ Executed 2026-04-25. D-1 (64 KB threshold) / D-2 (`MODULAR_BLOB_SPILL_BYTES`) / D-3 (`_rehydrate_payload` + `load_transcript` read-through + idempotent `_prepare_transcript_event`) / D-4 (`tests/test_writing_runtime_blob_spill.py` 3/3 green) / D-5 (`scripts/migrate_modular_sessions.py --dry-run`, idempotency smoke-tested) all landed. `tests/test_writing_runtime_persistence.py` 4/4 no regression. §10.4 升级触发条件仍记账。
