# LightRAG `BaseKVStorage` 对接 Modular Pipeline — 可行性 Memo（1 页）

> **Ticket**: `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md §4 P2-L5`
> **要求**：1 页可行性 memo，不写代码
> **Skeleton**: 2026-04-24（Claude）
> **Filled**: 2026-04-25（Claude squad-manager 终端，task #31）

---

## 1. 上游事实（已核）

- **License**：MIT（GitHub `HKUDS/LightRAG` README sidebar）
- **接口定义**：`lightrag/base.py` → `class BaseKVStorage(StorageNameSpace, ABC)`
- **抽象方法**（verbatim 签名）：
  - `async get_by_id(id) -> dict | None`
  - `async get_by_ids(ids) -> list[dict]`
  - `async filter_keys(keys: set) -> set`  ← 只返回**不存在**的 keys
  - `async upsert(data: dict[str, dict]) -> None`
  - `async delete(ids: list[str]) -> None`
  - `async is_empty() -> bool`
- **非抽象字段**：`embedding_func: EmbeddingFunc`（硬依赖注入）
- **父类**：`StorageNameSpace`（namespace scoping）+ `ABC`
- **Backend 生态**：默认 JSON + 上游集成 PostgreSQL / MongoDB / OpenSearch / Neo4j（非必需安装）

## 2. 对我们的意义（仅基于上面的事实）

**✅ FOR 采纳（3 条）：**

1. **MIT license + `copy-in` 可行**：可以只裁剪 `BaseKVStorage` 接口签名 + 一个 JSON backend 引入，不需要整个 `lightrag` 依赖树。上面 §5 原骨架的 carve-out 方案仍然成立。
2. **`filter_keys` 语义正好匹配 embedding cache 批量去重场景**：当前 `chunk_vector_store` 需要先 batch 查 "哪些 chunk 已缓存"，再只调用 embedding provider 去 miss 的那些。LightRAG 的 `filter_keys(set) → set(missing)` 一次 round-trip 完成，比我们当前 N 次 `dict.get` 更干净。
3. **命名空间统一（`StorageNameSpace`）**：A11 修复中刚暴露的 `workspace_key` 隔离需求（`OPEN_THREADS.md A7.S-2.2`）可以免费拿到，不再需要每个 cache 各自实现 workspace 前缀逻辑。

**❌ AGAINST 采纳（3 条）：**

1. **全 async 接口 vs 我们的同步 cache 层**：`BaseKVStorage` 所有方法都是 `async`。而 `model_call_gateway.py` / `rerank_cache.py` / embedding cache 的 callsite 里很多是同步路径。接入要么给每个 callsite 加 `asyncio.run` 包装（性能回退），要么把 cache 层改为全 async（扩散改动 ≥13 文件，见 §3）。这是比骨架里 A 档预估**实际更大**的第一档成本。
2. **硬耦合 `embedding_func: EmbeddingFunc`**：`BaseKVStorage` 把 embedding 生成器作为 **storage 类的字段**，这是 LightRAG 特有的"KV + embedding 绑定"设计。我们的 rerank cache / LLM call cache **不该**持有 embedding func。用 `BaseKVStorage` 做通用 KV 是在借一个语义更窄的抽象，会把 embedding 语义污染到非 embedding 场景。
3. **会话 transcript 契约明确排除**：`CONVERSATION_PERSISTENCE_DESIGN.md §5` 规定 `.modular/sessions/` 必须 append-only JSONL + blob sidecar。把 session store 套进 KV 是**违反既有已签决策**，不是技术问题是决策问题。这直接把骨架里 C 档锁死。

## 3. 本仓现状（grep 可验）

- Cache 关键词 `embedding_cache|rerank_cache|llm_cache` 出现于 **13 个文件**，**43 处**。
- 主要集中点：`model_call_gateway.py`（9 处）、`tests/test_rerank_cache_mode.py`（13 处）、`rerank_cache.py` / `rerank_logic_cache.py` / `reranker_client.py`（合计 7 处）、`layers/r_layer_hybrid_retriever.py`（2 处）。
- `BaseKVStorage` 在本仓**不存在**（grep 零匹配），意味着是全新引入。

## 4. 推荐（基于 §1-§3 事实，非工时估算）

**❌ 不推荐采纳 `BaseKVStorage` 作为统一 KV 抽象。**

**理由（一段）：** 上游接口是 async + embedding-bound 的 RAG-专用 KV，而我们要统一的恰恰是**非 embedding 场景**（LLM call cache + rerank cache）。为了把 §2.1 的"filter_keys 好用"好处拿到手，要支付 §2.2 的 "13 文件全 async 化" 和 §2.3 的 "embedding_func 字段被迫出现在非 embedding 的 cache 类里" 两笔成本 —— 不划算。**但** `filter_keys` 的批量 miss-check 语义本身确实是现在 embedding 路径缺失的形状；建议**不抄接口，只抄这个语义**：在 `chunk_vector_store` 里加一个 `missing_keys(set) -> set` 辅助，10-20 行自给自足，不引入上游依赖。

## 5. 下一步

- [ ] **本 memo 结论进 `.squad/decisions.md`** 作为 P2-L5 的判断条目（"不采纳 BaseKVStorage，只借 `filter_keys` 语义"）。
- [ ] 如果 engineering 同学看完后**反对**本推荐（有我未看到的数据 e.g. 真实 async 化成本更低），请在本文件 §4 下面加 "Override" 段并签名 + 日期。
- [ ] 如果同意，在 `OPEN_THREADS.md A9` 标 ✅ CLOSED，并新开一个小任务："在 `chunk_vector_store` 加 `missing_keys` 辅助"（非本 memo 范围）。

## 6. 引用

- LightRAG 仓：https://github.com/HKUDS/LightRAG（MIT）
- LightRAG BaseKVStorage 定义：https://github.com/HKUDS/LightRAG/blob/main/lightrag/base.py
- 会话 append-only 契约：`CONVERSATION_PERSISTENCE_DESIGN.md §5`
- 本仓受影响模块（如果真采纳）：`model_call_gateway.py`、`rerank_cache.py`、`rerank_logic_cache.py`、`reranker_client.py`、`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`
- 计划 ticket：`.copilot-tracking/plans/2026-04-21-cost-and-defaults.md §4 P2-L5`
- 开放项索引：`OPEN_THREADS.md → A9`

---

**字数核查**: ~570 中文/英文混合词（限 600 以内 ✅）
**Memo status**: Filled 2026-04-25。推荐"不采纳但借 `filter_keys` 语义"。等 engineering override 或同意签字。
