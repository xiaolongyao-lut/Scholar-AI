# TEAM_MEMORY

## Stable Facts

- [routing] FACT: 代码级最终技术判断权归 Morpheus。 | EVIDENCE: `.squad/identity/requirement-scoring.md`, `.squad/decisions.md`
- [night-shift] FACT: refactor/schema/new dependency 为 hard-stop，夜班必须等待 Morpheus。 | EVIDENCE: `.squad/identity/night-shift-policy.md`
- [process] FACT: 任务前必须阅读 `.squad/identity/start-here.md` 指定入口文档。 | EVIDENCE: `.squad/skills/project-conventions/SKILL.md`

- [phase1-discovery-refreshed] FACT: 两大真实数据源已确认。(1) output/（历史提取产物）：894 JSON 文件，含 batch summary 和每篇论文多层产物（01_full_extract / 02_hybrid_retrieval / 03_academic_scoring / 04_causal_dag / project_view）。(2) D:\zotero\zoterodate\storage（文献库）：815 文件，以 PDF 附件为主，含 83 个 jasminum-outline.json（仅 PDF 大纲，无 abstract/keywords/authors/year）。 | EVIDENCE: `.squad/discovery/literature-data-map.md`（刷新版）
- [phase1-architecture-refreshed] FACT: output/ 产物可作为提取管道设计参考和真实测试数据；Zotero storage 是运行时摄取主目标文件夹。Phase 2/3 均不阻塞且有真实数据支撑。Phase 4 若需结构化元数据（abstract/keywords/authors/year），需从 PDF 正文或 Zotero API 提取，这是真实采样约束。 | EVIDENCE: `.squad/discovery/literature-data-map.md`, `.squad/identity/phase-plan.md`
- [data-source-roles] FACT: 用户明确定义——output/ 是历史提取产物，D:\zotero\zoterodate\storage 是文献库。 | EVIDENCE: 用户指令（2026-04-20 Phase 1 刷新）

## Reusable Patterns

- [memory] DECISION: 使用 `.squad/memory/*` 作为本地持久 team 记忆层。 | WHY: 可版本化、可追溯、可被所有 agent 直接读取。 | EVIDENCE: `.squad/memory/README.md`
- [phase-close] PATTERN: Phase 关闭时执行：追加 DECISION_TRAIL → 更新 SESSION_SNAPSHOT Next → 检查 OPEN_THREADS 可关闭项 → 复制 .squad/memory/ 到 .squad/backups/checkpoint-phaseX-<时间>/ 。 | WHY: 保证每个 Phase 有可追溯的记忆快照和决策记录。 | EVIDENCE: Phase 1 关闭流程
