# OPEN_THREADS

## Active

- [phase4-metadata-constraint] ⚠️ NOTED 2026-04-20
  - Description: Zotero jasminum-outline.json 仅含 PDF 大纲结构（level/title/page），不含结构化元数据（abstract/keywords/authors/year）。output/ 中的 01_full_extract.json 前 5 行也未显示这些字段（可能在更深层）。如果未来需要结构化文献元数据，需额外从 PDF 正文解析或 Zotero API 获取。
  - Status: 非阻塞。当前三模块管道（prefilter + traversal + extraction）均不依赖此元数据。仅在对话/排序层可能需要。
  - Owner: Morpheus（架构判断）

- [async-ingestion-batch] ⏳ WAITING FOR USER 2026-04-20
  - Description: Batch async ingestion for large literature folders——requirement pool 遗留项。涉及大规模并发加载、内存管理、进度报告等设计决策。
  - Status: 阻塞 (WAITING FOR USER)。需 Owner 确认优先级和实现时序。
  - Owner: Owner（需求确认）
  - Evidence: requirement-pool inventory

## Closed

- [intelligent-chat-hard-stop] ✅ CLOSED 2026-04-20 → Phase 1-5 Shipped
  - Resolution: Intelligent Chat 完整实现链已完成（Phase 1 发现 → Phase 2 实现 → Phase 3 测试 → Phase 4 验证 → Phase 5 前端修复及检查）。前端修复周期经历"Switch 锁定 → Trinity 修复 → Tank 批准"流程，最终 Morpheus 批准全链投产。extraction_pipeline 和 folder_traversal 模块已通过 16/16 单元+集成+边界测试，Oracle 真实数据验证（109 篇论文，4 场景）全部 PASS。frontend/ 日志查询功能和后端查询 API 已对接就绪。
  - Closed by: Morpheus Phase 1-5 APPROVED, Trinity repair cycle + Tank verification APPROVED

- [team-memory-adoption] ✅ closed 2026-04-20
  - Resolution: `start-here.md` 已接入读取顺序（第14-16项），`project-conventions/SKILL.md` 已写入更新责任。
  - Closed by: Squad 巡检确认
- [phase1-no-data-correction] ✅ closed 2026-04-20
  - Resolution: 早期 Phase 1 结论"仓库无预置文献数据"已被刷新版 `literature-data-map.md` 修正。真实数据源已确认：output/（894 JSON）和 Zotero storage（815 文件）。
  - Closed by: Morpheus Phase 1 刷新关闭
