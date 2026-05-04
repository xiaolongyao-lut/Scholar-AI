# LLM-Wiki 集成切片 Runbook

> LMWR-407 / LMWR-409（关联 LMWR-415）· Wave 12 compile dry-run + page preview 最小闭环

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-407 / LMWR-409 |
| 简短描述 | 为 `/wiki` 工作台补齐 `WikiCompileDryRunPanel` 与 `WikiPagePreviewPanel`，把 compile/list/read 接成最小只读闭环。 |
| Wave | Wave 12 |
| 执行者 | Copilot（UI 蓝图参考 Gemini 3.1 Pro 子代理） |
| 开始时间 | 2026-05-04T10:56:36Z |

---

## 1. 回档点

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-compile-preview-ui"
```

| 字段 | 值 |
| ---- | ---- |
| 回档命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-compile-preview-ui"` |
| 恢复命令 | `git restore --source=HEAD --worktree frontend/src/types/wiki.ts frontend/src/services/wikiApi.ts frontend/src/services/wikiApi.test.ts frontend/src/components/wiki/WikiPageListPanel.tsx frontend/src/pages/WikiWorkbench.tsx ; Remove-Item frontend/src/components/wiki/WikiCompileDryRunPanel.tsx, frontend/src/components/wiki/WikiPagePreviewPanel.tsx, docs/plans/runbooks/llmwiki-slice-LMWR-407-wave12-compile-preview.md -ErrorAction SilentlyContinue` |
| 快照文件/stash ref | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-185636-lmwr-wave12-compile-preview-ui` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 | 关键借鉴点 |
| ---------- | ------ | ----------- |
| Gemini 3.1 Pro UI 子代理蓝图 | 本会话子代理结果 | `Pages + Preview` 做主从联动；`Compile Dry-Run` 放入系统诊断区；保留 glass-card + read-only first 语义。 |
| wiki router contract | `literature_assistant/core/routers/wiki_router.py` | `/api/wiki/pages/{page_path}` 返回 `enabled/path/frontmatter/body`；`/api/wiki/compile` 仅允许 dry-run。 |
| 现有前端工作台风格 | `frontend/src/components/wiki/*.tsx` | 延续 `glass-card`、中文错误提示、本地筛选与低爆炸半径的增量接入。 |
| generated OpenAPI schema | `frontend/src/generated/openapi.ts` | `WikiPageReadResponse` 与 `WikiCompileResponse` 都是可直接对齐的 named schema。 |

---

## 3. 实现记录

### 新增文件

| 文件 | 目的 |
| ---- | ---- |
| `frontend/src/components/wiki/WikiPagePreviewPanel.tsx` | 展示当前选中页面的 path / frontmatter / body 预览，保留空态、loading、错误态。 |
| `frontend/src/components/wiki/WikiCompileDryRunPanel.tsx` | 以 safe-mode console 形式展示 dry-run scope、warnings 与 planned paths。 |

### 修改文件

| 文件 | 改动摘要 |
| ---- | -------- |
| `frontend/src/types/wiki.ts` | 新增 `WikiPageDetailModel`、`WikiCompileDryRunModel`、`WikiCompileDryRunInputModel`。 |
| `frontend/src/services/wikiApi.ts` | 新增 `parseWikiPageDetail`、`parseWikiCompileDryRun`、`getWikiPageDetail`、`runWikiCompileDryRun`。 |
| `frontend/src/services/wikiApi.test.ts` | focused tests 从 6 项扩展到 8 项，锁定 page detail 与 compile dry-run parser contract。 |
| `frontend/src/components/wiki/WikiPageListPanel.tsx` | 页面列表支持选中态，并可把 preview 请求导向右侧面板。 |
| `frontend/src/pages/WikiWorkbench.tsx` | 将 `/wiki` 升级为 `Pages + Preview`、`Doctor + Compile`、`Review + Graph` 三排布局。 |

---

## 4. 验证

```powershell
Set-Location frontend
npx vitest run src/services/wikiApi.test.ts
npm run build
```

### 浏览器目测

- 打开 `http://127.0.0.1:4173/wiki`
- 确认 `/wiki` 页面现在能看到：
  - `Wiki 页面预览`
  - `Wiki Compile Dry-Run`
- 在后端接口返回 500/不可用时，页面仍保持结构可见，并输出中文错误提示，而不是白屏。

| 检查项 | 结果 |
| ------ | ---- |
| focused Vitest | PASS（`8 passed`） |
| frontend build | PASS |
| 浏览器 smoke | PASS（新两块 panel 可见；后端异常时仍显示中文诊断） |

---

## 5. 证据包

### Facts

- `/wiki` 现在已从五块只读工作台继续扩展到七块：新增 `Page Preview` 与 `Compile Dry-Run`。
- `frontend/src/services/wikiApi.ts` 已覆盖 `/api/wiki/pages/{page_path}` 与 `/api/wiki/compile` 的前端 parser / loader；对应 parser 测试从 `6 passed` 提升到 `8 passed`。
- 页面列表已具备选中态，可以把某个 page 的 preview 请求稳定导向右侧 preview panel。
- 浏览器 smoke 证明：即使后端接口报 500，新面板仍然可见，并维持中文错误/空态提示，不会把 `/wiki` 整页打成白屏。

### Decisions

- `WikiPagePreviewPanel` 暂不引入 markdown 富渲染依赖，先用只读 `frontmatter + body` 纯文本 preview 收口 contract，避免 blast radius 扩大。
- `WikiCompileDryRunPanel` 仅对接 dry-run contract，不伪造真实 compile 结果；当后端仍处 skeleton 阶段时，用 warnings 与空 planned paths 明确表达边界。
- `WikiPageListPanel` 采用“点击卡片即选中”的主从结构，而不是单独再加一套复杂 drawer / route 切换。原因是当前最小目标是把 list/read 连成工作台闭环。

### Evidence

- 回档点：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-185636-lmwr-wave12-compile-preview-ui`
- 新增组件：`frontend/src/components/wiki/WikiPagePreviewPanel.tsx`、`frontend/src/components/wiki/WikiCompileDryRunPanel.tsx`
- contract / parser：`frontend/src/services/wikiApi.ts`
- focused tests：`frontend/src/services/wikiApi.test.ts`（`8 passed`）
- 浏览器快照：`http://127.0.0.1:4173/wiki` 已显示 `Wiki 页面预览` 与 `Wiki Compile Dry-Run` 两块新面板

### Rollback

- 若只回滚本切片，优先执行上面的 touched-file restore，并删除新增的两个 panel 组件与本 runbook。
- 若需要完整恢复到切片开始前，以 checkpoint 目录中的 `metadata.json`、`worktree.diff`、`staged.diff` 为准执行人工恢复。

### Open

- `LMWR-412`：Citation warnings 视图仍未前端化。
- `LMWR-414`：existing Evidence UI 与 wiki citation 的联动仍未接入。
- 目前浏览器 smoke 仍是“后端错误容错”视角；后续应在后端服务正常启动时补一次真实 page preview / compile dry-run 联通验证。

### Next

- 继续 Wave 12：优先补 `CitationWarnings view`，然后把 existing Evidence UI 接到 wiki citation / page preview 上，完成本轮工作台最小产品面。

---

## 执行硬规则（copy from plan）

- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码。
- 产品代码优先放入 `literature_assistant/core/` 与 `frontend/src/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链，不默认启用 rerank，不改变 corpus/goldset/qrels。
- 对外部资料源 Zotero/EndNote/Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference。
