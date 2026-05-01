# Modular-Pipeline-Script 检索优化方案

## Context

**项目状态速览**（基于 2026-04-17 执行计划文档 + 代码审阅）：

- **Tier 1 (Phase 0–3)**：已提交（1403057）。BM25 + Graph + Dense(BGE-m3) 三路 RRF。
- **Tier 2 Phase 4 / 4.1 (Reranker + 并发重试)**：已提交（f48be75, b6ccdd2）。
- **Tier 2 Phase 5 (查询扩展)**：代码已写但**未提交**，全量 414q eval **负收益**（0.2899 vs 0.3043）。
- **Tier 2 Phase 6 (上下文切块)**：代码已写但**未提交**，30q 抽样 **负收益**（0.3667 vs 0.4000）。

**真实基线**（`BASELINE_METRICS_phase5_no_expansion.json`，414 queries）：

| 指标 | 当前 | 目标 | 缺口 |
|------|------|------|------|
| Recall@5 | 0.3043 | ≥0.45 | +48% |
| MRR | 0.1753 | ≥0.30 | +71% |

**`BASELINE_METRICS.json` 全零不是回归**：100 queries + latency=20s 说明检索正常执行。根因是用了默认 `eval_queries_v1.0.jsonl`——该文件所有 `doc_id="baseline_v1"`，是 mock 数据，与真实 chunk_store 对不上，命中判定永远 false。v2.0 才是对齐后的 414 查询评测集。

## 根因诊断

### Bug 1：Phase 5 `_retrieve_with_expansion` 把英文 query 错送给 BM25/Graph

`eval_retrieval_runtime.py:272-284` 把 `primary_query`（翻译后英文）传给所有 3 路召回。但 `layers/r_layer_hybrid_retriever.py:27-32` 的 BM25 把中英文 token 分开统计（`en_tokens` 只抓 `[A-Za-z]+`，`cn_tokens` 只抓 `[\u4e00-\u9fff]{2,}`）——**英文 query 对中文 chunk 的 BM25 得分几乎为 0**。同理 `graph_keyword_retriever` 走关键词匹配，英文 query 也匹不到中文节点。

结果：RRF 的 3 路里 BM25 + Graph 两路退化，只剩 dense 有效，融合后反而弱于不翻译时的 3 路。

### Bug 2：Phase 6 `reranker_client._extract_document` 读取被污染的 content

`reranker_client.py:22-32` 优先读 `content`，但 Phase 6 在 `content` 前加了 200+ 字中文摘要前缀（`contextual_chunker.py:170`），`raw_content` 才是无前缀原文。Qwen3-Reranker-8B 看到的是 "[摘要]\n原文"，关键信息被稀释，MRR 下降。

### 调参残留

`eval_retrieval_runtime.py:46-47`：`DEFAULT_RECALL_TOP_N=50 / DEFAULT_RERANK_TOP_N=20`。计划文档注释里已经写了："若召回不足则 50→80/100，MRR 不足则 20→30/40"——当前就属于这种状态。

### 默认文件隐患

`eval_retrieval_runtime.py:478`：`--queries` 默认 `eval_queries_v1.0.jsonl`（mock），应改成 `eval_queries_v2.0.jsonl`（对齐真实 corpus）。

## 修改方案

### 文件 1：`reranker_client.py`

`_extract_document`（line 22-32）字段优先级改：`raw_content > content > claim > text > source_text`。

这样 Phase 6 开启时 rerank 自然用无前缀原文；关闭时原 chunk 没有 raw_content 字段退回 content，行为不变。

### 文件 2：`eval_retrieval_runtime.py`

**2a. `_retrieve_with_expansion` 分路路由**（line 217-293）：
- BM25 + Graph：**用原中文 query**
- Dense：**用英文翻译 query + 对应 embedding**
- Rerank：**用原中文 query**（Qwen3-Reranker 跨语言能力可靠）

实现：让 `_retrieve()` 同时接 `bm25_query` / `graph_query` / `dense_query_vec` 三个输入（或让 `_retrieve_with_expansion` 直接手写合并 3 路），不再一个 primary_query 打全场。

**2b. 默认调参**（line 45-49）：
- `DEFAULT_RECALL_TOP_N`: 50 → 100
- `DEFAULT_RERANK_TOP_N`: 20 → 40
- `DEFAULT_USE_EXPANSION`: False → True（修好 2a 再开）

**2c. 默认 query 文件**（line 478）：
- `eval_queries_v1.0.jsonl` → `eval_queries_v2.0.jsonl`

### 不动的部分

- `contextual_chunker.py`：保持现状。先让 Phase 5 达标，**Phase 6 暂不默认开启**，`--contextual` 仍可手动测试。
- `chunk_vector_store.py`：当前上下文缓存切换逻辑（`_resolve_effective_cache_path`）是对的，无需改。
- `layers/r_layer_hybrid_retriever.py`：不改 BM25 分词。分词行为是 hybrid_search 正确的 Chinese-aware 实现，要支持英文 query 命中中文 chunk 应该靠 dense 分路，不应改 BM25。

## 验证计划

执行顺序（每一步都要通过才能下一步）：

1. **单元测试**：`pytest tests/test_reranker.py tests/test_eval_runtime.py tests/test_query_expander.py tests/test_contextual_chunker.py -q`  — 预期全通过（26+ passed）。

2. **A/B 快测（20–30 queries）**：先用 `--queries eval_queries_v2.0.jsonl` 小子集跑：
   - `--no-expansion` (对照组，应接近 0.30)
   - `--expansion`（修好后，目标 ≥0.35）
   - 若 `--expansion` 小子集就回退，立即排查分路接线。

3. **全量 414q**：`python eval_retrieval_runtime.py --queries eval_queries_v2.0.jsonl --expansion`
   - 预期：Recall@5 ≥ 0.40, MRR ≥ 0.25。
   - 若达到则覆盖 `BASELINE_METRICS.json`，这条是 Phase 5 门禁（0.40）的候选。

4. **（视 3 结果）Phase 6 再测**：若 Phase 5 达标且还差 MRR，加 `--contextual` 跑 A/B，观察 Phase 6 在 rerank 用 `raw_content` 后的真实收益。

5. **提交（分 2 次）**：
   - `fix(rerank): prefer raw_content to avoid contextual prefix pollution`
   - `feat(query): Phase 5 translated-first with split-routing + tuned top-n defaults`

## 关键文件清单

| 路径 | 改动类型 | 大概行数 |
|------|---------|---------|
| `reranker_client.py` | 改 `_extract_document` 字段优先级 | +3 行 |
| `eval_retrieval_runtime.py` | 重写 `_retrieve_with_expansion` 分路 + 调 defaults + 改 --queries 默认 | ~40 行 |

## 不会做的事

- 不动 `layers/r_layer_hybrid_retriever.py` 的 BM25/分词逻辑
- 不默认开启 `--contextual`（等 Phase 5 先达标）
- 不删除 `eval_queries_v1.0.jsonl`（保留兼容，仅改默认）
- 不碰前端或 routers（与本次检索优化无关）
- 不 force push / amend 已提交的 Phase 4 commits
