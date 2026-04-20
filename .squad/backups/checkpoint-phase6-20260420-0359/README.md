# Team Memory（本地持久记忆）

目标：把跨会话会丢失的上下文沉淀到仓库本地，让 team 成员随用随看。

## 读写原则

- 只记录可验证信息（文件路径、命令结果、测试结果、错误信息）。
- 不记录密钥、口令、token、隐私数据。
- 优先短句：结论先行，证据随后。
- 任何“规则级”结论要同步到 `.squad/decisions.md`。

## 文件分工

- `TEAM_MEMORY.md`：高价值长期记忆（稳定事实 / 关键约束 / 常见坑）
- `DECISION_TRAIL.md`：按时间记录关键决策与理由
- `OPEN_THREADS.md`：未决问题与下一步动作
- `SESSION_SNAPSHOT.md`：当前阶段可续接快照（简版）

## 推荐写入模板

```text
[scope] FACT: ... | EVIDENCE: file/path or command output
[scope] DECISION: ... | WHY: ... | EVIDENCE: ...
[scope] OPEN: ... | BLOCKER: ...
[scope] NEXT: ... | OWNER: ...
```

## 团队工作流（每次任务）

1. 开始前：先看 `SESSION_SNAPSHOT.md` + `OPEN_THREADS.md`
2. 实施中：有关键结论立即写 `DECISION_TRAIL.md`
3. 结束前：更新 `SESSION_SNAPSHOT.md` 的 Facts/Decisions/Open/Next
4. 若形成长期稳定结论：同步到 `TEAM_MEMORY.md`
