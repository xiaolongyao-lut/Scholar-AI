# RAG 历史优化模式总结

> 创建时间：2026-05-03
> 目标：汇总本项目与参考项目的 RAG 优化模式，供后续优化决策参考

## 1. 缓存优化模式

### 1.1 LLM 调用缓存（已实现）

**位置**：`literature_assistant/core/query_expander.py:125-138`

**模式**：
```python
gated_call(
    kind="llm",
    cache_key_parts={
        "model": model,
        "prompt_hash": _prompt_hash(prompt),
        "sampling_params_hash": _sampling_params_hash(),
        "task": task,
    },
    payload={"prompt": prompt},
    invoke=lambda: _call_ark_once(...),
    validate_result=lambda value: isinstance(value, str),
)
```

**收益**：
- 相同 query 第二次调用命中缓存，延迟降低 70-80%
- 适用于：翻译、扩展、重排序等 LLM 调用

**参考来源**：
- 本项目 `gated_call` 机制
- PaperQA2 的 `@lru_cache` 装饰器模式
- TheKnowledge 的 `hash_skip` 编译缓存

---

### 1.2 预排序前缓存短路（参考方案）

**来源**：`.squad/decisions/inbox/morpheus-retrieval-optimization.md`

**模式**：
```python
# 在 rerank 前检查缓存
if query_hash in rerank_cache:
    return rerank_cache[query_hash]

# 否则执行 rerank
reranked = await reranker.rerank(query, candidates)
rerank_cache[query_hash] = reranked
return reranked
```

**收益**：
- 跳过昂贵的 rerank 计算（通常是检索链最大延迟来源）
- 适用于：重复查询、评估批量运行

**风险**：
- 缓存失效策略需要考虑 corpus 更新
- 缓存大小需要限制（LRU 或 TTL）

---

## 2. 并发控制优化

### 2.1 信号量并发控制（已实现）

**位置**：`workspace_tests/evaluation_scripts/eval_retrieval_runtime.py:697-699, 1429-1431`

**模式**：
```python
ARK_EXPANSION_CONCURRENCY = int(os.getenv("ARK_EXPANSION_CONCURRENCY", "5"))
expansion_semaphore = asyncio.Semaphore(ARK_EXPANSION_CONCURRENCY)

async def translate_query_async(query: str) -> str:
    async with expansion_semaphore:
        return await _call_ark_async(...)
```

**收益**：
- 批量评估时，多个 query 并发翻译
- 从 2 提升到 5 后，延迟降低约 20-30%

**调优方向**：
- 测试 10/15 并发度（需验证 API rate limit）
- 监控网络带宽瓶颈（梯子限制）

**参考来源**：
- asyncio 标准模式
- LightRAG 的 `max_concurrent_requests` 配置

---

### 2.2 流水线并行（待实现）

**来源**：`docs/analysis/expansion-latency-optimization-plan.md` 方案 3

**模式**：
```python
# 当前：串行
translated = await translate_query_async(query_text)  # 2-3秒
query_vec = await vector_store.embed_query(translated)  # 2-3秒
# 总计：4-6秒

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

---

## 3. 候选过滤优化

### 3.1 Artifact-Aware 预排序过滤（已实现）

**位置**：`.squad/decisions/inbox/oracle-bad-chunk-optimization.md`

**问题**：
- Elsevier 索引页（目录页）污染检索结果
- 这些页面无实质内容，但 BM25/Dense 排序靠前

**解决方案**：
```python
# 在 rerank 前过滤
def filter_artifact_chunks(candidates: list[Chunk]) -> list[Chunk]:
    return [
        c for c in candidates
        if not is_elsevier_index_page(c)
    ]

# 检测规则
def is_elsevier_index_page(chunk: Chunk) -> bool:
    return (
        "elsevier" in chunk.source_labels
        and len(chunk.content) < 500
        and "Table of Contents" in chunk.content
    )
```

**收益**：
- 减少无效候选进入 rerank 队列
- 提升检索质量（避免噪声排序靠前）

**参考来源**：
- 本项目 Oracle 决策
- PaperQA2 的 `metadata_filter` 模式

---

### 3.2 元数据驱动候选剪枝（参考方案）

**来源**：`.squad/decisions/inbox/morpheus-retrieval-optimization.md`

**模式**：
```python
# 根据元数据降权或排除
def prune_candidates(candidates: list[Chunk], query_metadata: dict) -> list[Chunk]:
    pruned = []
    for c in candidates:
        # 排除：已知低质量来源
        if c.source_labels & {"elsevier_index", "duplicate", "malformed"}:
            continue
        # 降权：非目标语言
        if query_metadata.get("lang") == "zh" and c.metadata.get("lang") != "zh":
            c.score *= 0.5
        pruned.append(c)
    return pruned
```

**收益**：
- 减少 rerank 队列大小
- 提升检索精度（排除已知噪声）

**参考来源**：
- PaperQA2 的 `metadata_filter`
- TheKnowledge 的 `source_immutability` 检查

---

## 4. 词汇重叠增强（已实现）

### 4.1 TOLF 词汇重叠加权

**位置**：`literature_assistant/core/tolf_text_selector.py`

**问题**：
- 30/30 canary queries 缺乏词汇重叠
- 纯语义相似度可能漂移到无关文档

**解决方案**：
```python
def select_tolf_context_chunks(
    query: str,
    chunks: list[dict],
    top_k: int = 5,
    lexical_boost: float = 0.20,
) -> list[dict]:
    query_tokens = set(tokenize(query.lower()))
    for chunk in chunks:
        chunk_tokens = set(tokenize(chunk["content"].lower()))
        overlap = query_tokens & chunk_tokens
        if overlap:
            chunk["tolf_activation_score"] += lexical_boost
            chunk["query_overlap_tokens"] = list(overlap)
    return sorted(chunks, key=lambda c: c["tolf_activation_score"], reverse=True)[:top_k]
```

**收益**：
- 提升 Recall@5 +6.7%
- 提升 MRR +19.7%

**参考来源**：
- BM25 的词汇匹配思想
- PaperQA2 的 `lexical_overlap_bonus`

---

## 5. 按需启用模式（已实现）

### 5.1 Feature Flag 默认关闭

**位置**：`literature_assistant/core/runtime_env.py`

**模式**：
```python
# 所有新能力默认关闭
WIKI_ENABLED = parse_bool(os.getenv("LITERATURE_ASSISTANT_WIKI_ENABLED", "0"))
EXPANSION_ENABLED = parse_bool(os.getenv("LITERATURE_ASSISTANT_EXPANSION_ENABLED", "0"))
```

**收益**：
- 用户体验：快速响应为默认
- 成本控制：减少不必要的 API 调用
- 风险隔离：新功能不影响现有链路

**参考来源**：
- `docs/plans/specs/llmwiki-integration-spec.md` LMWR-228
- TheKnowledge 的 `draft_approval` 模式
- obsidian-llm-wiki-local 的 `inline_citation_toggle`

---

### 5.2 智能切换（待实现）

**来源**：`docs/analysis/expansion-latency-optimization-plan.md` 方案 5

**模式**：
```python
# 首次查询：无扩展（1.3秒）
results = await search(query, use_expansion=False)

# 如果结果质量低（如 top-1 score < 0.5），自动触发扩展
if results and results[0].score < 0.5:
    results = await search(query, use_expansion=True)
```

**收益**：
- 大部分查询快速响应
- 低质量结果自动重试
- 成本优化：只在需要时扩展

---

## 6. 链接页面扩展（已实现）

### 6.1 Wiki 链接页面去重扩展

**位置**：`literature_assistant/core/wiki/query.py:160-218`

**模式**：
```python
def expand_linked_pages(
    primary_results: list[WikiSearchResult],
    page_store: WikiPageStore,
    *,
    max_linked: int = 3,
) -> list[WikiSearchResult]:
    linked_pages: dict[Path, float] = {}
    primary_paths = {r.page_path for r in primary_results}

    for result in primary_results:
        content = page_store.read_page(result.page_path)
        if not content:
            continue
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        for link in wikilinks:
            link_path = Path(link.strip())
            if link_path in primary_paths:
                continue
            if link_path not in linked_pages:
                linked_pages[link_path] = 0.0
            linked_pages[link_path] += result.score * 0.5

    sorted_linked = sorted(linked_pages.items(), key=lambda x: x[1], reverse=True)
    return [WikiSearchResult(...) for link_path, score in sorted_linked[:max_linked]]
```

**收益**：
- 自动扩展相关上下文
- 去重避免重复内容
- 加权传播（primary score * 0.5）

**参考来源**：
- WikiLoom 的 `linked-page expansion`
- SwarmVault 的 `context packs`

---

## 7. 上下文打包与截断（已实现）

### 7.1 Token-Bounded Context Pack

**位置**：`literature_assistant/core/wiki/query.py:279-338`

**模式**：
```python
@dataclass(frozen=True)
class WikiContextPack:
    query: str
    primary_pages: list[str]
    linked_pages: list[str]
    total_tokens: int
    truncated: bool

def render_context_pack(
    query: str,
    query_result: WikiQueryResult,
    page_store: WikiPageStore,
    *,
    max_tokens: int = 4000,
    tokens_per_char: float = 0.25,
) -> WikiContextPack:
    max_chars = int(max_tokens / tokens_per_char)
    total_chars = 0
    truncated = False

    for result in query_result.wiki_hits:
        page_text = f"## {result.title}\n\n{body}"
        if total_chars + len(page_text) > max_chars:
            truncated = True
            break
        primary_pages.append(page_text)
        total_chars += len(page_text)

    return WikiContextPack(...)
```

**收益**：
- 控制 LLM 上下文窗口大小
- 优先级排序（primary → linked）
- 截断标记（用户可见）

**参考来源**：
- SwarmVault 的 `context packs`
- PaperQA2 的 `context_window_management`

---

## 8. 调试追踪（已实现）

### 8.1 Query Debug Trace

**位置**：`literature_assistant/core/wiki/query.py:341-357`

**模式**：
```python
@dataclass(frozen=True)
class WikiQueryTrace:
    query: str
    enabled: bool
    fts_hits: int
    linked_hits: int
    fallback_used: bool
    fallback_reason: str
    total_pages: int
    context_tokens: int

def build_query_trace(
    query: str,
    query_result: WikiQueryResult,
    context_pack: WikiContextPack | None = None,
    *,
    enabled: bool = False,
) -> WikiQueryTrace:
    return WikiQueryTrace(
        query=query,
        enabled=enabled,
        fts_hits=len(query_result.wiki_hits),
        linked_hits=len(query_result.linked_hits),
        fallback_used=query_result.fallback_used,
        fallback_reason=query_result.fallback_reason,
        total_pages=len(query_result.wiki_hits) + len(query_result.linked_hits),
        context_tokens=context_pack.total_tokens if context_pack else 0,
    )
```

**收益**：
- 可观测性：每次查询的检索路径
- 调试友好：fallback 原因、token 消耗
- 评估支持：批量查询的统计分析

**参考来源**：
- WeKnora 的 `observability` 模块
- openclaw 的 `usage_tracking`

---

## 9. 参考项目优化模式索引

### 9.1 PaperQA2（科学文献 RAG）

**路径**：`C:\Users\xiao\Downloads\llmwiki借鉴库\paper-qa-main`

**可借鉴优化**：
- `metadata_filter`：元数据驱动候选过滤
- `lexical_overlap_bonus`：词汇重叠加权
- `@lru_cache`：LLM 调用缓存
- `context_window_management`：上下文窗口管理
- `contradiction_detection`：矛盾检测（质量保证）

---

### 9.2 TheKnowledge（Wiki 编译器）

**路径**：`C:\Users\xiao\Downloads\llmwiki借鉴库\TheKnowledge-main`

**可借鉴优化**：
- `hash_skip`：编译缓存（source_hash 不变跳过）
- `citation_density`：引用密度检查（质量门禁）
- `draft/finalize`：分阶段质量控制
- `source_immutability`：源不可变性检查

---

### 9.3 LightRAG（图 RAG）

**路径**：`github\LightRAG-1.4.15`

**可借鉴优化**：
- `max_concurrent_requests`：并发控制
- `reranker as first-class capability`：重排序作为一等公民
- `query_modes`：多模式查询（local/global/hybrid）

---

### 9.4 WikiLoom（Chunk Store）

**路径**：`C:\Users\xiao\Downloads\llmwiki借鉴库\wikiloom-main`

**可借鉴优化**：
- `stable_chunk_id`：稳定 chunk ID（去重）
- `hybrid_linking`：混合链接（wikilink + semantic）
- `duplicates`：重复检测与合并

---

### 9.5 SwarmVault（Context Packs）

**路径**：`C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main`

**可借鉴优化**：
- `context_packs`：上下文打包
- `retrieval_manifest`：检索清单（可审计）
- `review_queues`：审核队列（质量控制）

---

## 10. 优化决策矩阵

| 优化模式 | 延迟收益 | 质量收益 | 成本 | 实现难度 | 状态 |
|---------|---------|---------|------|---------|------|
| LLM 调用缓存 | 70-80% | 0 | 低 | 低 | ✅ 已实现 |
| 并发控制（5→10） | 20-30% | 0 | 低 | 低 | ⏸️ 待测试 |
| 流水线并行 | 30-40% | 0 | 中 | 中 | ⏸️ 待实现 |
| Artifact 过滤 | 10-20% | +15% | 低 | 低 | ✅ 已实现 |
| 词汇重叠加权 | 0 | +6.7% Recall | 低 | 低 | ✅ 已实现 |
| 按需启用 | N/A | 0 | 低 | 低 | ✅ 已实现 |
| 链接页面扩展 | 0 | +上下文 | 低 | 低 | ✅ 已实现 |
| 上下文打包 | 0 | +可控性 | 低 | 低 | ✅ 已实现 |
| 调试追踪 | 0 | +可观测 | 低 | 低 | ✅ 已实现 |
| 预排序缓存短路 | 40-60% | 0 | 中 | 中 | ⏸️ 参考方案 |
| 元数据剪枝 | 10-20% | +10% | 低 | 中 | ⏸️ 参考方案 |
| 智能切换 | N/A | +体验 | 中 | 中 | ⏸️ 参考方案 |

---

## 11. 下一步行动

### 立即可用（短期）

1. ✅ 记录本方案到 `docs/analysis/`
2. ⏸️ 测试并发度提升（ARK_EXPANSION_CONCURRENCY 5→10/15）
3. ⏸️ 实现按需扩展 UI（默认关闭，用户选择）

### 待评估（中期）

4. ⏸️ 流水线优化（translate+embed 并行）
5. ⏸️ 预排序缓存短路（rerank 前检查缓存）
6. ⏸️ 元数据驱动剪枝（已知噪声源排除）

### 保留记录（长期）

- 用户实际体验后再决定是否深度优化
- 参考项目模式作为后续优化的思路库

---

## 12. 证据索引

- 扩展评估数据：`output/20260502-canary30-expansion-mm-embed.metrics.json`
- 扩展延迟优化计划：`docs/analysis/expansion-latency-optimization-plan.md`
- Oracle 坏块优化：`.squad/decisions/inbox/oracle-bad-chunk-optimization.md`
- Morpheus 检索优化：`.squad/decisions/inbox/morpheus-retrieval-optimization.md`
- LLMWiki 集成规范：`docs/plans/specs/llmwiki-integration-spec.md`
- LLMWiki 参考项目索引：`docs/plans/specs/llmwiki-reference-project-index.md`
- 性能优化指令：`.github/instructions/performance-optimization.instructions.md`
            if link_path in primary_paths:  # 去重
                continue
            linked_pages[link_path] = linked_pages.get(link_path, 0.0) + result.score * 0.5

    return sorted(linked_pages.items(), key=lambda x: x[1], reverse=True)[:max_linked]
```

**收益**：
- 扩展相关上下文（从 1 个主页面扩展到 3-5 个相关页面）
- 去重避免重复内容

**参考来源**：
- WikiLoom 的 `hybrid_linking` 模式
- SwarmVault 的 `context_packs` 模式

---

## 7. 上下文打包与截断（已实现）

### 7.1 Token-Bounded Context Pack

**位置**：`literature_assistant/core/wiki/query.py:279-338`

**模式**：
```python
def render_context_pack(
    query: str,
    query_result: WikiQueryResult,
    page_store: WikiPageStore,
    *,
    max_tokens: int = 4000,
    tokens_per_char: float = 0.25,
) -> WikiContextPack:
    primary_pages: list[str] = []
    linked_pages: list[str] = []
    total_chars = 0
    max_chars = int(max_tokens / tokens_per_char)
    truncated = False

    for result in query_result.wiki_hits:
        content = page_store.read_page(result.page_path)
        page_text = f"## {result.title}\n\n{content}"
        if total_chars + len(page_text) > max_chars:
            truncated = True
            break
        primary_pages.append(page_text)
        total_chars += len(page_text)

    return WikiContextPack(
        query=query,
        primary_pages=primary_pages,
        linked_pages=linked_pages,
        total_tokens=int(total_chars * tokens_per_char),
        truncated=truncated,
    )
```

**收益**：
- 避免超出 LLM context window
- 优先保留主页面，次要保留链接页面

**参考来源**：
- SwarmVault 的 `context_packs` 模式
- PaperQA2 的 `context_assembly` 模式

---

## 8. 参考项目优化模式索引

| 项目 | 优化模式 | 本项目对应 |
|---|---|---|
| **PaperQA2** | `@lru_cache` LLM 调用缓存 | `gated_call` 缓存机制 |
| **PaperQA2** | `metadata_filter` 元数据过滤 | Artifact-aware 过滤 |
| **PaperQA2** | `lexical_overlap_bonus` 词汇重叠加权 | TOLF 词汇重叠 |
| **TheKnowledge** | `hash_skip` 编译缓存 | `gated_call` cache_key_parts |
| **TheKnowledge** | `source_immutability` 来源不可变性 | Artifact quarantine |
| **WikiLoom** | `hybrid_linking` 混合链接 | Wiki 链接页面扩展 |
| **WikiLoom** | `stable_chunk_id` 稳定 chunk ID | 本项目 chunk_id 机制 |
| **SwarmVault** | `context_packs` 上下文打包 | Wiki context pack |
| **SwarmVault** | `retrieval_manifest` 检索清单 | 待实现 |
| **LightRAG** | `max_concurrent_requests` 并发控制 | ARK_EXPANSION_CONCURRENCY |
| **obsidian-llm-wiki-local** | `inline_citation_toggle` 按需启用 | Feature flag 默认关闭 |

---

## 9. 下一步优化方向

### 短期（立即可用）

1. ✅ **缓存预热**：评估脚本开始前预热常见查询
2. ✅ **并发度提升**：测试 `ARK_EXPANSION_CONCURRENCY=10/15`
3. ✅ **按需扩展 UI**：默认关闭扩展，用户主动选择

### 中期（需开发）

4. ⏸️ **流水线优化**：翻译+嵌入流水线并行
5. ⏸️ **智能切换**：首次快速，低质量自动扩展
6. ⏸️ **预排序前缓存短路**：跳过重复 rerank 计算

### 长期（需研究）

7. ⏸️ **元数据驱动剪枝**：根据元数据降权或排除候选
8. ⏸️ **检索清单**：记录检索决策路径，供 doctor 分析
9. ⏸️ **Graph-aware 检索**：利用 wiki graph 扩展相关实体

---

## 10. 证据索引

| 优化模式 | 证据文件 |
|---|---|
| LLM 调用缓存 | `literature_assistant/core/query_expander.py:125-138` |
| 并发控制 | `workspace_tests/evaluation_scripts/eval_retrieval_runtime.py:697-699` |
| Artifact 过滤 | `.squad/decisions/inbox/oracle-bad-chunk-optimization.md` |
| 预排序优化 | `.squad/decisions/inbox/morpheus-retrieval-optimization.md` |
| TOLF 词汇重叠 | `literature_assistant/core/tolf_text_selector.py` |
| Wiki 链接扩展 | `literature_assistant/core/wiki/query.py:160-218` |
| Context pack | `literature_assistant/core/wiki/query.py:279-338` |
| Feature flag | `docs/plans/specs/llmwiki-integration-spec.md` LMWR-228 |
| 扩展延迟优化 | `docs/analysis/expansion-latency-optimization-plan.md` |
| 参考项目索引 | `docs/plans/specs/llmwiki-reference-project-index.md` |
