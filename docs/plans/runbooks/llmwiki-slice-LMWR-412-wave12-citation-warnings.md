# LLM-Wiki 集成切片 Runbook

> LMWR-412（关联 LMWR-414、LMWR-415）· Wave 12 citation warnings view

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-412 |
| 简短描述 | 在 `/wiki` 页面预览中新增文内引用与证据预警卡，并让前端本地识别 `evidence_refs/references`、wikilink、`@cite` 与 quote/Evidence 上下文风险。 |
| Wave | Wave 12 |
| 执行者 | Copilot（UI 实现先由 Gemini 3.1 Pro Preview 子代理提交，再由 Copilot 独立复核与收紧测试） |
| 完成时间 | 2026-05-04T19:28:16+08:00 |

---

## 1. 回档说明

本切片在既有 Wave 12 前端工作台改动上继续小步增量。若只回滚本切片，恢复以下文件即可：

```powershell
git restore --source=HEAD --worktree frontend/src/services/wikiApi.ts frontend/src/services/wikiApi.test.ts frontend/src/components/wiki/WikiPagePreviewPanel.tsx docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md docs/plans/active/2026-05-03-llmwiki-execution-decisions.md
Remove-Item docs/plans/runbooks/llmwiki-slice-LMWR-412-wave12-citation-warnings.md -ErrorAction SilentlyContinue
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 | 关键借鉴点 |
| -------- | ---- | ---------- |
| existing Evidence UI | `frontend/src/lib/evidenceReferences.ts` | 前端现有证据展示以 `chunk_id/material_id/source_id/quote/text` 等字段为稳定跳转基础；wiki warning 不另造证据对象。 |
| wiki evidence adapter | `literature_assistant/core/wiki/evidence_adapter.py` | `evidence_ref_to_markdown` 使用 `quote > compressed_text > text`，并要求可引用文本；前端 warning 对齐这一约束。 |
| active execution plan | `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md` | Wave 12 明确：Evidence UI 已能展示 `evidence_refs`，新增 wiki 功能应从这些引用跳转到 page/citation。 |

---

## 3. 实现记录

### 修改文件

| 文件 | 改动摘要 |
| ---- | -------- |
| `frontend/src/services/wikiApi.ts` | 新增并收紧 `extractCitationWarnings`：区分 wikilink 与单括号引用，识别 `evidence_refs/references`，检查 evidence ref 是否具备 id 与 quote/text 字段。 |
| `frontend/src/services/wikiApi.test.ts` | focused tests 扩展到 11 项；新增红灯用例覆盖 wikilink 不误报、valid evidence_refs 不误报、malformed evidence_refs 预警。 |
| `frontend/src/components/wiki/WikiPagePreviewPanel.tsx` | 页面 preview 中渲染 `文内引用与证据预警` warning card。 |

### 当前 warning 覆盖

- 页面正文为空。
- draft 页面缺少 citation / wikilink / evidence refs。
- final / claim / synthesis / exploration 这类证据型页面缺少 `evidence_refs`。
- 正文含 `@cite(...)`、`[来源]` 等引用标记，但 frontmatter 缺少 `evidence_refs/references`。
- `evidence_refs` 缺少 `chunk_id/source_id/material_id` 或 `quote/text/content`，导致跳转/审计不可用。
- claim 页面缺少 `> 引述` 或 `## Evidence` 证据上下文。

---

## 4. 验证

```powershell
npm --prefix frontend exec vitest -- run src/services/wikiApi.test.ts
npm --prefix frontend run build
npm --prefix frontend run preview -- --host 127.0.0.1
```

| 检查项 | 结果 |
| ------ | ---- |
| 新增测试红灯 | PASS（预期失败：3 failed / 8 passed，证明旧启发式会误报 wikilink、漏识别 evidence_refs） |
| focused Vitest | PASS（最终 `11 passed`） |
| frontend build | PASS（`tsc && vite build`，`WikiWorkbench` chunk 约 50.98 kB / gzip 11.83 kB） |
| 浏览器 smoke | PASS（`http://127.0.0.1:4174/wiki` 可渲染；后端离线时各 panel 显示中文 500 诊断，不白屏） |

---

## 5. 证据包

### Facts

- `WikiPagePreviewPanel` 现在会在正文 preview 上方展示 citation/evidence warning card。
- `extractCitationWarnings` 不再把 `[[wikilink]]` 当作普通 citation reference 误报；有合格 `evidence_refs` 的 claim/final 页面也不误报。
- focused parser/client 测试从 8 项扩展到 11 项，并覆盖 citation warning 的主要边界。

### Decisions

- 本切片只做 read-only warning view，不接 approve/reject、不写 wiki page、不启用 wiki-first retrieval。
- `LMWR-414` 只完成证据跳转 readiness 的前置检查；真正把 existing Evidence UI 链到 wiki citation/page preview 仍是下一刀。

### Evidence

- 代码：`frontend/src/services/wikiApi.ts`、`frontend/src/components/wiki/WikiPagePreviewPanel.tsx`
- 测试：`frontend/src/services/wikiApi.test.ts`
- focused test：`npx vitest run src/services/wikiApi.test.ts` → `11 passed`
- build：`npm run build` → PASS
- browser：Vite preview `http://127.0.0.1:4174/wiki`，页面完整可见，后端离线错误被中文化展示。

### Open

- `LMWR-414` 仍待完成：把 existing Evidence UI 的 `evidence_refs` 项真正链接到 wiki page/citation preview。

### Next

- 继续 Wave 12：做 evidence_refs → wiki page/citation preview 的只读跳转入口，不新增证据对象，不改变默认 RAG 主链。
