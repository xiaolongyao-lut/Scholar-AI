# LLM-Wiki 集成切片 Runbook

> LMWR-414（关联 LMWR-415）· Wave 12 existing Evidence UI → Wiki preview links

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-414 |
| 简短描述 | 将现有 Chat / Writing Evidence UI 中携带显式 wiki page path 的 `evidence_refs` 接到 `/wiki?page=...` 只读 preview 深链。 |
| Wave | Wave 12 |
| 执行者 | Copilot |
| 完成时间 | 2026-05-04T19:35:51+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| 手动快照 | `.rollback_snapshots/manual-lmwr414-20260504_193254` |

快照覆盖：

- `frontend/src/lib/evidenceReferences.ts`
- `frontend/src/lib/evidenceReferences.test.ts`
- `frontend/src/pages/WikiWorkbench.tsx`
- `frontend/src/components/writing/WritingCanvas.tsx`
- `frontend/src/components/chat/MessageBubble.tsx`

---

## 2. 设计约束

- 只从显式 wiki page path 字段生成 deep link：`page_store_path`、`wiki_page_path`、`page_path`。
- 不从 `source_id` / `material_id` 猜测页面路径，因为 wiki compiler 使用 title slug，硬猜会把用户送到错误页面。
- URL 只进入 `/wiki?page=...` read-only preview；不写 wiki page，不触发 compile，不改变 RAG 默认主链。
- path guard 拒绝空路径、绝对路径、Windows drive path、scheme path、`.` / `..` 路径片段。

---

## 3. 实现记录

| 文件 | 改动摘要 |
| ---- | -------- |
| `frontend/src/lib/evidenceReferences.ts` | 新增 `getEvidenceReferenceWikiPagePath` 与 `getEvidenceReferenceWikiUrl`，集中处理 evidence_refs → `/wiki?page=...`。 |
| `frontend/src/lib/evidenceReferences.test.ts` | 新增 TDD 用例：明确 page path 可生成 deep link；source-only 和危险路径不生成。 |
| `frontend/src/pages/WikiWorkbench.tsx` | 支持 `?page=` deep link 自动加载 page preview；页面列表为空/后端离线时不清空 deep-linked selection。 |
| `frontend/src/components/writing/WritingCanvas.tsx` | Writing Evidence card 在存在 wiki deep link 时显示 `Wiki` 入口。 |
| `frontend/src/components/chat/MessageBubble.tsx` | Chat Evidence References 在存在 wiki deep link 时显示 `Wiki preview` 入口。 |

---

## 4. 验证

```powershell
npm --prefix "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend" exec vitest -- run src/lib/evidenceReferences.test.ts src/services/wikiApi.test.ts
npm --prefix "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend" run build
```

| 检查项 | 结果 |
| ------ | ---- |
| TDD 红灯 | PASS（新增 helper 测试先失败：`getEvidenceReferenceWikiPagePath is not a function`，`1 failed / 5 passed`） |
| focused tests | PASS（`src/lib/evidenceReferences.test.ts` + `src/services/wikiApi.test.ts` → `17 passed`） |
| frontend build | PASS（`tsc && vite build`；`WikiWorkbench` chunk 约 51.25 kB / gzip 11.97 kB） |
| browser smoke | PASS（`/wiki?page=sources%2Fpaper-a.md` 可渲染；后端离线时 page preview 显示中文 500 诊断，不白屏） |

---

## 5. 证据包

### Facts

- Evidence helper 现在能把明确携带 `page_store_path` / `wiki_page_path` / `page_path` 的 refs 转成 `/wiki?page=...`。
- Writing Canvas 与 Chat Bubble 的 existing Evidence UI 均已接入只读 Wiki 入口。
- WikiWorkbench 已支持 query-param deep link，并在 pages list 为空或后端离线时保留 deep-linked preview 目标。

### Decisions

- 不根据 `source_id` / `material_id` 猜路径，避免 false-positive 跳转。
- 本刀只实现 deep-link 入口；citation anchor / chunk highlight 暂不做，等待后端提供稳定锚点字段。

### Open

- 后续可在 `evidence_refs` 增加稳定 `page_store_path` / anchor 字段后，再做 chunk 高亮或 citation anchor 自动滚动。
- Wave 12 仍待补 `ReviewQueuePanel` / `DoctorReportPanel` 组件级测试与最后 frontend gate 收口。

### Next

- 继续 LMWR-416 / LMWR-417：给 ReviewQueuePanel 与 DoctorReportPanel 补 focused UI tests。
