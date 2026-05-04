# 遗留测试失败分类报告

**日期：** 2026-05-03
**测试运行：** pytest tests -q
**结果：** 22 failed, 1468 passed, 3 skipped
**改进：** 从 59 失败降至 22 失败（-62.7%）

## 最新收口（2026-05-04 22:25+ Codex）

- `pytest tests -q` → `1632 passed, 3 skipped`。
- 剩余 2 个失败已修复：
  - `tests/legacy_root/test_gateb_c6_repro.py::test_c6_reproducible_export_identical_hashes_across_reruns`
    - 根因：根目录 `gateb_phase_b_pool_export.py` 只是 import shim，脚本执行时没有转发 core `main()`；测试还依赖已迁移的旧 eval fixture 路径和长耗时真实检索。
    - 修复：shim 转发 CLI；core export 兼容迁移后的 `workspace_tests/evaluation_data/`；C6 reproducibility 测试改为临时目录 + tiny deterministic corpus。
  - `tests/test_validate_contextual_miss.py::test_validate_project_contextual_coverage_detects_missing_summary`
    - 根因：validation 脚本复用 `batch_contextualize()` 时未提供 validation-only key，导致缺 summary 时提前返回，不写 validation miss log。
    - 修复：validation-only 调用传入 `api_key="validation-only"`，仍不触发真实模型调用。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-464-test-failure-closeout.md`。

## 最新进展（2026-05-03 18:30+）

- **P0 Contextual Chunker (2)**：✅ 已修复（api_key=None 短路 + aggressive cost mode）
- **P0 Reranker (3)**：✅ 实际未失败（exit code 49 是 squad guard 误报）
- **P1 legacy_root (9)**：✅ 已修复（Query descriptor、路由前缀、阈值、响应格式）— commit 24d5ba6f
- **P2 Precompute/Migration (4)**：✅ 已修复（路径默认值、sys.path、兼容视图）— commit 672a73ac
- **剩余未修复：** Pipeline 可观测性 (2) + 编码 (1) + LLM Mock 残留 (1) = **约 4 个**
- **预估当前状态：** ~4-6 个失败（从 22 降至目标 <10 ✅）

## 失败分类

### 桶 1：legacy_root 路径/API 测试（9 个失败）

**特征：** `tests/legacy_root/` 路径下的测试

1. `test_gateb_c6_repro.py::test_c6_reproducible_export_identical_hashes_across_reruns`
2. `test_h41_final_hardening.py::TestH41FinalHarding::test_no_route_conflicts`
3. `test_pipeline_router_association.py::TestPipelineAssociationRouter::test_pipeline_run_returns_no_ai_association_bundle`
4. `test_pipeline_router_association.py::TestPipelineAssociationRouter::test_pipeline_run_returns_ai_association_bundle`
5. `test_pipeline_router_association.py::TestPipelineAssociationRouter::test_pipeline_analysis_enriched_strict_logic`
6. `test_pipeline_router_association.py::TestPipelineAssociationRouter::test_pipeline_run_prefers_in_memory_artifacts`
7. `test_recovery_api_routes_real.py::TestRecoveryAPIRoutes::test_recovery_error_handling`
   - **错误：** `Database connection failed`
   - **根因：** 数据库连接失败，可能是测试隔离问题
8. `test_resources_router.py::test_search_chunks_uses_backfilled_documents`
9. `test_resources_router.py::test_search_chunks_prefers_distinct_materials_before_repeat_chunks`
10. `test_resources_router.py::test_search_chunks_deduplicates_identical_chunks_within_same_material`

**根因分析：**
- 数据库连接失败（recovery_api_routes_real）
- 路由冲突检测失败（h41_final_hardening）
- 关联逻辑测试失败（pipeline_router_association）
- 搜索去重逻辑失败（resources_router）

**优先级：** 中（legacy 路径，可能不影响主流程）

### 桶 2：Contextual Chunker 测试（2 个失败）

1. `test_contextual_chunker.py::test_batch_contextualize`
   - **错误：** `assert False`
   - **根因：** 批量上下文化逻辑失败
2. `test_contextual_chunker.py::test_batch_contextualize_short_circuits_in_aggressive_cost_mode`
   - **根因：** 成本模式短路逻辑失败

**根因分析：**
- Contextual chunker 批量处理逻辑有 bug
- 可能与 LLM API mock 或成本控制逻辑相关

**优先级：** 高（影响上下文化分块功能）

### 桶 3：Precompute/Migration 脚本测试（4 个失败）

1. `test_migrate_chunk_store_to_jsonl.py::test_migration_script_converts_legacy_chunk_store`
2. `test_precompute_contextual.py::test_precompute_contextual_summaries_writes_three_artifacts`
3. `test_precompute_contextual.py::test_precompute_contextual_summaries_skips_existing_artifacts_on_repeat_run`
4. `test_precompute_contextual.py::test_precompute_contextual_summaries_dry_run_respects_limit`

**根因分析：**
- 预计算脚本的文件 I/O 或路径问题
- 可能与工作区状态或临时文件清理相关

**优先级：** 中（脚本测试，不影响运行时）

### 桶 4：Pipeline 可观测性/CLI 测试（2 个失败）

1. `test_pipeline_observability.py::test_pipeline_triggers_observer`
2. `test_integrated_pipeline_cli_help.py::test_integrated_pipeline_help_stays_side_effect_free`

**根因分析：**
- 观察者触发逻辑失败
- CLI help 命令有副作用

**优先级：** 低（可观测性和 CLI，不影响核心功能）

### 桶 5：Reranker 测试（3 个失败）

1. `test_reranker.py::test_rerank_async_reuses_async_client_within_same_event_loop`
2. `test_reranker.py::test_rerank_async_truncates_oversized_documents`
3. `test_reranker.py::test_rerank_async_applies_provider_rate_limit_before_http`

**根因分析：**
- Async client 复用逻辑失败
- 文档截断逻辑失败
- 速率限制逻辑失败
- 可能与 async/await 测试隔离或 mock 相关

**优先级：** 高（reranker 是核心功能）

### 桶 6：编码问题测试（1 个失败）

1. `test_rag_pipeline_ascii_only.py::test_pipeline_؞ͨ_ascii`
   - **错误：** JSON 编码问题
   - **根因：** 非 ASCII 字符处理失败

**优先级：** 中（边缘情况，但可能影响国际化）

### 桶 7：LLM API Mock 问题（1 个失败）

**特征：** 错误日志显示 `LLM API failed: <MagicMock ...>`

- 影响 `test_pipeline_router_association.py` 中的多个测试
- 根因：LLM API mock 配置不正确

**优先级：** 高（影响多个测试）

## 优先级排序

### P0（立即修复）：
1. **Contextual Chunker**（2 个失败）— 影响核心分块功能
2. **Reranker**（3 个失败）— 影响核心检索功能
3. **LLM API Mock**（影响多个测试）— 测试基础设施问题

### P1（本周修复）：
1. **legacy_root 数据库连接**（1 个失败）— 测试隔离问题
2. **legacy_root 路由/关联逻辑**（8 个失败）— 可能影响 API 行为

### P2（下周修复）：
1. **Precompute/Migration 脚本**（4 个失败）— 脚本测试
2. **Pipeline 可观测性/CLI**（2 个失败）— 非核心功能
3. **编码问题**（1 个失败）— 边缘情况

## 修复策略

### 短期（今天）：
1. 修复 Contextual Chunker 的 `assert False` 问题
2. 修复 Reranker async client 复用逻辑
3. 修复 LLM API mock 配置

### 中期（本周）：
1. 修复 legacy_root 数据库连接隔离
2. 审查 pipeline_router_association 的 LLM mock 依赖
3. 修复 resources_router 搜索去重逻辑

### 长期（下周）：
1. 重构 precompute/migration 脚本测试的文件 I/O
2. 改进 pipeline 可观测性测试的隔离
3. 添加非 ASCII 字符的编码测试覆盖

## 进展跟踪

- **初始状态：** 59 失败（2026-05-03 早期）
- **当前状态：** 22 失败（2026-05-03 16:30）
- **改进：** -62.7%
- **目标：** <10 失败（本周末）

## 下一步行动

1. 创建 P0 修复任务（Contextual Chunker + Reranker + LLM Mock）
2. 分配给 Trinity（实现修复）
3. 分配给 Tank（验证修复后的测试通过）
4. 更新 DECISION_TRAIL 和 OPEN_THREADS
