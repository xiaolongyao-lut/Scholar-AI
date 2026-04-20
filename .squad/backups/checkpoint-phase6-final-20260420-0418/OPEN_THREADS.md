# OPEN_THREADS

## Active

- [phase4-metadata-constraint] ⚠️ NOTED 2026-04-20
  - Description: Zotero jasminum-outline.json 仅含 PDF 大纲结构（level/title/page），不含结构化元数据（abstract/keywords/authors/year）。output/ 中的 01_full_extract.json 前 5 行也未显示这些字段（可能在更深层）。如果未来需要结构化文献元数据，需额外从 PDF 正文解析或 Zotero API 获取。
  - Status: 非阻塞。当前三模块管道（prefilter + traversal + extraction）均不依赖此元数据。仅在对话/排序层可能需要。
  - Owner: Morpheus（架构判断）

- [intelligent-chat-hard-stop] 🛑 HARD-STOP 2026-04-20
  - Description: phase-plan "Must Deliver" 最后一项——"Intelligent chat grounded in the extracted literature base"——需要 LLM 集成（API 调用库、模型选择、prompt 模板、token 管理）。这几乎确定引入新外部依赖（如 openai、langchain、litellm 等），属于 hard-stop 类决策。
  - Status: 阻塞。需 Morpheus + Owner 联合决策：选择哪个 LLM 框架、API 密钥管理策略、上下文窗口预算、对话记忆方案。
  - Owner: Morpheus + Owner（WAITING FOR USER）
  - Evidence: `.squad/identity/phase-plan.md` Must Deliver 第 5 项; `.squad/decisions.md` "Refactor/schema/dependency are hard-stop requirement classes"

## Closed

- [team-memory-adoption] ✅ closed 2026-04-20
  - Resolution: `start-here.md` 已接入读取顺序（第14-16项），`project-conventions/SKILL.md` 已写入更新责任。
  - Closed by: Squad 巡检确认
- [phase1-no-data-correction] ✅ closed 2026-04-20
  - Resolution: 早期 Phase 1 结论"仓库无预置文献数据"已被刷新版 `literature-data-map.md` 修正。真实数据源已确认：output/（894 JSON）和 Zotero storage（815 文件）。
  - Closed by: Morpheus Phase 1 刷新关闭
