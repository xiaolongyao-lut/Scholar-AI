# DECISION_TRAIL

> 记录格式：
>
> - Date:
> - Scope:
> - Decision:
> - Why:
> - Evidence:
> - Impact:

## 2026-04-20

- Date: 2026-04-20
- Scope: team-memory
- Decision: 建立本地持久记忆目录 `.squad/memory/`，作为 team 默认可读知识层。
- Why: 避免跨会话信息丢失，支持夜班/多成员持续接力。
- Evidence: `.squad/memory/README.md`, `.squad/identity/start-here.md`（接入后）
- Impact: 所有成员可按统一模板沉淀事实、决策、未决和下一步。

### 2026-04-20 Morpheus 自主更新 — 启动自检关闭漂移项

- **操作**：SESSION_SNAPSHOT 中两条 Open 项（memory 接入 start-here / memory 责任写入 SKILL.md）标记为已完成，迁入 Facts；Next 更新为等待 Phase 1。
- **触发原因**：启动自检发现 `start-here.md` 第14–16项已含 memory 读取顺序，`SKILL.md` 已含 "Team memory persistence" 段落，两项均有文件证据支撑。
- **结果**：SESSION_SNAPSHOT Open 区清空，状态对齐现实。OPEN_THREADS 无需变更（已无活跃项）。requirement-pool 无积压。
- **是否通知 Owner**：否（在 Owner 检查时可见）

### Morpheus 自主更新 — 第二次启动自检

- **操作**：SESSION_SNAPSHOT Next 第二项（等待 Owner 补充 copilot-instructions / wisdom）关闭并迁入 Facts；Next 更新指向 Phase 1 文献发现就绪。
- **触发原因**：自检发现 `.github/copilot-instructions.md` 已含完整共享规则与模型偏好，`.squad/identity/wisdom.md` 已含 3 条可复用模式。两项等待条件均已满足。
- **观察**：`decisions.md` 中模型偏好版本号（如 `gpt-5.2-codex`）与 `copilot-instructions.md` 当前版本（如 `GPT-5.4`）存在差异。运行时以 `copilot-instructions.md` 为准，`decisions.md` 保留历史记录，非阻塞。
- **结果**：SESSION_SNAPSHOT 事实更新、Next 指向 Phase 1 核心路径。OPEN_THREADS 无变更（无活跃项）。requirement-pool 无积压。
- **是否通知 Owner**：否（在 Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 1 关闭：文献数据发现完成

- **操作**：关闭 Phase 1（Core literature extraction discovery）。基于 Trinity 产出的 `.squad/discovery/literature-data-map.md` 完成架构评审。更新 SESSION_SNAPSHOT、TEAM_MEMORY、DECISION_TRAIL。创建检查点 `.squad/backups/checkpoint-phase1-20260420-0333/`。
- **触发原因**：Trinity 扫描 data/、output/、resources/、仓库根目录，未发现 .json/.jsonl/.csv/.txt 格式的文献数据文件。这是一个有效的发现结果，表明当前仓库中不存在预置文献数据。
- **结果**：
  - Phase 1 发现结论确认：仓库中无预置文献数据文件。系统需在运行时从用户提供的文件夹（如 Zotero 目录、笔记本文件夹）动态摄取数据。
  - 架构判断：此结果不阻塞 Phase 2（实现）和 Phase 3（测试）。Phase 2 可正常构建文件夹遍历和提取管道；Phase 3 可使用合成测试数据或最小样本进行验证。
  - 检查点已保存：`.squad/backups/checkpoint-phase1-20260420-0333/`（含全部 memory 文件快照）。
- **是否通知 Owner**：否（Phase 1 关闭为常规流程，Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 1 刷新关闭：基于真实数据源的发现修正

- **操作**：基于刷新后的 `literature-data-map.md` 修正 Phase 1 结论。更新 SESSION_SNAPSHOT、TEAM_MEMORY、OPEN_THREADS、DECISION_TRAIL。创建刷新版检查点 `.squad/backups/checkpoint-phase1-20260420-0339/`。
- **触发原因**：用户明确指出 output/ 是历史提取产物、D:\zotero\zoterodate\storage 是文献库。刷新后的 data-map 扫描了这两个路径，发现丰富的真实数据（output/ 894 JSON, Zotero 815 文件含 83 jasminum-outline.json）。早期"仓库无预置文献数据"的结论需要修正。
- **结果**：
  - Phase 1 发现结论修正：真实数据源已确认，结构已采样。output/ 产物覆盖多层提取管道（full_extract → hybrid_retrieval → academic_scoring → causal_dag → project_view）。Zotero storage 以 PDF 附件为主，jasminum-outline.json 仅提供大纲。
  - 架构判断：Phase 2（实现）可参考 output/ 已有产物结构设计提取管道；Phase 3（测试）可使用真实数据验证，无需依赖合成数据。Phase 4 如需结构化元数据（abstract/keywords/authors/year），需额外解析方案——已记入 OPEN_THREADS 作为非阻塞约束。
  - 检查点已保存：`.squad/backups/checkpoint-phase1-20260420-0339/`。
- **是否通知 Owner**：否（用户已知晓刷新触发，结果在 Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 2 关闭：keyword_prefilter 实现完成

- **操作**：关闭 Phase 2（关键词预过滤模块实现）。审查 `src/keyword_filter.py` 实现合同，更新 SESSION_SNAPSHOT、TEAM_MEMORY、DECISION_TRAIL。创建检查点 `.squad/backups/checkpoint-phase2-20260420-0345/`。
- **触发原因**：`src/keyword_filter.py` 已实现完整的关键词预过滤合同，满足 phase-plan "Keyword-first relevance filtering before heavier extraction" 要求。
- **结果**：
  - **实现合同摘要**：公开 API `keyword_prefilter(keywords, records) -> list[dict]`。纯函数，无副作用，无 I/O。Unicode NFKC 归一化 + casefold + 子串匹配。识别三类字段（title/abstract/keyword，含中英文别名共 73 个变体）。递归下降搜索嵌套结构中的匹配键。关键词去重后扫描。非 dict 记录静默跳过。
  - **设计评价**：接口简洁且防御性良好（空输入快返回、类型检查、Unicode 归一化）。字段识别覆盖中英文学术常见命名，与 output/ 已有产物（source_pdf、abstract 等）兼容。纯函数设计支持后续管道组合。
  - **OPEN_THREADS 评估**：实现未引入新的下游约束或阻塞。现有 phase4-metadata-constraint 仍然有效，无需新增条目。
  - 检查点已保存：`.squad/backups/checkpoint-phase2-20260420-0345/`（含更新前的 memory 快照）。
- **是否通知 Owner**：否（Phase 2 关闭为常规流程，Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 3 关闭：keyword_prefilter 单元测试验证完成

- **操作**：关闭 Phase 3（keyword_prefilter 测试验证）。审查 `tests/test_keyword_filter.py` 测试覆盖，运行全部测试确认通过，更新 SESSION_SNAPSHOT、TEAM_MEMORY、DECISION_TRAIL。创建检查点 `.squad/backups/checkpoint-phase3-20260420-0349/`。
- **触发原因**：`tests/test_keyword_filter.py` 已编写完成，包含 6 个测试用例，覆盖 keyword_prefilter 公开 API 的核心合同、边界条件、Unicode 支持和鲁棒性。
- **结果**：
  - **测试覆盖摘要**（6/6 passed, 0.05s）：
    1. `test_keyword_prefilter_empty_keywords_returns_empty_list` — 空关键词边界
    2. `test_keyword_prefilter_no_matches_returns_empty_list` — 否定路径
    3. `test_keyword_prefilter_multi_keyword_or_semantics` — 多关键词 OR 匹配
    4. `test_keyword_prefilter_multi_keyword_does_not_require_and_semantics` — 显式 OR-only 合同断言
    5. `test_keyword_prefilter_matches_chinese_keywords` — 中文关键词 Unicode 匹配
    6. `test_keyword_prefilter_handles_very_long_input_text` — 超长输入鲁棒性
  - **合同验证结论**：keyword_prefilter 的 OR 语义、Unicode NFKC 归一化、casefold、子串匹配、空输入防御、非 dict 跳过等行为均由测试覆盖。纯函数无副作用设计使测试无需 mock 或 fixture。
  - **OPEN_THREADS 评估**：测试未暴露新的下游约束或阻塞。现有 phase4-metadata-constraint 仍然有效，无需新增条目。
  - **设计观察**：测试质量良好——第 4 个测试包含显式断言消息（"Contract is OR-based; AND is not required."），这是管道集成时的关键假设文档。测试覆盖了中英文双语场景，与实现中 73 个字段别名的设计意图一致。
  - 检查点已保存：`.squad/backups/checkpoint-phase3-20260420-0349/`（含更新后的 memory 快照）。
- **是否通知 Owner**：否（Phase 3 关闭为常规流程，Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 4 关闭：Oracle 真实数据验证完成

- **操作**：关闭 Phase 4（Oracle real-record validation）。审查 `.squad/discovery/oracle-validation-report.md`，确认验证结论，更新 SESSION_SNAPSHOT、TEAM_MEMORY、DECISION_TRAIL。创建检查点 `.squad/backups/checkpoint-phase4-20260420-0352/`。
- **触发原因**：Oracle 使用 Phase 1 发现的真实提取数据（batch_test_109papers/）对 keyword_prefilter 进行了 3 场景 10 条记录的实际验证。
- **结果**：
  - **验证结论**：✅ PASS。3 个场景覆盖高相关域关键词（70% 匹配率）、过程参数关键词（10% 匹配率）、高级技术关键词（0% 匹配率）。所有结果符合预期。
  - **确认的设计属性**：OR 语义正确、Unicode 中英文混合处理无误、大小写不敏感子串匹配正常、字段检测灵活、零误报。
  - **边缘观察**：首 chunk 偏差（introduction chunk 可能不代表全文主题）为预期行为，非 bug。
  - **OPEN_THREADS 评估**：验证未暴露新的下游约束。现有 phase4-metadata-constraint（Zotero outline 缺结构化元数据）仍然有效且已在跟踪中，无需新增条目。
  - **架构判断**：keyword_prefilter 经过实现（Phase 2）→ 单元测试（Phase 3）→ 真实数据验证（Phase 4）三重确认，可作为检索管道的预过滤阶段直接集成。
  - 检查点已保存：`.squad/backups/checkpoint-phase4-20260420-0352/`。
- **是否通知 Owner**：否（Phase 4 关闭为常规流程，Owner 检查时可见）

---

## 2026-04-20 Phase 1-4 Decision Chain Summary

### Phase 1: Literature Data Discovery

**What:** Scanned real data sources to catalog literature artifacts available for retrieval pipeline.

**Decision:**
- Real data exists in two locations:
  1. Historical extraction output: `output/` (894 JSON files in batch_test_109papers structure)
  2. Zotero library: `D:\zotero\zoterodate\storage\` (815 files, 83 jasminum-outline.json outlines)
- Pipeline will accept real extraction artifacts at runtime (no pre-packaged data in repo)

**Why:** User-provided folders (Zotero, local literature) are the true data source; project should ingest from these, not carry standalone copies.

**Evidence:** `.squad/discovery/literature-data-map.md` (full scan report with file counts, structure samples)

**Impact:** Phase 2-4 can proceed with real data; no synthetic test data needed.

---

### Phase 2: keyword_prefilter Implementation

**What:** Implemented `src/keyword_filter.py` as public API for keyword-based record prefiltering.

**Decision:**
- Function signature: `keyword_prefilter(keywords: list[str], records: list[dict]) -> list[dict]`
- Match strategy: OR-based (record matches if ANY keyword found in ANY relevant field)
- Normalization: Unicode NFKC + casefold + substring matching
- Field recognition: 73 normalized variants covering title/abstract/keyword categories (English + Chinese aliases)
- Design: Pure function, stateless, no I/O—supports pipeline composition

**Why:** Keyword-first prefiltering is the lightest effective gate for literature retrieval. OR semantics allow flexible multi-keyword queries. Unicode normalization + case folding support multilingual corpora (key for mixed English/Chinese papers).

**Evidence:** `src/keyword_filter.py` implementation (lines 1–190); design mirrors common NLP normalization practice; field aliases empirically grounded in Phase 1 data structure analysis.

**Impact:** Provides solid entry point for retrieval pipeline; downstream stages can build on this without re-normalizing.

---

### Phase 3: Unit Test Coverage

**What:** Wrote comprehensive test suite `tests/test_keyword_filter.py` covering core contract and edge cases.

**Decision:**
- 6 test cases covering:
  1. Empty keyword boundary
  2. No-match path
  3. Multi-keyword OR semantics (explicit)
  4. OR-only contract assertion (documentation through assertion message)
  5. Chinese keyword matching (Unicode support)
  6. Robustness under 200K character input
- All tests pass (0.05s); pure function design eliminates need for mocks/fixtures

**Why:** Tests serve as executable specification of contract guarantees (OR semantics, Unicode handling, edge case robustness). Tests are documentation for downstream pipeline integrators.

**Evidence:** `tests/test_keyword_filter.py` (lines 1–69); test 4 includes explicit contract message ("Contract is OR-based; AND is not required.").

**Impact:** keyword_prefilter is now tested and ready for integration; new consumers can reference tests as specification.

---

### Phase 4: Real-Record Validation

**What:** Oracle validated keyword_prefilter against 10 real records sampled from Phase 1 extraction output.

**Decision:**
- Validation confirms function behavior on realistic data:
  - Scenario 1 (domain keywords): 7/10 matches (70%)—demonstrates OR semantics on real corpus
  - Scenario 2 (process parameters): 1/10 matches (10%)—shows selective filtering, no false positives
  - Scenario 3 (advanced tech): 0/10 matches (0%)—zero spurious matches
- All findings expected; no bugs discovered
- Function is production-ready for retrieval pipeline

**Why:** Unit tests validate contract; real-record validation ensures contract holds on actual project data. This three-stage validation (implementation → unit tests → real-world) reduces risk of field mismatch or unexpected corpus behavior.

**Evidence:** `.squad/discovery/oracle-validation-report.md` (full test protocol, sample table, scenario analysis)

**Impact:** keyword_prefilter fully validated. Retrieval pipeline can integrate immediately without additional proof-of-concept work.

---

### Phase 1-4 Synthesis: What Was Built

**Complete Component:** Keyword-first prefilter for literature retrieval

- ✅ **Phase 1 (Discovery):** Real data sources identified and mapped
- ✅ **Phase 2 (Implementation):** keyword_prefilter function implemented with robust normalization and field recognition
- ✅ **Phase 3 (Testing):** Comprehensive unit tests covering contract and edge cases
- ✅ **Phase 4 (Validation):** Real-world validation on extracted paper chunks confirms correct behavior

**Downstream Use:**
- Input: Records (dicts) from extraction pipeline
- Process: Filter by keyword presence in title/abstract/keyword fields
- Output: Matched records for ranking, scoring, or dialogue
- Design: Pure function, composable, production-ready

**Quality Gates Passed:**
- Implementation spec: ✅ OR semantics, Unicode normalization, field recognition
- Unit test spec: ✅ 6/6 passing, edge cases covered, multilingual support confirmed
- Real-data spec: ✅ 3/3 scenarios validated on real corpus, no bugs, expected match rates

---

### Architecture Outcome

The keyword_prefilter module is now ready for production integration into the literature retrieval pipeline. It provides:

1. **Flexibility:** OR-based matching supports broad multi-keyword queries
2. **Robustness:** Unicode handling and case folding work correctly on mixed corpora
3. **Composability:** Pure function design allows integration with ranking and dialogue stages without side-effect coupling
4. **Transparency:** Test suite and validation report document behavior guarantees for downstream integrators

**Next Phase:** Retrieval pipeline integration (ranking, dialogue, UI binding) can now proceed without revisiting prefilter concerns.

### 2026-04-20 Morpheus — Phase 6 关闭：real-shape 回归测试覆盖完成

- **操作**：关闭 Phase 6（free-improvement iteration）。确认 `tests/test_keyword_filter.py` 新增第 7 个测试 `test_keyword_prefilter_matches_real_record_shapes_from_phase_outputs`，全部 7/7 通过（0.05s）。更新 SESSION_SNAPSHOT、TEAM_MEMORY、DECISION_TRAIL。创建检查点 `.squad/backups/checkpoint-phase6-20260420-0359/`。
- **触发原因**：Phase 6 free-improvement 迭代的核心产出是 real-shape 回归测试——使用仿真 output/ 提取产物结构（source_pdf、meta、chunks、focus_points、stage_manifest 嵌套字段）验证 keyword_prefilter 递归下降搜索在真实记录形状下的正确性。这填补了 Phase 3 单元测试使用简化 dict 与 Phase 4 真实数据验证之间的回归安全网缺口。
- **结果**：
  - **新测试覆盖**：第 7 个测试使用三条仿真记录，分别模拟 `01_full_extract.json`（带 chunks）、`02_hybrid_retrieval.json`（带 focus_points）、`project_view.json`（带 stage_manifest 嵌套 chunks）结构。三条关键词（nitriding, temperature field, machine learning）分别匹配三条记录，验证递归下降搜索能正确穿透多层嵌套。
  - **测试基线**：7/7 passed, 0.05s。keyword_prefilter 的合同现在由 7 个测试覆盖：边界（空输入）、否定路径、OR 语义、OR-only 合同断言、中文 Unicode、超长输入鲁棒性、real-shape 回归。
  - **OPEN_THREADS 评估**：现有 phase4-metadata-constraint 仍然有效（Zotero outline 缺结构化元数据），Phase 6 未引入新阻塞或约束。
  - **架构判断**：real-shape 回归测试与 `project-conventions/SKILL.md` 中"Mirror real record shapes in regressions"模式一致。keyword_prefilter 模块现在拥有完整的五层验证链：实现（Phase 2）→ 单元测试（Phase 3）→ 真实数据验证（Phase 4）→ 文档整合（Phase 5）→ real-shape 回归（Phase 6）。
  - 检查点已保存：`.squad/backups/checkpoint-phase6-20260420-0359/`。
- **是否通知 Owner**：否（Phase 6 关闭为常规流程，Owner 检查时可见）

### 2026-04-20 Morpheus — Phase 5 关闭：文档整合完成

- **操作**：关闭 Phase 5（文档整合与记忆沉淀）。确认 README.md 文献检索模块章节已整合 Phase 1-4 全部产出。确认 DECISION_TRAIL.md 已包含完整的 Phase 1-4 决策链摘要。更新 SESSION_SNAPSHOT、TEAM_MEMORY。创建检查点 `.squad/backups/checkpoint-phase5-20260420-0356/`。
- **触发原因**：Phase 5 任务要求整合 Phase 1-4 产出到 README.md 文献检索模块章节，并将完整决策链写入 DECISION_TRAIL.md。两项工作均已完成。
- **结果**：
  - **README.md 文献检索模块章节**：包含 Phase 1（数据发现）、Phase 2（keyword_prefilter 实现）、Phase 3（测试覆盖）、Phase 4（真实数据验证）的完整描述，含 API 签名、字段识别、验证场景表格和模块集成指南。
  - **DECISION_TRAIL.md Phase 1-4 决策链**：包含每阶段的 What/Decision/Why/Evidence/Impact 以及综合架构结论。
  - **OPEN_THREADS 评估**：现有 phase4-metadata-constraint 仍然有效（Zotero jasminum-outline.json 缺结构化元数据），不影响文档完整性，无需新增条目。
  - **架构判断**：文档层已对齐实现层。keyword_prefilter 的 API 合同、测试规格和验证结论均有文档记录，后续管道集成者可直接参考 README.md 和 DECISION_TRAIL.md。
  - 检查点已保存：`.squad/backups/checkpoint-phase5-20260420-0356/`。
- **是否通知 Owner**：否（Phase 5 关闭为常规流程，Owner 检查时可见）
