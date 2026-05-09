# LLM-Wiki 集成切片 Runbook

> LMWR-405（关联 LMWR-404~406、LMWR-415）· Wave 12 Wiki status workbench 首刀

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-405 |
| 简短描述 | 为 Wave 12 落地最小可见的 Wiki 前端状态面：OpenAPI 类型刷新、strict client parsing、`WikiStatusCard`、`/wiki` 页面与导航入口。 |
| Wave | Wave 12 |
| 执行者 | Copilot |
| 开始时间 | 2026-05-04T10:12:44Z |

---

## 1. 回档点

> **每个非平凡代码切片开始前必须创建。**

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-wiki-status-frontend"
```

| 字段 | 值 |
| ---- | ---- |
| 回档命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave12-wiki-status-frontend"` |
| 恢复命令 | `git restore --source=HEAD --worktree frontend/openapi/modular-pipeline-openapi.json frontend/src/generated/openapi.ts frontend/src/App.tsx frontend/src/layouts/MainLayout.tsx docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md docs/plans/active/2026-05-03-llmwiki-execution-decisions.md ; Remove-Item frontend/src/types/wiki.ts, frontend/src/services/wikiApi.ts, frontend/src/services/wikiApi.test.ts, frontend/src/components/wiki/WikiStatusCard.tsx, frontend/src/pages/WikiWorkbench.tsx, docs/plans/runbooks/llmwiki-slice-LMWR-405-wave12-status-workbench.md -ErrorAction SilentlyContinue` |
| 快照文件/stash ref | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-181244-lmwr-wave12-wiki-status-frontend` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 | 关键借鉴点 |
| ---------- | ------ | ----------- |
| 本项目知识库页面 | `frontend/src/pages/KnowledgeBase.tsx` | 复用现有 glass-card、统计卡、工作台式信息密度，而不是另做营销型展示页。 |
| 本项目 service 写法 | `frontend/src/services/intelligentChatApi.ts` | 维持 `getApiBaseUrl()` + typed response 的前端数据访问模式。 |
| 本项目 OpenAPI 类型别名 | `frontend/src/types/resources.ts` | 先刷新 `generated/openapi.ts`，再用独立 `types/wiki.ts` 封装 wiki 相关 alias / normalized model。 |
| 本项目 service 测试模式 | `frontend/src/services/skillApi.test.ts` | 用 focused Vitest 覆盖 unknown payload 防守与错误边界，而不是只靠页面人工点测。 |

---

## 3. 实现记录

### 新增文件

| 文件 | 目的 |
| ---- | ---- |
| `frontend/src/types/wiki.ts` | 为 wiki status surface 提供 generated schema alias 与归一化 `WikiStatusModel`。 |
| `frontend/src/services/wikiApi.ts` | 提供 `/api/wiki/status` strict parser 与请求封装。 |
| `frontend/src/services/wikiApi.test.ts` | 锁定 wiki status payload parsing 与 malformed payload 防守。 |
| `frontend/src/components/wiki/WikiStatusCard.tsx` | 展示 `enabled/stale/page_count`、存在性指标、canonical paths 与 warnings。 |
| `frontend/src/pages/WikiWorkbench.tsx` | 新建 `/wiki` 页面，提供 Wave 12 最小工作台骨架。 |

### 修改文件

| 文件 | 改动摘要 |
| ---- | -------- |
| `frontend/openapi/modular-pipeline-openapi.json` | 基于最新后端 schema 刷新，纳入 `/api/wiki/*`。 |
| `frontend/src/generated/openapi.ts` | 重新生成 TypeScript OpenAPI 类型，补齐 `WikiStatusResponse` / `WikiCompileRequest` / `WikiQueryRequest`。 |
| `frontend/src/App.tsx` | 注册懒加载的 `WikiWorkbench` 路由 `/wiki`。 |
| `frontend/src/layouts/MainLayout.tsx` | 增加 Wiki 导航入口与页面标题。 |
| `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md` | 回填 Wave 12 status workbench 首刀结果。 |
| `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md` | 同步 Wave 12 从暂停切到进行中的状态与下一步。 |

---

## 4. 验证

```powershell
Set-Location frontend
npm run generate:openapi
npx vitest run src/services/wikiApi.test.ts
npm run build
```

### 浏览器目测

- 打开 `http://127.0.0.1:4174/wiki`
- 确认左侧出现 `Wiki` 导航
- 确认页面渲染 `Wiki 工作台状态面`
- 在后端未启动时，页面显示友好的中文错误：`Wiki 状态接口暂不可用（500）...`，而不是白屏

| 检查项 | 结果 |
| ------ | ---- |
| OpenAPI 生成 | PASS |
| focused Vitest | PASS（`2 passed`） |
| frontend build | PASS |
| 浏览器路由/渲染 smoke | PASS（`/wiki` 页面与导航可见；后端离线时显示中文诊断） |

---

## 5. 证据包

### Facts

- `frontend/src/generated/openapi.ts` 已刷新到包含 `/api/wiki/status` 与 `WikiStatusResponse` 等 schema，前端不再对 wiki contract 盲打。
- 前端新增 `WikiStatusModel`，把 generated schema 的可选字段归一化成状态面可直接消费的必填模型。
- `/wiki` 已成为独立工作台入口，最小面板信息架构明确分成 Status / Pages / Review / Graph / Doctor。
- 当后端不可达时，Wiki 页面不会白屏，而会显示友好的中文错误提示，保留工作台骨架与下一步面板占位。

### Decision

- Wave 12 第一刀只做 status workbench，不同时引入 compile dry-run、page preview、review mutate 等高交互面，控制 blast radius。
- wiki 前端 client 采用“generated OpenAPI alias + runtime strict parser”双层结构：既跟随后端 contract，又避免 unknown payload 直接污染 UI。
- 先把 `/wiki` 独立成侧边导航入口，而不是塞进 `KnowledgeBase`；因为它代表的是 wiki-aware 工作台，不是文档上传/切片管理的附属抽屉。

### Evidence

- 回档点：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-181244-lmwr-wave12-wiki-status-frontend`
- OpenAPI 刷新产物：`frontend/openapi/modular-pipeline-openapi.json`、`frontend/src/generated/openapi.ts`
- 新增前端代码：`frontend/src/types/wiki.ts`、`frontend/src/services/wikiApi.ts`、`frontend/src/components/wiki/WikiStatusCard.tsx`、`frontend/src/pages/WikiWorkbench.tsx`
- focused test：`frontend/src/services/wikiApi.test.ts`
- 浏览器验证：`/wiki` 页面可见 `Wiki` 导航、`Wiki 工作台状态面`、以及后端离线时的中文错误诊断

### Rollback

- 若只回滚本切片，优先执行上面的 touched-file restore，并删除新增的 wiki 前端文件与 runbook。
- 若需要完整恢复到切片开始前，以 checkpoint 目录中的 `metadata.json`、`worktree.diff`、`staged.diff` 为准执行人工恢复。

### Open

- `LMWR-407` / `LMWR-408` / `LMWR-410` / `LMWR-411` 仍未落地：compile dry-run、page list/preview、review queue、doctor report 目前仍是占位态。
- 当前浏览器 smoke 证明了“前端容错可见”，但未证明“后端联通后数据渲染正确”；后续需在本地启后端后补一次联通 smoke。

### Next

- 继续 Wave 12：优先补 `WikiPageList` 与 `DoctorReportPanel` 的只读工作台面，把当前占位区变成可用视图。

---

## 执行硬规则（copy from plan）

- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码。
- 产品代码优先放入 `literature_assistant/core/` 与 `frontend/src/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链，不默认启用 rerank，不改变 corpus/goldset/qrels。
- 对外部资料源 Zotero/EndNote/Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference。
