# 切块与检索算法工程设计（决策驱动版）

> 版本：v3.0  
> 日期：2026-04-16  
> 状态：可执行设计（Phase 1 可直接落地）

---

## 0. 文档目标

本设计文档不再做“论文综述堆叠”，只回答四件事：

1. 我们现在有什么问题（基于当前代码）
2. 我们决定做什么 / 不做什么（带理由）
3. 每一阶段怎么落地（接口、参数、回滚）
4. 如何证明改动有效（评测口径与验收门槛）

---

## 1. 现状审计（基于当前仓库）

### 1.1 当前切块逻辑

文件：`routers/resources_router.py`（L289-L420）

- `CHUNK_SIZE=800`（字符）
- `CHUNK_OVERLAP=150`（字符）
- 递归字符切分（分隔符优先级：段落/换行/句号/空格）
- chunk 元数据仅有：`chunk_id/material_id/title/chunk_index/content/char_count`

**缺陷：**

- 不保留 `section_title/page/chunk_type`（来源语义弱）
- 表格/列表/公式容易被切断
- 与检索层的数据契约不统一

### 1.2 当前检索逻辑

存在两套并行但割裂的检索：

1. `resources_router.py`：关键词打分（token 交集 + 覆盖率）
2. `layers/r_layer_hybrid_retriever.py`：hybrid 框架 + rerank

**关键问题：**

- 向量检索分支当前是占位：`vector_score = bm25_score`
- BGE-m3 虽已配置，但未实质用于 chunk 检索

### 1.3 评测现状

- `eval_queries_v1.0.jsonl`：100 条查询
- `BASELINE_METRICS.json` / `calibration_results.json`：当前近似全零

**结论：** 当前没有可信 baseline，必须先打通评测闭环。

---

## 2. 方案选型与取舍

### 2.1 采纳（当前应做）

1. **结构感知切块（Phase 1）**  
   参考：Structure-Aware Chunking / Financial Report Chunking  
   原因：实现成本低、收益直接、能立刻改善可读性与召回。

2. **真实向量检索 + RRF 融合（Phase 2）**  
   参考：Reconstructing Context（RRF）  
   原因：BGE-m3 已有基础设施，改造 ROI 高。

3. **关键词二部图增强（Phase 3）**  
   参考：KET-RAG（轻量路径）  
   原因：零 LLM 成本，适合当前项目规模。

### 2.2 暂缓/否决（当前不做）

1. **DMG-RAG Router MLP**：缺训练数据，不具备落地条件。  
2. **SYNAPSE 全量扩散激活**：参数敏感、工程复杂度高。  
3. **MAQ 凸包检索**：小样本高维协方差不稳定。  
4. **全量 GraphRAG/HippoRAG**：成本高，当前阶段不必要。

---

## 3. Phase 0（前置）：评测闭环

### 3.1 目标

给任何检索策略一个统一评测入口，输出：

- Recall@1/3/5/10
- MRR
- P50/P95 延迟
- 按难度分层指标（simple/medium/hard）

### 3.2 交付

新增评测脚本（建议）：`eval_retrieval_runtime.py`

输入：`eval_queries_v1.0.jsonl` + retriever  
输出：结构化 JSON 指标 + 控制台摘要

### 3.3 验收门槛

- 脚本可稳定运行 100 条查询
- 产出非零 baseline（哪怕低）

---

## 4. Phase 1：结构感知切块（先做）

### 4.1 目标

修复 D1/D2/D3：让切块“知道结构”，并补齐关键元数据。

### 4.2 设计

#### 4.2.1 元素分类

按行/块识别：

- `TITLE`
- `NARRATIVE`
- `TABLE`
- `LIST`
- `FORMULA`

#### 4.2.2 切块策略

- 正文：递归切块（保留 overlap）
- 表格/列表/公式：整块优先，不拆行
- 每个 chunk 注入轻量上下文前缀：
  - `[文献: xxx]`
  - `[章节: xxx]`
  - `[类型: table/list/formula/narrative]`

#### 4.2.3 新数据结构

```python
@dataclass
class EnrichedChunk:
    chunk_id: str
    material_id: str
    title: str
    section_title: str
    chunk_index: int
    content: str
    raw_content: str
    chunk_type: str
    char_count: int
    page: int = 0
    embedding: list[float] | None = None
    keywords: list[str] | None = None
```

### 4.3 验收

- Recall@5 相比 baseline 提升 ≥10%（否则回滚）
- 输出 chunk 中 `section_title/chunk_type` 覆盖率 >95%

### 4.4 不做项

- 不引入 LLM 命题切分
- 不做图谱构建
- 不做 retrieval routing

---

## 5. Phase 2：真实向量检索上线

### 5.1 目标

修复“hybrid 名存实亡”问题，让 dense 分支真实生效。

### 5.2 设计

1. 建立 chunk embedding 索引（BGE-m3，1024 维）
2. 计算 query embedding，做余弦 TopN
3. 与 BM25 排名做 RRF 融合
4. Top50 进入现有 reranker 精排

### 5.3 关键公式（RRF）

$$
RRF(d) = \sum_{r \in rankers} \frac{1}{k + rank_r(d)}
$$

建议固定：$k=60$。

### 5.4 验收

- 在 Phase 1 基础上 Recall@5 再提升 ≥15% 或绝对值达到 0.60
- P95 延迟可控（目标 < 1200ms，含 rerank）

### 5.5 不做项

- 不上向量数据库（当前规模先用 numpy/轻量方案）
- 不做 late chunking

---

## 6. Phase 3：图增强检索（轻量）

### 6.1 目标

增强 hard 查询的跨段关联能力。

### 6.2 设计（KET-RAG 轻量路径）

- 构建“关键词-Chunk 二部图”
- Query 命中关键词节点后反向召回 chunk
- 三路融合：BM25 + Dense + Bipartite（RRF）

### 6.3 验收

- hard 子集 Recall@5 提升 ≥20%
- simple/medium 不明显退化（若退化，图检索仅对 hard 启用）

### 6.4 暂缓

- 不上全量 PPR
- 不上全量 OpenIE KG

---

## 7. 接口契约（必须统一）

### 7.1 输入输出契约

- 切块层输出：`list[EnrichedChunk]`
- 检索层统一接口：

```python
class RetrieverInterface(Protocol):
    def retrieve(self, query: str, top_k: int, project_id: str) -> list[tuple[EnrichedChunk, float]]: ...
```

### 7.2 与现有 `ChunkRecord` 兼容

`layers/contracts.py` 的 `ChunkRecord` 作为下游桥接结构，统一映射：

- `ChunkRecord.text = EnrichedChunk.content`
- `ChunkRecord.section_title = EnrichedChunk.section_title`
- `ChunkRecord.page = EnrichedChunk.page`

---

## 8. 超参数策略（只做可解释调参）

| 参数 | 初始值 | 调优方式 |
| --- | ---: | --- |
| `CHUNK_SIZE` | 800 | 网格：400/600/800/1000 |
| `CHUNK_OVERLAP` | 150 | 比例：15%-20% chunk_size |
| `RRF_K` | 60 | 固定（不轻易调） |
| `RERANK_TOPN` | 50 | 网格：20/50/100（看延迟-收益曲线） |
| `GRAPH_TOPN` | 100 | 网格：50/100/200 |

**调参规则：** 一次只动一个参数，必须在 100 条 eval 上出完整报告。

---

## 9. 风险与回滚

### 9.1 风险

1. BGE-m3 对中文学术文本效果不及预期
2. 结构切块导致 chunk 粒度不均，影响 reranker 稳定性
3. 图增强对 simple query 产生噪声

### 9.2 回滚策略

- Phase 1 回滚：恢复旧切块函数
- Phase 2 回滚：关闭 dense 分支，保留 BM25 + rerank
- Phase 3 回滚：按 query 难度门控图检索，仅 hard 启用

---

## 10. 实施顺序（最终版）

1. **先做 Phase 0**：打通 eval（1 天）
2. **再做 Phase 1**：结构切块 + 元数据（1-2 天）
3. **然后 Phase 2**：真实向量检索 + RRF（2-3 天）
4. **最后 Phase 3**：二部图增强（2-4 天）

每个阶段通过验收再进入下个阶段。

---

## 11. 附录：16 篇论文在本项目中的角色

### A. 当前直接用于工程决策

- Structure-Aware Chunking
- Financial Report Chunking
- Reconstructing Context（RRF）
- KET-RAG（轻量图路径）

### B. 当前仅作中长期参考（暂不实现）

- DMG-RAG
- Dense X Retrieval（LLM命题版）
- ChunkRAG（LLM过滤）
- HippoRAG
- SYNAPSE
- RAPTOR
- GraphRAG
- MAQ-retrieval

其余论文用于横向比较，不进入当前三阶段计划。

---

## 12. 一句话结论

**这版设计的核心不是“最先进”，而是“可落地、可验证、可回滚”。**
