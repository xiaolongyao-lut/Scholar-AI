# OPEN_THREADS

## Active

- [async-ingestion-batch] ⏳ WAITING FOR USER 2026-04-20
  - Description: Batch async ingestion for large literature folders——requirement pool 遗留项。涉及大规模并发加载、内存管理、进度报告等设计决策。
  - Status: 阻塞 (WAITING FOR USER)。需 Owner 确认优先级和实现时序。
  - Owner: Owner（需求确认）
  - Evidence: requirement-pool inventory

## Closed

- [phase4-metadata-constraint] ✅ CLOSED 2026-04-26 (round-1 brief 030334) → Non-blocking by design, pipeline-independent
  - Resolution: Three pipeline modules (`keyword_prefilter` 7/7 + `folder_traversal` 4/4 + `extraction_pipeline` 5/5 = 16/16 tests pass, plus Oracle 109-paper 4-scenario validation all PASS) operate correctly without `abstract/keywords/authors/year` from `jasminum-outline.json`. `folder_traversal.py` references `zotero_outline` only as a known record-type label, not as a dependency on structured metadata fields. The thread has held NOTED status for 6 days with no new evidence escalating it; SESSION_SNAPSHOT line 50-54 documents the independence directly. Future structured-metadata needs (re-ranking layer, citation triple `[作者, 年份]` enforcement under `citation_auditor`) are tracked separately under goal-drift §4 line 93 and are NOT regressions of this thread.
  - Evidence: `grep "jasminum.outline" my-project/src/` → 1 hit (folder_traversal.py, label-only); 16/16 test pass record in SESSION_SNAPSHOT; no churn in this thread since 2026-04-20.
  - Closed by: Morpheus self-update authority (Memory 维护, no review required per charter Self-Update Authority §Memory)

- [intelligent-chat-hard-stop] ✅ CLOSED 2026-04-20 → Phase 1-5 Shipped
  - Resolution: Intelligent Chat 完整实现链已完成（Phase 1 发现 → Phase 2 实现 → Phase 3 测试 → Phase 4 验证 → Phase 5 前端修复及检查）。前端修复周期经历"Switch 锁定 → Trinity 修复 → Tank 批准"流程，最终 Morpheus 批准全链投产。extraction_pipeline 和 folder_traversal 模块已通过 16/16 单元+集成+边界测试，Oracle 真实数据验证（109 篇论文，4 场景）全部 PASS。frontend/ 日志查询功能和后端查询 API 已对接就绪。
  - Closed by: Morpheus Phase 1-5 APPROVED, Trinity repair cycle + Tank verification APPROVED

- [team-memory-adoption] ✅ closed 2026-04-20
  - Resolution: `start-here.md` 已接入读取顺序（第14-16项），`project-conventions/SKILL.md` 已写入更新责任。
  - Closed by: Squad 巡检确认
- [phase1-no-data-correction] ✅ closed 2026-04-20
  - Resolution: 早期 Phase 1 结论"仓库无预置文献数据"已被刷新版 `literature-data-map.md` 修正。真实数据源已确认：output/（894 JSON）和 Zotero storage（815 文件）。
  - Closed by: Morpheus Phase 1 刷新关闭
