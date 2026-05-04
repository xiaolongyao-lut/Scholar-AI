# LLM-Wiki 停止 / 交接记录

> 记录时间：2026-05-04T19:40+08:00
> 停止原因：用户明确要求停止并记录（`先停止，然后记录吧`）

---

## 1. 当前结论

- Wave 12 前端工作台本轮已收口，可视为当前阶段完成。
- Wave 13 只做了 connector 最小骨架的起步，实现未收口，当前暂停在 `tests/wiki/test_connectors.py` 的缩进修复前。
- 本文档是本次停止的正式 docs 记录；`.squad/orchestration-log/` 中的同名记录仅保留为本地审计镜像，不作为仓库内主入口。

---

## 2. Facts

### Wave 12 已完成事实

- `/wiki` 已具备七块只读面板：`Status / Pages / Preview / Doctor / Compile Dry-Run / Review / Graph`。
- citation warnings 已落地：
  - `frontend/src/services/wikiApi.ts`
  - `frontend/src/components/wiki/WikiPagePreviewPanel.tsx`
- existing Evidence UI -> Wiki preview deep link 已落地：
  - `frontend/src/lib/evidenceReferences.ts`
  - `frontend/src/lib/evidenceReferences.test.ts`
  - `frontend/src/components/chat/MessageBubble.tsx`
  - `frontend/src/components/writing/WritingCanvas.tsx`
  - `frontend/src/pages/WikiWorkbench.tsx`
- Review / Doctor UI 测试已补齐：
  - `frontend/src/components/wiki/ReviewQueuePanel.test.tsx`
  - `frontend/src/components/wiki/DoctorReportPanel.test.tsx`

### Wave 12 已验证证据

- focused Wave 12 前端测试：
  - `npm --prefix "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend" exec vitest -- run src/components/wiki/ReviewQueuePanel.test.tsx src/components/wiki/DoctorReportPanel.test.tsx src/lib/evidenceReferences.test.ts src/services/wikiApi.test.ts`
  - 结果：`4 files / 19 tests passed`
- 前端全量 Vitest：
  - `npm --prefix "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend" run test`
  - 结果：`11 files / 54 tests passed`
- 前端构建：
  - `npm --prefix "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend" run build`
  - 结果：PASS
- 浏览器 smoke：
  - `/wiki?page=sources%2Fpaper-a.md` 可渲染；后端离线时显示中文错误诊断，不白屏。

### Wave 13 当前部分进展

- 已新增 connector 包：
  - `literature_assistant/core/wiki/connectors/__init__.py`
  - `literature_assistant/core/wiki/connectors/base.py`
  - `literature_assistant/core/wiki/connectors/markdown.py`
  - `literature_assistant/core/wiki/connectors/pdf_folder.py`
- 已新增 focused 测试：
  - `tests/wiki/test_connectors.py`
- 在后续缩进误改之前，connector focused 测试曾通过一次：
  - `c:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/.venv-1/Scripts/python.exe -m pytest "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py" -q`
  - 结果：`5 passed in 0.10s`
- 同一阶段 compileall 也曾通过一次：
  - `c:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/.venv-1/Scripts/python.exe -m compileall -q "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\connectors" "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py"`

---

## 3. Decisions

- **停止决策**：按用户要求立即停止，不继续推进 Wave 13 实现。
- **Evidence deep-link 决策**：只接受 `page_store_path` / `wiki_page_path` / `page_path` 生成 `/wiki?page=...`，不从 `source_id` / `material_id` 猜 slug。
- **Connector 边界决策**：Wave 13 维持只读优先。
  - Markdown connector：只读扫描/读取 note。
  - PDF connector：只列 metadata，不做文本抽取。
  - external path：必须显式 allow roots。

---

## 4. Open / 风险

- `tests/wiki/test_connectors.py` 当前有一个已知缩进问题：
  - 位置：`test_pdf_folder_connector_lists_metadata_without_content_extraction`
  - 行：`connector.read_source(sources[0].source_id)`
  - 症状：缩进被改坏，编辑器曾报 `expected 8`。
- `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md` 顶部存在历史 Markdown lint 债务（`MD022` / `MD032`），本轮没有大面积重排。
- `literature_assistant.core.wiki.connectors` 可能短时间内出现语言服务缓存导致的导入误报；需要以下一轮实际 pytest/compileall 结果为准。

---

## 5. Next

1. 先修 `tests/wiki/test_connectors.py` 的 `with pytest.raises(...)` 块缩进。
2. 复跑：
   - `c:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/.venv-1/Scripts/python.exe -m pytest "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py" -q`
   - `c:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/.venv-1/Scripts/python.exe -m compileall -q "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\connectors" "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_connectors.py"`
3. 若都转绿，再补 Wave 13 connector runbook，并回填 active plan 对 `LMWR-419` ~ `LMWR-428` 的阶段状态。

---

## 6. 相关文档入口

- Wave 12 citation warnings：`docs/plans/runbooks/llmwiki-slice-LMWR-412-wave12-citation-warnings.md`
- Wave 12 evidence links：`docs/plans/runbooks/llmwiki-slice-LMWR-414-wave12-evidence-wiki-links.md`
- Wave 12 UI tests / gate：`docs/plans/runbooks/llmwiki-slice-LMWR-416-418-wave12-ui-tests-gate.md`
- Active plan：`docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`
- Execution decisions：`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

---

## 7. 当前 git 快照（停止时）

```text
 M docs/plans/active/2026-05-03-llmwiki-execution-decisions.md
 M docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md
 M frontend/src/components/chat/MessageBubble.tsx
 M frontend/src/components/writing/WritingCanvas.tsx
 M frontend/src/lib/evidenceReferences.test.ts
 M frontend/src/lib/evidenceReferences.ts
?? docs/plans/runbooks/llmwiki-slice-LMWR-397-wave11-cli-openapi.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-405-wave12-status-workbench.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-407-wave12-compile-preview.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-408-wave12-readonly-panels.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-412-wave12-citation-warnings.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-414-wave12-evidence-wiki-links.md
?? docs/plans/runbooks/llmwiki-slice-LMWR-416-418-wave12-ui-tests-gate.md
?? docs/plans/runbooks/longrun-local-supervisor.md
?? frontend/src/components/wiki/
?? frontend/src/pages/WikiWorkbench.tsx
?? literature_assistant/core/wiki/connectors/
?? tests/wiki/test_connectors.py
```
