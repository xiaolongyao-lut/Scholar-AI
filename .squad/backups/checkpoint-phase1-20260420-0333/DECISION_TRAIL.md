# DECISION_TRAIL

> 记录格式：
>
> - Date:
> - Scope:
> - Decision:
> - Why:
> - Evidence:
> - Impact:

## 2026-04-20

- Date: 2026-04-20
- Scope: team-memory
- Decision: 建立本地持久记忆目录 `.squad/memory/`，作为 team 默认可读知识层。
- Why: 避免跨会话信息丢失，支持夜班/多成员持续接力。
- Evidence: `.squad/memory/README.md`, `.squad/identity/start-here.md`（接入后）
- Impact: 所有成员可按统一模板沉淀事实、决策、未决和下一步。

### 2026-04-20 Morpheus 自主更新 — 启动自检关闭漂移项

- **操作**：SESSION_SNAPSHOT 中两条 Open 项（memory 接入 start-here / memory 责任写入 SKILL.md）标记为已完成，迁入 Facts；Next 更新为等待 Phase 1。
- **触发原因**：启动自检发现 `start-here.md` 第14–16项已含 memory 读取顺序，`SKILL.md` 已含 "Team memory persistence" 段落，两项均有文件证据支撑。
- **结果**：SESSION_SNAPSHOT Open 区清空，状态对齐现实。OPEN_THREADS 无需变更（已无活跃项）。requirement-pool 无积压。
- **是否通知 Owner**：否（在 Owner 检查时可见）
