# Phase 4.2 修复笔记 + 下阶段成熟方案参考

## 本次已提交（commit 6a3a644）

| 变更 | 文件 | 作用 |
|---|---|---|
| `DEFAULT_USE_EXPANSION=False` | `eval_retrieval_runtime.py:57` | expansion v2 split-routing 实测 -12%（0.3043 → 0.2657），默认关闭 |
| `query_gate = asyncio.Semaphore(query_concurrency)` | `_run_eval_async` | 消除 gather 414 协程一次性挤 rerank_semaphore 造成的排队污染 |
| `rerank_api_p95_ms` / `rerank_queue_p95_ms` | `aggregate_metrics` | 把纯 API round-trip 和信号量等待时间分开 |
| `timings` 参数 | `rerank_async` | 调用方传 dict 收集 `queue_wait_ms` / `api_ms` / `attempts` |
| dotenv 自动加载 | 脚本顶部 | 免 source .env |

**验证结论**（BASELINE_METRICS_phase42_rerank_no_exp.json, n=414）：
- `Queue-p95 = 0.01 ms` ← 排队污染已吸收
- `API-p95 = 15 567 ms` ← 高是因为 TPM 429 被当成 fatal 错误落到 fallback，不是真 API 卡
- `R@5 = 0.0097` ← corpus 漂移 + TPM 429 双重污染，**不是检索退化**（见下）

## 当前阻塞问题

### 1. Corpus 与 embedding cache 不同步（最致命）

| 项 | 04-16（0.30 R@5 时） | 04-18（现在） |
|---|---|---|
| `output/chunk_store/` 总 chunks | 1656 | **6293**（04-17 22:02 新增 laser_welding_109/30） |
| `corpus_embeddings.npy` | 1656 × 1024 | 1656 × 1024（**未同步**） |
| `corpus_embeddings_contextual.npy` | n/a | 6293 × 1024（04-18 01:10 一次 `--contextual` 跑产出） |
| v2.0 queries 设计时针对 | 1656 chunks | 仍是 1656（每 doc 20 题 × 21 doc = 414） |

当前 `ChunkVectorStore.build` 的缓存判定只比 `cached.shape[0] == n`，不一致就**静默**走 API 重算全部 6293 条（遇 TPM 又会失败），行为很诡异。

### 2. 评测链路缺硬门禁

chunks 数量/hash 与 embedding cache 不一致时，应**直接 raise，不允许静默重算**。现在这个静默回退把"数据漂移"掩盖成"模型退化"。

### 3. 429 当前直接 fallback，不重试

`reranker_client.py:98-100`：`if response.status_code != 200: return _apply_fallback(...)`。对 429 完全不做退避，并发 8 × rerank_top_n 40 下稳定命中 SiliconFlow TPM 限额。

---

## 成熟方案参考（用户建议的调研方向）

### A. 429 / TPM 指数退避（reranker_client.py）

1. **先读 `Retry-After` 头**：`retry-after-ms`（非标，毫秒精度）→ `retry-after`（秒）→ `retry-after`（HTTP 日期）。如果 ≤60s 就直接 sleep 这个值。
2. **无头或超 60s 就自己算**：`delay = min(base * 2^attempt, max_delay=60)` + **full jitter**（`delay + random(0, delay*0.1)`），避免雷群。
3. **把 429 / 500 / 502 / 503 / 504 一起放进可重试清单**，当前代码只重试网络异常。
4. **上限 3-5 次**。
5. **客户端侧提前节流**（aiometer / 信号量 / `max_per_second`）比事后重试更省配额——配合 Step A 的 `query_gate`，把并发从 8 下调到 3 更稳。
6. `tenacity` 库提供成熟装饰器模式，可选用（不强制引入依赖的话，手写即可）。

参考：
- [AI API Error Handling: Fix 429 (2026)](https://ofox.ai/blog/ai-api-error-handling-troubleshooting-guide-2026/)
- [Claude API 429 Fix Guide](https://www.aifreeapi.com/en/posts/claude-api-429-error-fix)
- [Dealing with Rate Limiting Using Exponential Backoff](https://substack.thewebscraping.club/p/rate-limit-scraping-exponential-backoff)

### B. Embedding cache manifest / hash 校验（chunk_vector_store.py）

核心思路：别再靠 `shape[0] == n` 判断缓存有效。改成**内容哈希 + 版本清单**。

推荐 manifest schema（跟 cache 同目录放 `.manifest.json`）：

| 字段 | 作用 |
|---|---|
| `chunk_id` | 稳定 ID，用 `sha256(normalized_text)` |
| `content_hash` | 文本变化 → 触发重嵌（就这一条） |
| `embedding_model_id + version` | 换模型 → 全部失效 |
| `chunker_version + params` | 分块策略改 → 需重新分块和重嵌 |
| `source_doc_id + doc_version` | 源文档更新时定点 invalidate |

读缓存时对 manifest 做校验：chunk_ids 集合差异或 content_hash 变化 → **raise**（不是 silently 重算）。这就对应用户要的"硬门禁"。

参考：
- [Hidden Infrastructure of RAG — VersionedCache / SmartResultCache](https://ilovedevops.substack.com/p/the-hidden-infrastructure-of-rag)
- [Azure RAG Chunking — chunk ID 用哈希](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-chunking-phase)
- [Cascading Cache Invalidation — Philip Walton](https://philipwalton.com/articles/cascading-cache-invalidation/)

**Lazy vs Eager**：embedding cache 建议 lazy（读时核对 manifest），query-result cache 建议 eager（写时 purge 相关 doc_id）。我们当前只需要前者。

---

## 执行顺序（用户决定：4 → 2 → 3，1 最后）

- [x] **Step A-1**：快照当前修复（commit 6a3a644）
- [x] **Step A-2**：调研 429 退避 + embedding manifest（本文件）
- [ ] **Step B-1**：恢复 1656 chunks 快照，复测 Phase 4，验证 R@5 回到 ~0.30
- [ ] **Step B-2**：给 ChunkVectorStore + eval pipeline 加硬门禁（chunks↔embeddings 不一致 raise）
- [ ] **Step C**：构建 v2.1 queries 匹配 laser_welding_* 新语料
- [ ] **Step D**：v2.1 就位后重算 6293 embedding，跑 Phase 4/5/6 A/B
- [ ] **并行**：rerank 429 指数退避 + 默认并发从 8 下调到 3
