# TEAM_MEMORY

## Stable Facts

- [routing] FACT: 代码级最终技术判断权归 Morpheus。 | EVIDENCE: `.squad/identity/requirement-scoring.md`, `.squad/decisions.md`
- [night-shift] FACT: refactor/schema/new dependency 为 hard-stop，夜班必须等待 Morpheus。 | EVIDENCE: `.squad/identity/night-shift-policy.md`
- [process] FACT: 任务前必须阅读 `.squad/identity/start-here.md` 指定入口文档。 | EVIDENCE: `.squad/skills/project-conventions/SKILL.md`

- [phase1-discovery-refreshed] FACT: 两大真实数据源已确认。(1) output/（历史提取产物）：894 JSON 文件，含 batch summary 和每篇论文多层产物（01_full_extract / 02_hybrid_retrieval / 03_academic_scoring / 04_causal_dag / project_view）。(2) D:\zotero\zoterodate\storage（文献库）：815 文件，以 PDF 附件为主，含 83 个 jasminum-outline.json（仅 PDF 大纲，无 abstract/keywords/authors/year）。 | EVIDENCE: `.squad/discovery/literature-data-map.md`（刷新版）
- [phase1-architecture-refreshed] FACT: output/ 产物可作为提取管道设计参考和真实测试数据；Zotero storage 是运行时摄取主目标文件夹。Phase 2/3 均不阻塞且有真实数据支撑。Phase 4 若需结构化元数据（abstract/keywords/authors/year），需从 PDF 正文或 Zotero API 提取，这是真实采样约束。 | EVIDENCE: `.squad/discovery/literature-data-map.md`, `.squad/identity/phase-plan.md`
- [data-source-roles] FACT: 用户明确定义——output/ 是历史提取产物，D:\zotero\zoterodate\storage 是文献库。 | EVIDENCE: 用户指令（2026-04-20 Phase 1 刷新）

- [phase2-keyword-filter] FACT: `src/keyword_filter.py` 提供 `keyword_prefilter(keywords, records)` 纯函数 API。Unicode NFKC 归一化 + casefold + 子串匹配。识别 title/abstract/keyword 三类字段（73 个中英文别名变体）。递归下降搜索嵌套结构。无副作用、无 I/O、无外部依赖。 | EVIDENCE: `src/keyword_filter.py`
- [phase2-field-compat] FACT: keyword_filter 的字段识别集包含 source_pdf、abstract、keywords、title 等，与 output/ 中已有提取产物的字段命名兼容。 | EVIDENCE: `src/keyword_filter.py`（_TITLE_KEYS, _ABSTRACT_KEYS, _KEYWORD_KEYS 集合）

- [phase3-test-coverage] FACT: `tests/test_keyword_filter.py` 提供 6 个单元测试，覆盖边界（空输入）、否定路径（无匹配）、核心合同（多关键词 OR 语义 + 显式 AND-not-required 断言）、Unicode 路径（中文关键词）、鲁棒性（200K 字符超长输入）。全部通过，0.05s 完成。 | EVIDENCE: `tests/test_keyword_filter.py`, pytest 6/6 passed
- [phase3-contract-verified] FACT: keyword_prefilter 的 OR 语义合同已由测试显式验证——`test_keyword_prefilter_multi_keyword_does_not_require_and_semantics` 包含断言消息 "Contract is OR-based; AND is not required."。这是管道集成时的关键假设。 | EVIDENCE: `tests/test_keyword_filter.py` line 48

- [phase4-real-data-validated] FACT: keyword_prefilter 已通过 Oracle 真实数据验证。10 条来自 batch_test_109papers/ 的真实提取记录，3 个场景（高相关域 70% 匹配、过程参数 10% 匹配、高级技术 0% 匹配），全部符合预期。OR 语义、Unicode 中英文、大小写不敏感、零误报均确认。该模块已完成实现→单元测试→真实数据验证三重确认，可直接集成到检索管道。 | EVIDENCE: `.squad/discovery/oracle-validation-report.md`
- [phase4-first-chunk-bias] FACT: 首 chunk（introduction section）可能不完整代表全文主题，导致某些相关论文未被匹配（如长摘要论文的关键词在 chunk 深层）。这是预期行为而非 bug——过滤器搜索字段中实际出现的内容，不推断主题。 | EVIDENCE: `.squad/discovery/oracle-validation-report.md` Scenario 1 分析

- [phase6-real-shape-regression] FACT: `tests/test_keyword_filter.py` 第 7 个测试 `test_keyword_prefilter_matches_real_record_shapes_from_phase_outputs` 使用仿真 output/ 提取产物结构（source_pdf + meta + chunks、focus_points、stage_manifest 嵌套 chunks）验证 keyword_prefilter 递归下降搜索。7/7 passed, 0.05s。该测试填补了简化 dict 单元测试与 Oracle 真实数据验证之间的回归安全网。 | EVIDENCE: `tests/test_keyword_filter.py` lines 71-104, pytest 7/7 passed

- [phase5-docs-integrated] FACT: README.md 文献检索模块章节已整合 Phase 1-4 全部产出：数据发现（两大数据源）、keyword_prefilter 实现（API/字段识别/归一化/匹配策略）、测试覆盖（6/6 用例）、真实数据验证（3 场景 10 条记录）。DECISION_TRAIL.md 包含完整的 Phase 1-4 决策链（含 What/Decision/Why/Evidence/Impact 格式和综合架构结论）。文档层已对齐实现层。 | EVIDENCE: `README.md`, `.squad/memory/DECISION_TRAIL.md`

## Reusable Patterns

- [memory] DECISION: 使用 `.squad/memory/*` 作为本地持久 team 记忆层。 | WHY: 可版本化、可追溯、可被所有 agent 直接读取。 | EVIDENCE: `.squad/memory/README.md`
- [phase-close] PATTERN: Phase 关闭时执行：追加 DECISION_TRAIL → 更新 SESSION_SNAPSHOT Next → 检查 OPEN_THREADS 可关闭项 → 复制 .squad/memory/ 到 .squad/backups/checkpoint-phaseX-<时间>/ 。 | WHY: 保证每个 Phase 有可追溯的记忆快照和决策记录。 | EVIDENCE: Phase 1 关闭流程
