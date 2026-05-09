# SESSION_SNAPSHOT

Facts:

- 本地 team 记忆目录 `.squad/memory/` 已建立。
- 记忆分层文件已创建（README/TEAM_MEMORY/DECISION_TRAIL/OPEN_THREADS）。
- memory 读取顺序已接入 `start-here.md`（第14–16项）。
- memory 更新责任已写入 `project-conventions/SKILL.md`（"Team memory persistence"段）。
- Morpheus 启动自检已完成：无活跃阻塞，无漂移项，requirement-pool 无积压。
- `.github/copilot-instructions.md` 已补充完成（含共享规则、角色分工、模型偏好）。
- `.squad/identity/wisdom.md` 已补充完成（3 条可复用模式）。
- **Phase 1 已关闭（刷新版 2026-04-20）**：两大真实数据源确认（output/ 894 JSON + Zotero storage 815 文件）。检查点：`.squad/backups/checkpoint-phase1-20260420-0339/`。
- **Phase 2 已关闭（2026-04-20）**：`src/keyword_filter.py` 实现完成。合同摘要：
  - 公开 API：`keyword_prefilter(keywords: list[str], records: list[dict]) -> list[dict]`
  - 纯函数，无副作用，无 I/O，无外部依赖
  - Unicode NFKC 归一化 + casefold + 子串匹配
  - 识别三类字段：title-like（21 变体）、abstract-like（28 变体）、keyword-like（24 变体），含中英文别名
  - 递归下降搜索嵌套结构中的匹配键；非 dict 记录静默跳过；关键词去重
  - 与 output/ 已有产物（source_pdf、abstract 等字段）兼容
  - 检查点：`.squad/backups/checkpoint-phase2-20260420-0345/`

Decisions:

- 采用"Facts / Decisions / Open / Next"四段式最小快照。
- 规则级结论继续以 `.squad/decisions.md` 为准，memory 作为检索层。
- Phase 1 发现结论（修正）：真实数据源已确认。实现层以 output/ 和 Zotero storage 为核心设计参考。
- Phase 2 实现决策：关键词预过滤采用纯函数式设计，字段识别覆盖中英文学术别名，支持后续管道组合。

- **Phase 3 已关闭（2026-04-20）**：`tests/test_keyword_filter.py` 全部通过（6/6）。测试覆盖摘要：
  - 空关键词 → 空列表（边界）
  - 无匹配 → 空列表（否定路径）
  - 多关键词 OR 语义（核心合同）
  - OR-only 显式断言（AND 不要求）
  - 中文关键词匹配（Unicode 路径）
  - 超长输入文本处理（性能/鲁棒性）
  - 检查点：`.squad/backups/checkpoint-phase3-20260420-0349/`
- **Phase 4 已关闭（2026-04-20）**：Oracle 真实数据验证通过。验证摘要：
  - 10 条真实提取记录（来自 batch_test_109papers/），覆盖中英文论文、多学科领域
  - 3 场景验证：高相关域关键词（7/10 匹配）、过程参数关键词（1/10 匹配）、高级技术关键词（0/10 匹配）
  - 全部结果符合预期：OR 语义正确、Unicode 无误、零误报
  - keyword_prefilter 经实现→测试→真实数据三重确认，可投入管道集成
  - 检查点：`.squad/backups/checkpoint-phase4-20260420-0352/`

- **Phase 5 已关闭（2026-04-20）**：文档整合完成。README.md 文献检索模块章节已包含 Phase 1-4 全部产出（数据发现、预过滤实现、测试覆盖、真实数据验证）。DECISION_TRAIL.md 已包含完整的 Phase 1-4 决策链。检查点：`.squad/backups/checkpoint-phase5-20260420-0356/`。
- **Phase 6 已关闭（2026-04-20）**：free-improvement 迭代完成。新增第 7 个测试 `test_keyword_prefilter_matches_real_record_shapes_from_phase_outputs`，使用仿真 output/ 提取产物结构验证递归下降搜索。7/7 passed, 0.05s。keyword_prefilter 模块五层验证链完整（实现→测试→真实数据→文档→real-shape 回归）。检查点：`.squad/backups/checkpoint-phase6-20260420-0359/`。

- **Folder traversal 已关闭（2026-04-20）**：`src/folder_traversal.py` 实现完成 + `tests/test_folder_traversal.py` 4/4 通过。联合 keyword_filter 7/7 = 全套 11/11 passed (0.07s)。模块合同摘要：
  - 公开 API：`collect_folder_records(folder_paths, keywords=None, allowed_extensions=None) -> list[dict]`，别名 `traverse_folder`
  - 递归遍历用户提供的文件夹，支持 .json/.jsonl/.csv/.txt
  - 识别真实产物类型（full_extract, hybrid_retrieval, writing_material_pack, academic_scoring, causal_dag, project_view, zotero_outline）
  - 每条记录含 source_root / path / relative_path / record_type / filename 可追溯字段
  - 内置 keyword_prefilter 集成：传入 keywords 时自动应用关键词预过滤
  - 防御性设计：空路径跳过、不存在目录跳过、文件读取异常静默降级
  - 检查点：`.squad/backups/checkpoint-phase6-traversal-20260420-0408/`

- **Extraction pipeline 已关闭（2026-04-20）**：`src/extraction_pipeline.py` 实现完成 + `tests/test_extraction_pipeline.py` 5/5 通过（含 Tank 3 个边界测试）。联合全套测试 16/16 passed (0.09s)。模块合同摘要：
  - 公开 API：`extract_literature_context(folder_paths, keywords=None, allowed_extensions=None) -> list[dict]`
  - 编排已有三模块：folder_traversal（遍历）→ keyword_prefilter（预过滤）→ 内容提取
  - 内容提取优先级：chunks > focus_points > abstract/text > title（分层降级）
  - 每条输出含 content、content_type、provenance（源路径追溯）、metadata（title/chunk_id/section 等）
  - 支持 dict payload（映射提取）、list payload（逐条提取）、str payload（直接文本）、record-level text 字段
  - 段落级关键词二次过滤（_segment_matches）——遍历+预过滤后，仅返回关键词命中的具体段落/chunk
  - 无新外部依赖——仅使用 keyword_filter + folder_traversal + 标准库
  - 检查点：`.squad/backups/checkpoint-phase6-extraction-20260420-0414/`

- **Tank 边界测试已完成（2026-04-20）**：extraction_pipeline 新增 3 个边界测试——malformed lightweight inputs 安全跳过、keyword pruning 可产出空列表、mixed-source provenance 在 focus_point+text+chunk 混合场景下保持稳定。全套 5/5 passed。

- **README 文档最终更新（2026-04-20）**：新增 Phase 7 Oracle extraction 真实数据验证章节（4 场景结果表 + 验证发现）。修正测试计数（keyword_filter 7/7, extraction_pipeline 5/5 含 Tank 边界测试, 全套 16/16）。新增 extraction validation report 引用。文档层完整覆盖检索管道全生命周期。

Open:

- （无漂移项。HARD-STOP [intelligent-chat-hard-stop] 已关闭后续转为 requirement pool。）

Next:

- ✅ **所有 Intelligent Chat Phase 1-5 支持任务已完成并 Morpheus 批准。** 检索管道三模块（keyword_prefilter 7/7、folder_traversal 4/4、extraction_pipeline 5/5）全部实现、测试、真实数据验证均已交付。前端修复周期（Switch 锁定 → Trinity 修复 → Tank 批准）已完成。
- ✅ **Tier 3 检查点恢复成功（2026-04-21 01:10:39）**：Ralph 完成全量 U1A-3269 查询集评估。最终指标：2,748/2,748 (100%)、Recall@5=0.25%、MRR=0.4%。三个产物已持久化（progress.jsonl 2.7MB、per_query.jsonl 840KB、metrics.json 735B）。自动链到 Morpheus 评审 + Tank 审计（用户指令）。
- 🔄 **Board 状态**：Tier 3 完成后，自动链在进行。无新决策 inbox 文件；决策合并暂停至 Morpheus/Tank 交付。
- ⚠️ Zotero jasminum-outline.json 缺结构化元数据的约束仍有效（非阻塞，已跟踪于 OPEN_THREADS）。
- **最新检查点**：`.squad/orchestration-log/20260421T011311Z-ralph-tier3-checkpoint-resume-completion.md`