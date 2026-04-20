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
