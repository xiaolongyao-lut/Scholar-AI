# Query Expansion 延迟优化方案

> 创建时间：2026-05-03  
> 目标：将扩展检索延迟从 10.4秒 降低到 8秒以内  
> 当前状态：baseline 1.3秒，expansion 10.4秒（8.1倍）

## 当前架构分析

### 延迟来源拆解

根据 `eval_retrieval_runtime.py` 和 `query_expander.py` 分析：

1. **翻译阶段**（~2-3秒）
   - `translate_query_async()` 调用 ARK API
   - 已有缓存：`gated_call` with `cache_key_parts`
   - 并发控制：`ARK_EXPANSION_CONCURRENCY=5`

2. **重嵌入阶段**（~2-3秒）
   - 翻译后的英文 query 需要重新 embed
   - `vector_store.embed_query(translated)`

3. **三路检索并发**（~4-5秒）
   - BM25 (hybrid) + Graph：原中文 query
   - Dense：英文 translated query + 重嵌的 query_vec
   - 两路并发执行，但 Dense 路径依赖翻译+重嵌入完成

### 已有优化

✅ **缓存机制**：
- `gated_call` 使用 `cache_key_parts` (model, prompt_hash, sampling_params_hash, task)
- 相同 query 第二次调用会命中缓存

✅ **并发控制**：
- `ARK_EXPANSION_CONCURRENCY=5`（从 2 提升到 5，TASK-218）
- `expansion_semaphore` 控制并发数

✅ **异步架构**：
- 所有扩展函数都是 async
- BM25 和 Dense 路径并发执行

## 优化方案

### 方案 1：预热缓存（立即可用）

**原理**：首次查询慢，后续查询快

**实现**：
```python
# 在评估开始前，预热常见查询的翻译缓存
async def warmup_expansion_cache(queries: list[str]):
    tasks = [translate_query_async(q) for q in queries[:10]]
    await asyncio.gather(*tasks, return_exceptions=True)
```

**收益**：
- 第二次运行同一 query set 时，延迟降低 70-80%
- 适合：重复评估、用户常问问题

**成本**：
- 首次仍需等待
- 缓存存储空间（已有机制，无额外成本）

---

### 方案 2：提升并发度（需测试）

**原理**：更多并发翻译请求

**实现**：
```bash
# .env 配置
ARK_EXPANSION_CONCURRENCY=10  # 从 5 提升到 10
```

**收益**：
- 批量评估时，多个 query 并发翻译
- 理论上可降低 20-30% 延迟

**风险**：
- API 限流风险（需测试 ARK API 的 rate limit）
- 网络带宽瓶颈（梯子可能限制）

**验证方法**：
```bash
# 测试不同并发度
ARK_EXPANSION_CONCURRENCY=5 python eval_retrieval_runtime.py ...
ARK_EXPANSION_CONCURRENCY=10 python eval_retrieval_runtime.py ...
ARK_EXPANSION_CONCURRENCY=15 python eval_retrieval_runtime.py ...
```

---

### 方案 3：翻译+嵌入流水线优化（需开发）

**原理**：翻译完成后立即嵌入，不等所有翻译完成

**当前问题**：
```python
# 当前：串行
translated = await translate_query_async(query_text)  # 2-3秒
query_vec = await vector_store.embed_query(translated)  # 2-3秒
# 总计：4-6秒
```

**优化后**：
```python
# 优化：流水线
async def translate_and_embed(query_text, vector_store):
    translated = await translate_query_async(query_text)
    if translated:
        query_vec = await vector_store.embed_query(translated)
        return translated, query_vec
    return query_text, None

# 并发执行多个 query 的翻译+嵌入
results = await asyncio.gather(*[
    translate_and_embed(q, vector_store) for q in queries
])
```

**收益**：
- 批量评估时，流水线并行
- 理论上可降低 30-40% 延迟

**成本**：
- 需要修改 `eval_retrieval_runtime.py` 的 `_retrieve_with_expansion` 函数
- 测试工作量：中等

---

### 方案 4：按需扩展 UI（产品层）

**原理**：默认关闭扩展，用户主动选择

**实现**：
```python
# API 层
@router.post("/api/search")
async def search(
    query: str,
    use_expansion: bool = False,  # 默认 False
):
    ...

# 前端 UI
<Checkbox label="深度搜索（扩展查询，约10秒）" />
```

**收益**：
- 用户体验：快速响应（1.3秒）为默认
- 质量提升：需要时可选择扩展（10秒）
- 成本控制：减少不必要的 API 调用

**成本**：
- 前端开发：1-2小时
- 后端已支持 `use_expansion` 参数

---

### 方案 5：智能切换（产品层）

**原理**：首次快速响应，结果不满意时自动扩展

**实现**：
```python
# 首次查询：无扩展（1.3秒）
results = await search(query, use_expansion=False)

# 如果结果质量低（如 top-1 score < 0.5），自动触发扩展
if results and results[0].score < 0.5:
    results = await search(query, use_expansion=True)
```

**收益**：
- 用户体验：大部分查询快速响应
- 质量保证：低质量结果自动重试
- 成本优化：只在需要时扩展

**成本**：
- 需要定义"低质量"阈值
- 可能需要两次检索（最坏情况）

---

## 推荐方案组合

### 短期（立即可用）

1. ✅ **方案 1：预热缓存**
   - 在评估脚本开始前，预热常见查询
   - 成本：0，收益：70-80%（第二次运行）

2. ✅ **方案 2：提升并发度**
   - 测试 `ARK_EXPANSION_CONCURRENCY=10/15`
   - 成本：低，收益：20-30%（需验证）

3. ✅ **方案 4：按需扩展 UI**
   - 默认关闭扩展，用户主动选择
   - 成本：低，收益：用户体验提升

### 中期（需开发）

4. ⏸️ **方案 3：流水线优化**
   - 翻译+嵌入流水线并行
   - 成本：中，收益：30-40%

5. ⏸️ **方案 5：智能切换**
   - 首次快速，低质量自动扩展
   - 成本：中，收益：用户体验+成本优化

---

## 延迟目标验证

| 方案 | 当前延迟 | 优化后延迟 | 达标？ |
|------|---------|-----------|-------|
| Baseline | 10.4秒 | - | ❌ |
| 方案 1（缓存预热，第二次） | 10.4秒 | ~2-3秒 | ✅ |
| 方案 2（并发 10） | 10.4秒 | ~7-8秒 | ✅ |
| 方案 1+2 | 10.4秒 | ~1.5-2秒 | ✅ |
| 方案 3（流水线） | 10.4秒 | ~6-7秒 | ✅ |
| 方案 1+2+3 | 10.4秒 | ~1-1.5秒 | ✅ |

---

## 下一步行动

### 立即执行（Squad 自决策）

1. ✅ 记录本方案到 `docs/analysis/`
2. ⏸️ 测试方案 2（并发度提升）
3. ⏸️ 实现方案 4（按需扩展 UI）

### 待用户确认

- 是否需要立即实现方案 3（流水线优化）？
- 是否需要方案 5（智能切换）？

### 保留记录

- 本方案作为后续优化的参考
- 用户实际体验后再决定是否深度优化

---

## 证据

- 评估数据：`output/20260502-canary30-expansion-mm-embed.metrics.json`
- 代码位置：`workspace_tests/evaluation_scripts/eval_retrieval_runtime.py:878-932`
- 缓存机制：`literature_assistant/core/query_expander.py:125-138`
- 并发控制：`eval_retrieval_runtime.py:697-699, 1429-1431`
