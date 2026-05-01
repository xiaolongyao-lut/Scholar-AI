# Embedding + Rerank 测试任务清单 — 可外包执行

> **目的**：把嵌入 / 重排序相关、**独立可交付**的测试任务打包给外部 AI 执行。清单里每一项都给了：输入文件、预期行为、验收命令、回滚按钮。
>
> **给执行 AI 的硬规矩**：
> 1. 不要改业务实现，除非某一项里显式说"实现并测"。
> 2. 每项写完先 `git diff --stat` 让用户看增改文件面积。
> 3. 全部写完后**只报告测试命令 + pass 数**，别自我表扬。
> 4. 遵循 CLAUDE.md §2 "Simplicity First" / §3 "Surgical Changes"。
> 5. 不在仓库里生产新 README / 新计划文件，除非下方明确要求。

---

## 上下文概览（10 秒读完）

- 仓库：`Modular-Pipeline-Script`（FastAPI + retrieval + rerank pipeline）
- 相关模块：
- `reranker_client.py` — SiliconFlow / DashScope rerank 封装（含 validity-first key probe）
  - `rerank_cache.py` / `rerank_logic_cache.py` / `rerank_budget.py` — cache + budget gating
  - `layers/ai_adapter.py` — 统一 chat/embedding 出口
- 现有测试：`tests/test_rerank_budget.py`, `tests/test_rerank_cache_mode.py`, `tests/test_rerank_short_circuit_and_budget.py`, `tests/test_reranker.py`
- 约束：Python 3.12+、pytest 9.x、`pytest-asyncio` mode=auto、Windows path 要兼容
- 跑测试：`python -m pytest tests/<file>.py -v`

---

## 任务 E1 — Embedding provider switch 回归

**动机**：`.env` 里存在多组 embedding/rerank 凭证与重复的裸 `API_KEY` / `BASE_URL` / `MODEL` 条目。历史问题是凭证与 endpoint/type 配对不稳，导致错误路由与 401；embedding 这一侧需要专门 regression 来锁定当前解析合同。

**要做**：新建 `tests/test_embedding_provider_resolution.py`，4 个 case：

1. `test_siliconflow_key_resolves_embedding_endpoint` — 只设 `SILICONFLOW_API_KEY`，调用 embedding 入口（看代码里叫什么），实际 HTTP 目标应是 SiliconFlow embedding URL，payload 中 auth header 带的 key 正确。
2. `test_jina_only_falls_through_to_jina` — 只设 `JINA_API_KEY`，不设 SiliconFlow，应走 Jina。
3. `test_both_present_prefers_siliconflow_unless_overridden` — 两个都设，默认优先级 = SiliconFlow；设 `EMBEDDING_PROVIDER=jina` 时走 Jina。
4. `test_no_key_returns_none_api_key_contract` — 都没设时保持当前 resolver 合同：`api_key is None`，由调用方决定 fail closed / degrade / skip。

**实现提示**：
- 用 `monkeypatch.setenv` / `delenv` 控制环境；**不要真正发 HTTP**，用 `responses` 或 `httpx_mock` 或 `unittest.mock.patch` 拦截。
- 先在仓库 grep：`grep -rn "get_embedding\|embedding_provider\|EMBEDDING_PROVIDER" --include="*.py"` 找到解析入口。如果没有明确 resolver（只是散落在各处），**不要重构**，改做：`pytest.skip("no central embedding resolver yet — see TODO-E1")` 并在报告里写上这一项 skipped 的原因。

**验收**：`python -m pytest tests/test_embedding_provider_resolution.py -v` — 4 pass 或 4 skip（附理由）。

**回滚**：删文件即可。

---

## 任务 E2 — Embedding 批处理边界

**动机**：provider 通常有单次 batch 上限（如 SiliconFlow ≤ 64 / Jina ≤ 2048）。当前代码是否在超限时自动切块？需要可验证行为，否则生产跑大 corpus 会静默吞 401 或 413。

**要做**：新建 `tests/test_embedding_batch_chunking.py`：

1. `test_under_limit_single_request` — 10 个文本一次请求。断言 HTTP mock 收到 1 次调用。
2. `test_over_limit_auto_chunks` — 200 个文本（假设 limit=64），应发 4 次请求（64+64+64+8）。
3. `test_provider_limit_is_configurable` — 设 `EMBEDDING_BATCH_SIZE=32`，200 文本应发 7 次。
4. `test_empty_input_returns_empty_without_request` — 空列表 → 0 次请求 → 返回 `[]`。

**实现提示**：
- 如果代码里没有 `EMBEDDING_BATCH_SIZE`、也没切块逻辑，这就是**发现的 gap**：写红测试、在报告里列 "gap found — needs impl"，**不要**顺手实现。
- 2026-04-26 实际仓库状态：`batch_size` 参数可配置已被测试锁定；`EMBEDDING_BATCH_SIZE` 在默认批处理路径已接线，且显式 `batch_size` 参数优先级更高。

**验收**：5 pass（或列出 skipped + gap）。

---

## 任务 R1 — Rerank validity-first probe 回归（补强）

**动机**：`reranker_client.py:71-213` 的 `_probe_rerank_key` + `resolve_rerank_config` 已经落地（见 A1 close）。`tests/test_reranker.py` 可能已有覆盖，但关键 regression 仍应锁定：当 probe 判定首个 env key 不适配当前 rerank endpoint 时，resolver 是否真的前进到下一个有效候选，而不是返回被拒 key。

**要做**：读 `tests/test_reranker.py`，看已有 case 清单。**只补**下面这些没被覆盖的：

1. `test_probe_reject_falls_back_to_alternate_provider_key` — mock probe 对首个 SiliconFlow key 返回 invalid，对后续候选 key 返回 valid；`resolve_rerank_config()` 应返回后续有效 key。
2. `test_probe_disable_env_skips_probe` — `RERANK_KEY_PROBE_DISABLE=1` 时，无论 key 有效性如何，走旧静态顺序；用一个"会被 probe 拒掉"的 key 验证它这次**不会**被拒。
3. `test_all_keys_invalid_warn_and_fallback` — 所有 probe 都 invalid 时，锁定当前语义：发出 loud warning，并回退到静态顺序的首个候选 key。

**实现提示**：
- 先 `pytest tests/test_reranker.py --collect-only` 列出已有 case。已覆盖就 skip 别写重复。
- 用 `unittest.mock.patch` 打 `_probe_rerank_key`。

**验收**：新增 case 全 pass；旧 case 0 回归。

---

## 任务 R2 — Rerank cache key 不变性

**动机**：`rerank_cache.py` / `rerank_logic_cache.py` 的 cache key 如果随 dict 顺序 / JSON 序列化细节变，cache 会静默 miss，前面 §3.3 评测的 warm cache 结论就不可信。

**要做**：新建 `tests/test_rerank_cache_key_stability.py`：

1. `test_same_query_same_candidates_same_key` — 同 query / 同 doc list 两次调 cache key 函数，输出相等。
2. `test_candidate_order_should_not_change_key_if_dedup_on` — 如果 cache 文档上写了 "对 candidates 排序后 hash"，那 `[d1, d2]` 和 `[d2, d1]` 应该同 key；否则这个 case 写成 `test_candidate_order_changes_key_documented_behavior` 并在 docstring 明文记住当前行为。
3. `test_different_model_name_different_key` — `model="bge-rerank-v2-m3"` 和 `"jina-reranker-v2"` 必须不同 key。
4. `test_top_n_changes_key_or_not_documented` — 同理，写测试钉死当前语义。

**实现提示**：
- 先读 `rerank_cache.py` 里 cache key 生成函数（可能叫 `_make_key` / `_cache_key` / `hash_*`）。**测当前行为**，不要改它。
- 这组 test 是"锁定语义"，发现奇怪的设计就写 docstring 吐槽但不改代码。

**验收**：全 pass（可能都是 documentation-locking tests）。

---

## 任务 R3 — Rerank budget 并发安全

**动机**：`rerank_budget.py` 如果在多协程同时扣额度时有 race，budget 可能溢出。

**要做**：新建 `tests/test_rerank_budget_concurrency.py`：

1. `test_concurrent_decrement_never_goes_negative` — 设 budget=10，开 100 个 asyncio task 每个 `-1`，最终 budget 不应小于 0，且用户代码里预期的 "超出则抛" 行为应被观察到 ≥ 90 次。
2. `test_concurrent_reset_is_atomic` — 一边扣一边 reset，reset 后读到的值应 = reset 值或扣后值，绝不是中间态。

**实现提示**：
- 用 `pytest-asyncio` + `asyncio.gather`。
- 如果 `rerank_budget.py` 根本不是线程安全设计（比如就是个 int + 无 lock），**不要加 lock**，写红测试并在报告里挂 "gap found — see concurrency test"。

**验收**：2 pass 或 2 xfail（附 `reason=` 指向源文件行号）。

---

## 任务 R4 — Rerank short-circuit path 边界

**动机**：`test_rerank_short_circuit_and_budget.py` 已存在，但可能没覆盖下面这些边界：

**要做**：读已有 case，**只补**：

1. `test_empty_candidates_returns_empty_without_calling_provider` — 空 list 输入，provider mock 的调用次数应是 0。
2. `test_single_candidate_short_circuits` — 1 个 doc 直接返回，不发请求。
3. `test_top_n_larger_than_candidates` — 请求 top_n=20 但只有 5 个 doc，结果长度 = 5。
4. `test_negative_or_zero_top_n_raises` — top_n ≤ 0 时明确抛 ValueError。

**验收**：新增 case 全 pass；旧 case 0 回归。

---

## 任务 R5 — 端到端 retrieval → rerank 烟雾测试（可选，大件）

**动机**：§3.3 评测用的是离线 metrics，`test_reranker.py` 是单元级。缺一个**打通** retrieval → rerank → 返回 top_k 的最小 happy-path。

**要做**：新建 `tests/test_retrieve_then_rerank_smoke.py`，1-2 个 case 就够：

1. `test_happy_path_small_corpus` — mock 一个 5 文档的 corpus，mock embedding provider 返回固定向量，mock rerank provider 返回固定得分，断言最终 top_3 顺序稳定。

**实现提示**：
- **不要**真的连 FAISS / Chroma / remote API；都 mock。
- 如果发现没有一个清晰的 "retrieve_then_rerank(query, corpus, top_k)" 入口，**跳过该项**并在报告里写 "no single entrypoint — see router X / adapter Y"。

**验收**：1 pass 或 1 skipped + 理由。

---

## 交付格式（给外包 AI 的报告模板）

```
# Embedding + Rerank 测试交付报告

## 完成项
- [x] E1 — 已关闭（含 no-key 行为：`resolve_embedding_config()` 返回 `api_key=None`）
- [x] E2 — 5 pass（`batch_size` 参数合同保持不变，`EMBEDDING_BATCH_SIZE` 默认路径已接线）
- [x] R1 / R2 / R3 / R4 — 当前回归已覆盖并保持绿色
- [ ] R5 — 1 skipped（缺单一 `retrieve_then_rerank(...)` 入口）
...

## 发现的 gap（不要擅自修）
- R5: 仍无单一 `retrieve_then_rerank(query, corpus, top_k)` 入口；烟雾测试以 skip 锁定当前缺口。

## 验收命令
python -m pytest tests/test_embedding_provider_resolution.py tests/test_embedding_batch_chunking.py tests/test_reranker.py tests/test_rerank_cache_key_stability.py tests/test_rerank_budget_concurrency.py tests/test_rerank_short_circuit_and_budget.py tests/test_retrieve_then_rerank_smoke.py -v

## git diff --stat
(paste here)
```

---

## 明确拒绝（out of scope）

- ❌ 修 embedding/rerank 业务代码（只测当前行为）
- ❌ 引入新 provider（Cohere v3 等）
- ❌ 改 cache/budget 数据结构
- ❌ 跑真实 HTTP（只允许 mock）
- ❌ 接入 CI / GitHub Actions

---

**Created**: 2026-04-25 (Claude, Squad 4.7 — 用户休息期间的外包清单)
**Spec 锚点**：`OPEN_THREADS.md A1 / A2`, `.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md`
**Status**: 已在仓库内执行并完成该轮收敛：E1 已关闭并锁定 no-key=`api_key=None` 合同；E2 已翻绿，当前为“`batch_size` 参数合同已锁定 + `EMBEDDING_BATCH_SIZE` 在默认 embedding batch 路径生效”；R1 已补 all-invalid probe fallback 语义回归，且 R2/R3/R4 当前均为绿色；R5 已由 RED 翻绿，`eval_retrieval_runtime.py` 现已公开 `retrieve_then_rerank(...)` 薄包装层；embedding probe 已补 schema-aware 校验，`200 + HTML`/非 embedding JSON 不再被当成健康；`key_pool.parse_env_pools()` 已识别 `SILICONFLOW_EMBEDDING_*` typed 变量并保持 typed flow 优先。

Facts:
- Focused verification `py -m pytest tests\test_embedding_batch_chunking.py -q` → `5 passed`.
- Focused verification `py -m pytest tests\test_embedding_key_probe.py tests\test_key_pool.py tests\test_retrieve_then_rerank_smoke.py tests\test_embedding_provider_resolution.py tests\test_dense_rrf_retrieval.py -q` → `42 passed`.
- Live smoke（本地 `.env`）已通过：`resolve_embedding_config(...)` 现能解析出 text embedding 目录，且 `ChunkVectorStore.build()` 单条 text embedding 成功返回 `has_embeddings=true`。
Decisions:
- 关闭 E2：`EMBEDDING_BATCH_SIZE` 仅在未显式传入 `batch_size` 时作为默认值生效，保留显式参数路径优先级。
- 关闭 R5 / embedding probe schema / key_pool typed-key 三个收尾项，并保持改动面限制在 `runtime_env.py`、`key_pool.py`、`chunk_vector_store.py`、`eval_retrieval_runtime.py` 与对应测试。
Open:
- 仅剩后续 runtime gate：需要基于已恢复的本地 `.env` embedding 路径，继续做 Phase 5/6、§3.3、§3.6 的 cache rebuild / canary / live rerun 验收。
Next:
- 回到阻塞项：继续 cost-and-defaults §3.3 / §3.6 与 advanced-retrieval Phase 5 / 6 的 cache rebuild / canary / live gate closure。
