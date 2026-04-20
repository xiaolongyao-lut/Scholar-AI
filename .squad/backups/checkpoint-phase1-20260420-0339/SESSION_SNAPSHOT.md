# SESSION_SNAPSHOT

Facts:

- 本地 team 记忆目录 `.squad/memory/` 已建立。
- 记忆分层文件已创建（README/TEAM_MEMORY/DECISION_TRAIL/OPEN_THREADS）。
- memory 读取顺序已接入 `start-here.md`（第14–16项）。
- memory 更新责任已写入 `project-conventions/SKILL.md`（"Team memory persistence"段）。
- Morpheus 启动自检已完成：无活跃阻塞，无漂移项，requirement-pool 无积压。
- `.github/copilot-instructions.md` 已补充完成（含共享规则、角色分工、模型偏好）。
- `.squad/identity/wisdom.md` 已补充完成（3 条可复用模式）。
- **Phase 1 已关闭（刷新版 2026-04-20）**：基于刷新后的 `literature-data-map.md`，确认两大真实数据源：
  - `output/`（历史提取产物）：895 文件（894 .json, 1 .txt），含 batch summary + 每篇论文多层 JSON 产物（01_full_extract / 02_hybrid_retrieval / 03_academic_scoring / 04_causal_dag / project_view 等）。
  - `D:\zotero\zoterodate\storage`（文献库）：815 文件，以 PDF 附件为主，含 83 个 jasminum-outline.json（PDF 大纲/目录结构，无 abstract/keywords/authors/year）。
- 架构判断（修正）：真实数据已存在且结构丰富。output/ 产物可直接作为提取管道的参考输入格式和测试数据；Zotero storage 是运行时摄取的主要目标文件夹。
- Phase 1 检查点（刷新版）：`.squad/backups/checkpoint-phase1-20260420-0339/`。

Decisions:

- 采用"Facts / Decisions / Open / Next"四段式最小快照。
- 规则级结论继续以 `.squad/decisions.md` 为准，memory 作为检索层。
- Phase 1 发现结论（修正）：真实数据源已确认。output/ 是历史提取产物（894 JSON），Zotero storage 是文献库（815 文件含 PDF 和大纲）。实现层应以这两个路径为核心设计参考。

Open:

- （无漂移项）

Next:

- Phase 2 可启动：按 `phase-plan.md` 构建文件夹遍历、关键词过滤、提取管道。设计应参考 output/ 中已有的提取产物结构（01_full_extract.json → chunks[]、source_pdf 等）。
- Phase 3 可启动：Tank 可使用 output/ 中的真实提取产物和 Zotero storage 中的真实 PDF 附件进行验证，无需依赖合成测试数据。
- Phase 4 注意：Zotero jasminum-outline.json 仅含 PDF 大纲（level/title/page），不含结构化元数据（abstract/keywords/authors/year）。如需结构化元数据，需从 PDF 正文或 Zotero API 获取，这是一个真实采样约束。