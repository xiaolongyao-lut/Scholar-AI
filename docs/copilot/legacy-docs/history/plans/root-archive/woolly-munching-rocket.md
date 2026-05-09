# Plan: token-aware embedding/rerank guard + Qwen3 召回模型切换

## Context

Canary 复测(30 条分层 v2.1)触发深层 bug:
- `output/chunk_store/*.json` 里 73 个 chunks > 12k chars(最长 35588),单条超过 SiliconFlow `/embeddings` 8192-token 上限 → 413。
- `chunk_vector_store.py:_batch_embed` 在 413 时**整批回填零向量**(:174,:177),导致 `output/embedding_cache/corpus_embeddings_contextual.npy` 里 **885/6293 行全零**(14% 污染),smoke 工具目前只校验 manifest 哈希,对零向量无感知。
- canary 30q 结果 Recall@5=0.0667,且 rerank 三次 retry 全失败,根因是污染的索引 + 长文档 rerank 拒收,不是 translated-first 链路。

同步用户要求切换召回/重排模型(具体 key 与 endpoint 由用户的本地 `.env` 提供,本计划只涉及变量名和默认值,不涉及真实值):
- Embedding: `Qwen/Qwen3-Embedding-8B`,通过 `dimensions=1024` 走 Matryoshka 截断,保持 `EMBEDDING_DIM=1024` 不动。
- Rerank: `Qwen/Qwen3-Reranker-8B`。
- ARK LLM endpoint 等:不改默认,沿用现有 env 变量名。

**目标**:修主干使索引/重排不再隐式退化,让 canary 在 Qwen3 召回模型下干净通过,再推进 full v2.1 + smoke 入 pytest + docs。保持 corpus 形状和 `EMBEDDING_DIM=1024`,避免下游 blast radius。

## 安全与执行约束(本 plan 的硬约束)

1. **计划、代码、commit message、`.env.example` 里不出现任何真实 API key**。全部写成占位符(如 `your_siliconflow_api_key_here`),并通过 `os.getenv(...)` 读本地 `.env`(.env 在 `.gitignore`,本地用户手动维护)。
2. 不 bypass permissions;本轮采用 **manually approve edits** 流程。
3. 本 plan **不自动修改用户的 `.env`**。只在代码里调整默认 model 名(把 `BAAI/bge-m3` 默认改为 `Qwen/Qwen3-Embedding-8B`),真实 key 切换由用户手工完成。
4. 先提交代码 + 测试改动(不含真实值),再跑 canary/full eval,最后补 docs。

## 改动范围(精简)

### 改动 1 — 新文件 `token_utils.py`

`count_tokens(text) -> int`、`truncate_to_tokens(text, max_tokens) -> str`、`split_by_tokens(text, max_tokens) -> list[str]`。
- 懒加载 `transformers.AutoTokenizer.from_pretrained("BAAI/bge-m3")`(XLM-R 族,对中文估算偏紧,对 Qwen3 作为保守近似安全)。
- 离线/加载失败时 fallback:`len(text) * 0.75`(CJK 实测比例)作为 token 估算。
- `split_by_tokens`:优先按 `\n\n` 段落切,再按中英句末符号 `。！？.!?` 切,最后按定长 token 窗口切,保证每片 ≤ `max_tokens`。

### 改动 2 — `chunk_vector_store.py`

- 引入 `from token_utils import count_tokens, split_by_tokens`。
- 新增常量 `SAFE_EMBED_TOKENS = 7500`(8192 留 buffer)。
- `_batch_embed` 重写:
  - **预检**:逐条 text 计算 token。超过 SAFE_EMBED_TOKENS 的条目走 split+mean-pool 分支;其它正常 batch。
  - **split+mean-pool**:
    - `pieces = split_by_tokens(text, SAFE_EMBED_TOKENS)`
    - 对 pieces 逐批调 API,得 sub-vectors → L2 归一 → `np.mean(axis=0)` → 再 L2 归一 → 单个 vector,放回原 slot。
    - 日志:`embed: chunk #i %d tokens split into %d pieces`。
  - **请求体**:添加 `"dimensions": EMBEDDING_DIM`(bge-m3 忽略未知字段,Qwen3-Embedding-8B 返回 1024 维)。
  - **去零向量 fallback**:
    - 200:正常。
    - 413 / 400 input-too-long:raise `RuntimeError`(说明 "after split guard 仍超长,排查 token_utils 的切分逻辑或 max 阈值";正常流程永远不会到这里)。
    - 429 / 5xx:指数退避重试(最多 3 次),仍失败 raise。
    - 连接/超时异常:重试;仍失败 raise。
  - **空串**:仍用 "empty" placeholder(保留原 :149 行为)。
- `ChunkVectorStore.build`:
  - API 拿到 `embeddings` 后计算 `zero_rows = int(np.sum((embeddings == 0).all(axis=1)))`。
  - 若 `resolved_key` 存在且 `zero_rows > 0`:raise `ValueError`("embedding build produced %d all-zero rows — poisoned, aborting")。
  - manifest 追加 `"zero_row_count": 0`(observability;校验为非负 int,不作硬断言,保留向后兼容)。
- `DEFAULT_MODEL`:从 `"BAAI/bge-m3"` 改为 `"Qwen/Qwen3-Embedding-8B"`。`EMBEDDING_DIM` 保持 1024 不动。

### 改动 3 — `reranker_client.py`

- 引入 `from token_utils import count_tokens, truncate_to_tokens`。
- 新增常量 `SAFE_RERANK_DOC_TOKENS = 7500`。
- `rerank_async` 中,`documents = [_extract_document(item) for item in candidates]` 之后增加一步:
  - 对每个 doc 计 token。超长则 `truncate_to_tokens(doc, SAFE_RERANK_DOC_TOKENS)`(头部截断,保留语义主体)。
  - 日志:`rerank: truncated doc #i from %d to %d tokens`。
- rerank 不做 split(单元语义不可拆),截断是合理妥协。
- `DEFAULT_RERANKER_MODEL` 保持 `"Qwen/Qwen3-Reranker-8B"` 不动。

### 改动 4 — `smoke_cache_guard.py`

扩 2 个 case,保留原 4 个(miss/hit/tamper/rerank):
- `case_oversize`:构造 5 个 chunks,其中 1 个文本 `"激光焊接" * 5000`(>8192 tokens)。`ChunkVectorStore.build` 应正常产出 `.npy` + manifest,**无 413 raise**;对应行 embedding 非零,`store.has_embeddings=True`。
- `case_no_zero_rows`:紧跟 oversize 的产物,`np.load(cache_npy)`,断言 `not (arr == 0).all(axis=1).any()`。

CLI `--case` 新增 `oversize` / `no_zero_rows`。"all" 顺序:`miss → hit → tamper → oversize → no_zero_rows → rerank`。每轮 API 成本上限提升到 ~10 次 embed + 1 次 rerank。

### 改动 5 — `.env.example`

- 只改注释里提到的默认模型名(`BAAI/bge-m3` → `Qwen/Qwen3-Embedding-8B`),占位符保留 `your_xxx_here` 形式。
- 不含任何真实 key。

### 改动 6 — 新 `tests/test_token_utils.py`

- `test_count_tokens_empty`
- `test_count_tokens_short_cjk`
- `test_split_by_tokens_under_limit_returns_one_piece`
- `test_split_by_tokens_over_limit_produces_all_fit`(断言每片 ≤ max 且拼回覆盖原文的主要内容)
- `test_truncate_to_tokens_respects_limit`

### 改动 7 — `tests/test_reranker.py`(小改)

在现有 mock-based 测试基础上追加一个 case:
- 准备一个 `"激光焊接" * 5000` 的 doc,mock 捕获 POST payload,断言 `payload["documents"][0]` 的 token 数 ≤ `SAFE_RERANK_DOC_TOKENS`。

### 改动 8 — `chunk_vector_store.py` 的 `EMBEDDING_DIM`

保持 1024。**不改** `tests/test_dense_rrf_retrieval.py`。

## 不做 / 留待后续

- **不动**用户本地 `.env`(由用户手动切换真实 key)。
- **不切**生产路径(`layers/r_layer_hybrid_retriever.py`、`main_rag_workflow.py`、`semantic_router.py`)的模型字符串显式默认;它们读同一 env `SILICONFLOW_EMBEDDING_MODEL`,若用户切了会被动跟进,但本 plan 不改这些文件。
- **不做** expand-corpus 方案(每 sub-chunk 独立成行);mean-pool 保形状,留作检索质量增强版。
- **不加** smoke 的 rerank/oversize case 进 pytest(需要真 API key);pytest 仍用现有 mock 测试,只新增 token_utils 与 rerank-truncate 断言。

## 关键文件清单

- `token_utils.py`(**新**)
- `chunk_vector_store.py`(:24 DEFAULT_MODEL、:135 `_batch_embed`、:209 `build`、:354 `_save_cache` 的 manifest)
- `reranker_client.py`(:60 `_extract_document` 后、:117-131 payload build 前)
- `smoke_cache_guard.py`(:177 `CASES` 字典、:214 `run` 默认顺序)
- `.env.example`(注释里默认模型名)
- `tests/test_token_utils.py`(**新**)
- `tests/test_reranker.py`(+1 case)

## 不触碰真实密钥的环节

- 所有改动都只通过 `os.getenv(...)` 读取密钥。
- 代码、测试、plan、commit message、`.env.example` 里**不出现真实 key**。
- canary / full eval 执行时,API key 只在运行进程的内存里,不 echo,不写入任何输出文件。
- 本地 `.env` 文件由用户手动维护,本 plan 不自动写入。

## 验证步骤

```bash
# ① 单元测试
pytest tests/test_token_utils.py tests/test_dense_rrf_retrieval.py \
       tests/test_reranker.py tests/test_eval_runtime.py \
       tests/test_query_expander.py -q

# ② smoke 6 case(需要真 key 在 .env,由用户切换后执行)
python smoke_cache_guard.py       # expect 6/6 PASS

# ③ 清缓存 + canary(需要 .env 已切到 Qwen3 + 新 key)
rm -f output/embedding_cache/corpus_embeddings*
python eval_retrieval_runtime.py \
  --queries eval_queries_v2.1_canary30.jsonl \
  --expansion --strict-cache-guard \
  --output BASELINE_METRICS_canary30.json
# 期望:日志无 413、无 "all-zero rows" raise、Recall@5 显著 > 0.0667

# ④ 全量
python eval_retrieval_runtime.py \
  --queries eval_queries_v2.1.jsonl \
  --expansion --strict-cache-guard \
  --output BASELINE_METRICS_phase5_qwen3.json

# ⑤ docs + commit + push(commit message 不含真实 key)
```

## 交付顺序

1. 先写代码 + 测试(token_utils、chunk_vector_store、reranker_client、smoke、.env.example、tests)。
2. 跑 `pytest` 三件套,过。
3. 把代码改动 commit(**不含** .env,也不含真实 key)。
4. 用户本地手动切 `.env`(真实 key + Qwen3 模型名)。
5. 清 cache → 跑 smoke → 跑 canary → 跑 full eval。
6. eval 产物(BASELINE_METRICS_*.json)commit。
7. 更新 `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md`,commit + push。

## 风险与回退

- Token 估算误差:XLM-R 对中文偏紧(≈ Qwen3 估算的上界),SAFE_EMBED_TOKENS=7500 留 buffer,**极小概率** split 后单片仍超。触发的话会 raise,不会静默污染 → 可观察 → 回退策略:把 SAFE_EMBED_TOKENS 降到 6000。
- Mean-pool 质量损失:对单一超长 chunk,mean-pool 相当于语义 blur。影响面:只作用于 73 条超长 chunks,其余 6220 条不变。全量 eval 可量化影响。
- `dimensions=1024` 被 Qwen3 API 拒收的可能性极低(Matryoshka 是 Qwen3 官方文档写明的特性);若出错,回退策略:把请求体 `dimensions` 字段拿掉,改用返回的原生 dim + 更新 `EMBEDDING_DIM`。
