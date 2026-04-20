# OPEN_THREADS

## Active

- [phase4-metadata-constraint] ⚠️ NOTED 2026-04-20
  - Description: Zotero jasminum-outline.json 仅含 PDF 大纲结构（level/title/page），不含结构化元数据（abstract/keywords/authors/year）。output/ 中的 01_full_extract.json 前 5 行也未显示这些字段（可能在更深层）。如果 Phase 4 需要结构化文献元数据，需额外从 PDF 正文解析或 Zotero API 获取。
  - Status: 非阻塞。Phase 2/3 不受影响。Phase 4 设计时需考虑此约束。
  - Owner: Morpheus（架构判断）

## Closed

- [team-memory-adoption] ✅ closed 2026-04-20
  - Resolution: `start-here.md` 已接入读取顺序（第14-16项），`project-conventions/SKILL.md` 已写入更新责任。
  - Closed by: Squad 巡检确认
- [phase1-no-data-correction] ✅ closed 2026-04-20
  - Resolution: 早期 Phase 1 结论"仓库无预置文献数据"已被刷新版 `literature-data-map.md` 修正。真实数据源已确认：output/（894 JSON）和 Zotero storage（815 文件）。
  - Closed by: Morpheus Phase 1 刷新关闭
