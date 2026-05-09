# LLM-Wiki 集成切片 Runbook

> LMWR-408（关联 LMWR-408、LMWR-410、LMWR-411、LMWR-413）· Wave 12 四块只读工作台面板

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-408 |
| 简短描述 | 为 Wave 12 扩展 `/wiki` 前端工作台：新增 Pages / Doctor / Review / Graph 四块只读面板、对应的 runtime parser，以及更完整的浏览器状态面。 |
| Wave | Wave 12 |
| 执行者 | Copilot |
| 开始时间 | 2026-05-04T10:28:18Z |

---

## 1. 回档点

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-review-graph-readonly"
```

| 字段 | 值 |
| ---- | ---- |
| 回档命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-review-graph-readonly"` |
| 恢复命令 | `git restore --source=HEAD --worktree frontend/src/types/wiki.ts frontend/src/services/wikiApi.ts frontend/src/services/wikiApi.test.ts frontend/src/pages/WikiWorkbench.tsx ; Remove-Item frontend/src/components/wiki/WikiPageListPanel.tsx, frontend/src/components/wiki/DoctorReportPanel.tsx, frontend/src/components/wiki/ReviewQueuePanel.tsx, frontend/src/components/wiki/GraphDebugPanel.tsx, docs/plans/runbooks/llmwiki-slice-LMWR-408-wave12-readonly-panels.md -ErrorAction SilentlyContinue` |
| 快照文件/stash ref | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-182818-lmwr-wave12-review-graph-readonly` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 | 关键借鉴点 |
| ---------- | ------ | ----------- |
| doctor 机器可读 contract | `literature_assistant/core/wiki/doctor.py`、`tests/wiki/test_doctor.py` | 前端只消费 `status / counts / checks / actions` 的稳定结构，不假设更多后端魔法字段。 |
| review queue durable shape | `literature_assistant/core/wiki/review_queue.py`、`tests/wiki/test_review_queue.py` | 只读面优先展示 `kind / status / decision`，不在本刀接 approve/reject mutate。 |
| graph export contract | `literature_assistant/core/wiki/graph.py`、`tests/wiki/test_graph.py` | 先展示 `node_count / edge_count / nodes / edges` 的 debug 视图，再谈图可视化。 |
| 本项目前端 panel 风格 | `frontend/src/pages/KnowledgeBase.tsx` | 延续 glass-card + compact control bar 的工作台式布局。 |

---

## 3. 实现记录

### 新增文件

| 文件 | 目的 |
| ---- | ---- |
| `frontend/src/components/wiki/WikiPageListPanel.tsx` | 只读页面列表 + kind/status 本地筛选。 |
| `frontend/src/components/wiki/DoctorReportPanel.tsx` | 只读 doctor report，显示 counts/checks/actions。 |
| `frontend/src/components/wiki/ReviewQueuePanel.tsx` | 只读治理队列，显示 pending/approved/rejected item。 |
| `frontend/src/components/wiki/GraphDebugPanel.tsx` | 只读 graph debug 视图，显示 node/edge 预览。 |

### 修改文件

| 文件 | 改动摘要 |
| ---- | -------- |
| `frontend/src/types/wiki.ts` | 扩展 review/graph 的 normalized models。 |
| `frontend/src/services/wikiApi.ts` | 新增 `parseWikiReviewList`、`parseWikiGraph` 与对应 `getWikiReview` / `getWikiGraph`。 |
| `frontend/src/services/wikiApi.test.ts` | focused tests 扩展到 status/pages/doctor/review/graph 共 6 项。 |
| `frontend/src/pages/WikiWorkbench.tsx` | 从双 panel 升级为 status/pages/doctor/review/graph 五块观测面。 |

---

## 4. 验证

```powershell
Set-Location frontend
npx vitest run src/services/wikiApi.test.ts
npm run build
```

### 浏览器目测

- 打开 `http://127.0.0.1:4174/wiki`
- 确认 `/wiki` 页面渲染 `Pages` / `Doctor` / `Review` / `Graph` 四块只读 panel
- 在后端未启动时，四块 panel 都显示友好的中文错误诊断，不出现白屏或未捕获崩溃

| 检查项 | 结果 |
| ------ | ---- |
| focused Vitest | PASS（`6 passed`） |
| frontend build | PASS |
| 浏览器 smoke | PASS（四块 panel 可见；后端离线时显示中文诊断） |

---

## 5. 证据包

### Facts

- `/wiki` 现在不再只是 status 页，而是完整的只读工作台：Status / Pages / Doctor / Review / Graph 五块面板齐备。
- `wikiApi.ts` 已覆盖 review/graph 的 parser，前端对 `/api/wiki/*` 的主要只读 contract 不再只依赖 status 一条线。
- review / graph 前端模型采用 normalized model，而不是直接把 generated schema 的宽松对象裸传给 UI。
- 浏览器 smoke 证明了：即使后端离线，四块 panel 也能稳定显示中文错误提示并保持页面结构可见。

### Decision

- Review/Graph 本轮坚持只读；不接 approve/reject mutate，也不接 graph rebuild，避免在没有完整交互设计前把治理操作暴露进 UI。
- Graph 先做 debug view，不做图可视化。原因是当前最需要的是 contract 可读性和节点/边核对，而不是视觉动画。
- Review queue 先用本地筛选，避免为了前端 MVP 过早绑定服务端筛选组合与状态同步复杂度。

### Evidence

- 回档点：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-182818-lmwr-wave12-review-graph-readonly`
- 新增前端面板：`frontend/src/components/wiki/WikiPageListPanel.tsx`、`DoctorReportPanel.tsx`、`ReviewQueuePanel.tsx`、`GraphDebugPanel.tsx`
- parser / tests：`frontend/src/services/wikiApi.ts`、`frontend/src/services/wikiApi.test.ts`
- 浏览器验证：`/wiki` 页面现已显示四块只读 panel 与对应错误诊断

### Rollback

- 若只回滚本切片，优先执行上面的 touched-file restore，并删除新增的四个 panel 组件与本 runbook。
- 若需要完整恢复到切片开始前，以 checkpoint 目录中的 `metadata.json`、`worktree.diff`、`staged.diff` 为准执行人工恢复。

### Open

- `LMWR-407` / `LMWR-409` / `LMWR-412` / `LMWR-414` 仍未落地：compile dry-run panel、page preview、citation warnings、existing evidence UI 仍待继续。
- 当前浏览器 smoke 仍是“后端离线容错”视角；后续需要在本地启后端后补一次真实数据联通 smoke。

### Next

- 继续 Wave 12：优先补 `WikiCompileDryRunPanel` + `WikiPagePreview`，把 status/list/read 三条 contract 真正连成工作台闭环。

---

## 执行硬规则（copy from plan）

- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码。
- 产品代码优先放入 `literature_assistant/core/` 与 `frontend/src/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链，不默认启用 rerank，不改变 corpus/goldset/qrels。
- 对外部资料源 Zotero/EndNote/Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference。
