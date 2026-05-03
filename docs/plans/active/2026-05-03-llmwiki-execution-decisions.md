# LLM-Wiki RAG 执行决策记录

## 决策时间：2026-05-03 15:40 UTC+8

## 核心决策

### D1: 执行范围
- **决策**：完成全部 240 任务（LMWR-224~463）
- **理由**：用户要求"做完吧"，可以在执行过程中继续编写后续任务
- **影响**：不限于最小闭环，完整实现 Wiki 系统所有功能

### D2: Wiki-first Retrieval
- **默认状态**：可开可关，通过 `ENABLE_WIKI_FIRST_RETRIEVAL` 环境变量控制
- **查询顺序**：wiki FTS → wiki linked pages → wiki embeddings (optional) → raw RAG fallback
- **付费测试**：支持 env 控制的付费测试模式
- **影响**：需要在 `runtime_env.py` 和 `main_rag_workflow.py` 中实现开关逻辑

### D3: Frontmatter 格式
- **决策**：JSON frontmatter (`---json\n{...}\n---`)
- **理由**：严格、易解析、与现有 Python 生态兼容
- **不支持**：YAML frontmatter（暂不支持，后续可扩展）
- **影响**：`wiki/page_store.py` 中 `render_frontmatter` 使用 JSON

### D4: 外部资料源集成
- **是否做**：做（Wave 13）
- **优先级**：Zotero > Obsidian > EndNote（按用户建议）
- **写回策略**：先不做写回，只读索引
- **影响**：Wave 13 任务保留，实现只读 connector

### D5: Graph 存储格式
- **决策**：JSON + SQLite 双模式
  - `graph.json`：人类可读、易调试、版本控制友好
  - `graph.db`：SQLite 表，支持复杂查询（typed edges、blast radius）
- **理由**：兼顾可读性和查询性能
- **影响**：`wiki/graph.py` 需要实现双写逻辑

### D6: API Router 权限模型
- **决策**：用户级权限控制
- **实现**：前端界面用户可选择是否添加 API key
- **状态转换**：Draft → Review → Final 由用户控制（不需要审批流程）
- **影响**：
  - `routers/wiki_router.py` 需要实现用户权限检查
  - 前端需要 API key 管理界面
  - 状态转换 API 需要用户身份验证

### D7: 测试失败修复
- **决策**：先修复所有简单测试失败（包括 27 个 squad_cli）
- **执行顺序**：
  1. 修复 legacy_root 路径问题（13 个）
  2. 修复 squad_cli 命令测试（27 个）
  3. 修复 contextual/export/observability（9 个）
  4. 修复 reranker（3 个）
- **验收**：每个修复后运行 focused tests，确保不引入新失败
- **影响**：Task #15 优先级提升，在 Wave 3 之前完成

## 延续决策

### D8: Wave 执行顺序
按原计划顺序推进：
1. ✅ Wave 0: 治理文档
2. ✅ Wave 1: 数据模型 (23 tests)
3. ✅ Wave 2: Source/chunk registry (27 tests)
4. ✅ Wave 3: Markdown page store (39 tests)
5. ✅ Wave 4: Citation validator (35 tests)
6. ✅ Wave 5: Evidence adapter (26 tests)
7. ✅ Wave 6: Compiler dry-run (10 tests)
8. ✅ Wave 7: LLM gateway integration (15 tests, stub mode)
9. 🔄 Wave 8: Wiki-aware retrieval (10 tests, 基础功能完成)
10. ⏸️ Wave 9: Graph
11. ⏸️ Wave 10: Doctor/review queue
12. ⏸️ Wave 11: API contract
13. ⏸️ Wave 12: Frontend Wiki 工作台
14. ⏸️ Wave 13: 外部 connector
15. ⏸️ Wave 14: 评测和质量门禁
16. ⏸️ Wave 15: 迁移、MCP、长期维护

**进度**：185 wiki tests passing, 8 waves 完成（Wave 8 基础功能）
**核心能力**：数据模型、注册表、页面存储、引用验证、证据适配、编译器、LLM网关（stub模式）、FTS 检索（基础）

**Wave 8 剩余任务**：
- Linked page expansion（参考 WikiLoom）
- RAG fallback bridge（wiki 无命中时回退）
- Context pack renderer（token bounded）
- Query debug trace
- Saved exploration page flow

### D9: 回档策略
- 每个 Wave 开始前创建回档点
- 回档命名：`wave{N}-{slug}-{timestamp}`
- 回档路径：`.rollback_snapshots/`

### D10: 测试覆盖率要求
- 每个新模块至少 80% 行覆盖率
- 关键路径（citation validator、compiler、doctor）要求 90%+
- 每个 Wave 完成后运行 `pytest tests/wiki/ -v --cov=literature_assistant/core/wiki`

## 决策影响矩阵

| 决策 | 影响模块 | 优先级 | 预计工作量 |
|------|---------|--------|-----------|
| D1 | 全部 | P0 | 240 任务 |
| D2 | `runtime_env.py`, `main_rag_workflow.py`, `wiki/query.py` | P1 | Wave 8 |
| D3 | `wiki/page_store.py` | P0 | Wave 3 |
| D4 | `wiki/connectors/` | P2 | Wave 13 |
| D5 | `wiki/graph.py` | P1 | Wave 9 |
| D6 | `routers/wiki_router.py`, `frontend/` | P1 | Wave 11-12 |
| D7 | `tests/` | P0 | 立即执行 |

## 下一步行动

1. **立即**：修复 59 个测试失败（Task #15）
2. **然后**：继续 Wave 3 - Markdown page store（Task #18）
3. **并行**：在执行过程中编写后续 Wave 的详细任务

## 决策人
- 用户：小龙 姚
- 执行者：Claude (Kiro)
- 记录时间：2026-05-03T15:40:00+08:00
