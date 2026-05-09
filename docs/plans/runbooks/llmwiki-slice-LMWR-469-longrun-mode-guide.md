# LLM-Wiki 集成切片 Runbook

> LMWR-469 · longrun mode guide and supervision boundary

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-469 |
| 简短描述 | 补充 longrun 模式使用指南，明确启动条件、停止条件、监督策略、回档和成熟方案搜索要求。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:55:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-214424-llmwiki-longrun-resume-align-next` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-214424-llmwiki-longrun-resume-align-next" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| OpenAI Codex `AGENTS.md` | `https://developers.openai.com/codex/guides/agents-md` | Codex 会读取全局和项目级指令；longrun 必须先读仓库指导和 active plan。 |
| OpenAI Codex non-interactive mode | `https://developers.openai.com/codex/noninteractive` | 本地 scheduled worker 对齐 `codex exec` 自动化模式：显式权限、窄任务、执行后验证。 |
| Microsoft ScheduledTasks | `https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasktrigger` | 本地监督使用 time-based repeating trigger；每个 tick 启动一个 worker。 |
| Git worktree | `https://git-scm.com/docs/git-worktree` | dirty worktree 下避免互相覆盖；高风险并行工作应隔离或停下询问。 |
| 本地执行纪律 | `AI_WORKSPACE_GUIDE.md`、`AGENTS.md` | 先回档、再调研、保留未关联变更、计划落在 `docs/plans/`。 |

---

## 3. 核心落点

| 文件 | 覆盖 |
| ---- | ---- |
| `docs/plans/runbooks/longrun-local-supervisor.md` | 增加 LMWR-469 scope、成熟方案、启动 envelope、任务选择、命令模板、验证梯度、handoff 记录。 |
| `tools/longrun/longrun-prompt.md` | 强化 non-interactive worker 的读档、回档、成熟方案搜索、命令给出规则和停止条件。 |
| `docs/plans/active/llmwiki-autonomy-authorization.md` | 记录 2026-05-04 用户授权：独立窗口终态、评测基线备份后可演进、安全审计轻量化、AI 联网边界、删除修改先备份。 |
| `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md` | 标记 LMWR-469 完成，补充执行结果和证据。 |
| `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md` | 更新 D15 当前状态、边界、停止条件和证据路径。 |

---

## 4. Longrun SOP

### 启动条件

- 用户明确说“长跑”“继续”“自决策”“检查 doc 后继续”等。
- active plan 仍有未完成任务。
- 下一个任务在 LLM-Wiki/RAG 范围内，且能用 focused verification 证明。
- 已创建 checkpoint，已读取 `git status --short` 和 active docs。

### 停止条件

- 下一步需要修改默认 RAG/TOLF 主链。
- 下一步需要外部知识库写回、auto-finalize、`.env`/secret。
- 下一步需要无备份修改 qrels/goldset/canary30/eval query。
- 下一步需要生产访问、账号、付费服务或不可逆操作。
- 下一步需要删除或修改无法备份、无法验证恢复路径的目标。
- 工作树冲突风险过高，无法确认改动归属。
- 已完成一个可验证切片，剩余任务需要用户产品判断。

### 每个任务必须做

1. 创建 checkpoint。
2. 读取 active docs 和目标文件。
3. 搜索成熟方案或读取本地参考项目。
4. 狭窄实现。
5. 运行 focused verification。
6. 更新 runbook / active plan / decisions。
7. 只在用户明确要求时恢复 checkpoint。

---

## 5. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m compileall -q docs\plans tools\longrun
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_compiler.py tests\wiki\test_wiki_router.py tests\wiki\test_wave15_end_to_end.py -q
cd frontend
npm run test -- --run src/services/wikiApi.test.ts
npm run build
```

| 检查项 | 结果 |
| ------ | ---- |
| docs/tools compileall | PASS |
| Wiki focused pytest | PASS（29 passed） |
| frontend wikiApi Vitest | 本轮改文档前补跑 PASS（11 passed） |
| frontend build | 本轮改文档前补跑 PASS |

---

## 6. Open / 后续

- LMWR-466 前端 E2E 仍未完成，但已获用户授权。
- LMWR-466 已获用户授权：复用现有 Playwright，浏览器只做独立窗口终态前的最小 E2E。
- LMWR-467 已完成 default-off/no-write design；任何直接外部写回实现都必须先做 dry-run diff、target-level backup 和 operation journal。
- LMWR-470 已获用户授权：qrels/goldset/canary30 可在备份、版本化和对照指标充分后自决策演进。
- LMWR-472/473 已获用户授权：安全审计按本地轻量门禁执行，可观测性默认本地、无网络导出、脱敏。
