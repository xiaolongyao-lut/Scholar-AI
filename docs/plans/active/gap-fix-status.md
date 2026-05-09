# 漏洞修复执行状态

## 当前状态

**测试失败数**：0 个（从 22 个降至 0 个，-100%）

**剩余失败**：无。`pytest tests -q` 已通过。

---

## 修复决策

### 决策 1：剩余 2 个失败已收口

**理由**：
1. legacy export 测试已改为 deterministic fixture，不再依赖迁移前 eval 路径或长耗时真实检索。
2. contextual validation miss 计数已恢复。
3. 测试失败率已从 22/1625 (1.35%) 降至 0。
4. 全量 `pytest tests -q` 已通过。

**影响**：
- 不影响 Wave 15 推进
- 不影响发布门禁
- LMWR-464 可标记完成

### 决策 2：优先推进 LMWR-465（TOLF 设计）

**理由**：
1. TOLF 功能已实现（最新 5 个 commit）
2. 缺少设计文档会影响 Wiki 集成
3. 是其他漏洞修复的前置条件

---

## 修复优先级调整

### 原计划
1. LMWR-464（测试修复）← 当前
2. LMWR-465（TOLF 设计）
3. LMWR-468（成本预估）
4. LMWR-472（安全审计）

### 调整后
1. ✅ LMWR-464（测试修复）← 已完成，0 failed
2. ✅ LMWR-465（TOLF 设计）
3. ✅ LMWR-466（前端 E2E）
4. ✅ LMWR-467（外部写回策略）
5. ✅ LMWR-468（成本预估）
6. ✅ LMWR-469（longrun 指南）
7. ✅ LMWR-470（分块参数 200/8 复盘）
8. ✅ LMWR-471（性能基线）
9. ✅ LMWR-472（本地安全门禁）
10. ✅ LMWR-473（Wiki 可观测性）

---

## 下一步行动

1. LMWR-470 已完成只读复盘；Post-LMWR-470 cache/corpus preflight 也已落地。当前 `laser_welding_109` v2 chunk-store 与 canonical/legacy embedding manifests 不对齐，下一步是定位 canary30 control 的真实 corpus source，而不是直接重跑 provider eval。
2. 保持 `pytest tests -q` 作为后续大切片的回归门禁。

---

## 最新补充完成项

### LMWR-466：前端 E2E 已收口

**完成内容**：
1. 复用现有 Playwright 框架，为 `WikiWorkbench` 增加最小关键工作流 E2E。
2. 修复 `frontend/tests/e2e/mockApi.ts` catch-all route 抢占 `/api/wiki/*` 的问题，改为 `route.fallback()`。
3. 将断言收紧到真实状态徽标、canonical path 与治理面数据，避免说明文案导致误报。

**验证**：
```text
npm run test:e2e -- tests/e2e/wiki-workbench.spec.ts --reporter=line
5 passed

npm run test -- --run src/services/wikiApi.test.ts
11 passed

npm run build
PASS
```

**证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-466-frontend-e2e.md`

### LMWR-472：本地安全门禁已收口

**完成内容**：
1. `wiki_router` 增加 filter token、identifier、page_path 输入校验，非法形状返回 400。
2. `wiki_status` 对 repo 外路径做 `<external>/<name>` 脱敏，避免前端暴露真实绝对路径。
3. `wiki_backup_plan` 收集文件时校验真实目标仍在声明 allowed root 内，越界文件不进入 zip。

**验证**：
```text
pytest tests/wiki/test_wiki_router.py tests/wiki/test_backup.py -q
19 passed, 1 skipped

python -m compileall -q literature_assistant/core/routers/wiki_router.py literature_assistant/core/wiki/backup.py tests/wiki/test_wiki_router.py tests/wiki/test_backup.py
PASS
```

**证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-472-security-audit.md`

### LMWR-473：Wiki 可观测性已收口

**完成内容**：
1. 新增 `wiki/observability.py`，提供本地事件、指标、span JSONL sink。
2. 新增 `wiki_observability_path()`，产物落在 `workspace_artifacts/runtime_state/wiki/observability/`。
3. `WikiQueryIndex`、`WikiCompiler`、`WikiDoctor` 支持注入 sink，默认路径不写观测产物。
4. 观测 payload 对 query/prompt/answer/text/path/api_key/token 等字段做 hash + length + reason 脱敏。

**验证**：
```text
pytest tests/wiki/test_observability.py tests/wiki/test_query.py tests/wiki/test_compiler.py tests/wiki/test_doctor.py -q
61 passed

python -m compileall -q literature_assistant/core/wiki tests/wiki/test_observability.py
PASS
```

**证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-473-observability.md`

### LMWR-470：分块参数复盘已收口

**完成内容**：
1. 新增 `tools/eval/wiki_lmwr470_chunk_param_review.py`，只读解析 canary30 历史 artifacts 与当前 chunk constants。
2. 新增 `tests/wiki/test_lmwr470_chunk_param_review.py`，覆盖指标相同、cache stale evidence 和 deterministic JSON 输出。
3. 生成 `workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json`，明确 `promote_200_8=false`。
4. 保留当前 `CHUNK_OVERLAP=150`、`MAX_CHUNKS_PER_MATERIAL=5`，不改 qrels/goldset/canary30。

**验证**：
```text
pytest tests/wiki/test_lmwr470_chunk_param_review.py -q
5 passed

pytest tests/wiki/test_lmwr470_chunk_param_review.py tests/wiki/test_performance_baseline.py -q
7 passed

python -m compileall -q tools/eval tests/wiki/test_lmwr470_chunk_param_review.py docs/plans
PASS
```

**证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-470-chunk-params-reevaluation.md`

### Post-LMWR-470：cache/corpus 预检已落地

**完成内容**：
1. 新增 `tools/eval/wiki_cache_corpus_preflight.py`，只读对比 corpus/chunk-store 与 embedding manifest。
2. 新增 `tests/wiki/test_cache_corpus_preflight.py`，覆盖 manifest PASS/FAIL、v2 chunk-store、路径逃逸、多 cache dir。
3. 生成 `workspace_artifacts/evaluations/post-lmwr-470-cache-corpus-preflight-laser-welding-109-20260505.json`。
4. 真实结果为 FAIL：`laser_welding_109` 当前 v2 chunk-store 是 `7225` chunks，现有 canonical/legacy manifests 是 `11470` / `2` / `11457` chunks。

**验证**：
```text
pytest tests/wiki/test_cache_corpus_preflight.py -q
8 passed

pytest tests/wiki/test_cache_corpus_preflight.py tests/wiki/test_lmwr470_chunk_param_review.py tests/wiki/test_performance_baseline.py -q
15 passed

python -m compileall -q tools/eval tests/wiki/test_cache_corpus_preflight.py tests/wiki/test_lmwr470_chunk_param_review.py docs/plans
PASS
```

**证据**：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md`

### Post-LMWR-470：canary corpus source locator / root hygiene 已落地

**完成内容**：
1. 新增 `tools/eval/wiki_canary_corpus_source_locator.py`，复刻 `eval_retrieval_runtime._load_retrieval_corpus()` 的 root 聚合语义，只读定位 canary runtime corpus。
2. 测试覆盖 v2 root 聚合、v2 优先于 legacy、runtime 顺序 hash、manifest 匹配/不匹配、同一 resolved root 去重。
3. 生成 `workspace_artifacts/evaluations/post-lmwr-470-canary-corpus-source-locator-20260505.json`。
4. 初始结果为 `REPAIR_CANDIDATE`：canary 默认 root 是 `output/chunk_store`，该路径为 junction，实际解析到 `workspace_artifacts/generated/output/chunk_store`；runtime corpus 是 `11471` chunks / hash `76f661a741bbc5b7cc69dfab34b3cdd99cba8744691111403874b9fee162bc6a`。
5. 定位精确残留：排除 1-chunk v2 project `proj_f9adfb165de1` 后，projected corpus 为 `11470` / hash `58c76986fdfa125d9e690ad00dfa990b72b2a6b41a564405280d8613a012ddf0`，精确匹配 canonical contextual manifest。
6. 已按授权先备份再清理：备份和 journal 位于 `workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/`；清理后 locator status 为 `PASS`。

**验证**：
```text
pytest tests/wiki/test_cache_corpus_preflight.py -q
14 passed
```

**证据**：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md`

---

## 验证结果

```
pytest tests -q
1632 passed, 3 skipped in 197.96s

pytest tests/legacy_root/test_gateb_c6_repro.py tests/test_validate_contextual_miss.py -q
5 passed
```

**结论**：测试基础设施已收口，后续补充任务可用全量 pytest 作为回归门禁。
