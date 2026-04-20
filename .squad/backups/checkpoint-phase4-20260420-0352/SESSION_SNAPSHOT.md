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

Open:

- （无漂移项）

Next:

- Phase 5 可启动：文件夹遍历模块和提取管道实现（phase-plan 中的 folder traversal + extraction pipeline）。keyword_prefilter 已经过实现 + 测试 + 真实数据验证三重确认，可作为管道中的预过滤阶段直接集成。
- Phase 5 注意：Zotero jasminum-outline.json 仅含 PDF 大纲，不含结构化元数据——此约束不影响 keyword_prefilter（它处理已解析的 dict 记录，不直接读取文件），但影响提取管道的元数据获取策略。