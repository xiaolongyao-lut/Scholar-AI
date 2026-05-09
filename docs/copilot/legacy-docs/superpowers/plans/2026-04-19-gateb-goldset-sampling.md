# Gate B: 100–200 条人工小金标集抽样与标注方案

> **External web retrieval was unavailable on 2026-04-19, so this Gate B draft
> is grounded in repo-local requirements plus established IR conventions.**
>
> 当 web access 恢复后可做一次 lightweight verification pass,针对 BEIR/TREC/
> sentence-transformers 的一手文本做对照,不需要重写本方案。

---

## 0. 来源标签约定

每条规则在行末用 `[标签]` 标明依据分类,严格区分"仓库已写死的事实"、"IR 领
域通行约定"、"本项目基于证据的推断"三类:

- `[repo_anchor]` — 仓库内已提交的文档或 Wave 1 审计产物中的事实
- `[established_ir_convention]` — TREC / BEIR / Sentence-Transformers 等领
  域广泛采用的做法(训练知识,无法实时引证时不假装逐字引用)
- `[project_inference]` — 基于上述两类,针对本项目当前状态推断出的选择

---

## 1. 触发背景(Context)

### 1.1 Gate A 核心证据(repo_anchor)

来自 `artifacts/eval_audit/audit_v21_20260418.json`: `[repo_anchor]`

- total_queries = **3269**
- unique_query_text = **181 / 3269 = 5.5%**
- template_match = **3269/3269 (100%)**
- doc_id_coverage: 168/168 hit, **missing=0**
- per_source_fanout: min=3, **median=20**, mean=19.46, max=20
- duplicate_query_text_across_docs (≥6 distinct docs): **70 types**
  - top1 "激光焊接的最新研究进展" → **158 distinct docs**
  - top2 "激光焊接的基本原理和方法" → 158 distinct docs
- hard_with_single_doc_evidence: **326 / 326 (100%)**
- per_template_count 不均衡:
  - `simple:0 = simple:1 = simple:2 = 496` (共 1488)
  - `medium:0 = medium:1 = medium:2 = 485` (共 1455)
  - `hard:0 = hard:1 = 163` (共 326)
- per_difficulty.unique_text:
  - simple: 33 unique / 1488 = **2.2%**
  - medium: 108 unique / 1455 = 7.4%
  - hard: 40 unique / 326 = 12.3%

### 1.2 由 Gate A 得到的 qrels-level 判断

> 现有 v2.1 语料的 evidence_set 每条 query **只登记 1 个 doc_id**,而同一字面
> query 跨 158 条不同 query 分别指向 158 个不同 doc;在 fanout 这么高的分布
> 上,top-k 检索的命中天花板接近 `k / fanout`,任何检索系统都无法从 R@5=0.022
> 的泥潭里靠模型升级爬出来。`[project_inference]`

因此 Gate B 需要做的事,不是"换一套更好的 query",而是:

1. **重建 qrels**:对被多条 query 共用的字面(high-fanout text),人工确认每个
   指向的 doc 是否真的 relevant,产出 `query_text → {doc_id: relevance}` 的
   多对多映射。`[project_inference]`
2. **重建 hard 的定义**:现在 326 条 hard 全部 evidence=1,违反 hard 本意。
   抽样重判,恢复"多 evidence 支撑"的语义。`[project_inference]`
3. **扩入 non-template query**:当前 non_template=0,与真实用户分布差距大。
   补 30 条左右覆盖 TOLF §9.4.2 列出的五种文献问题类型。`[repo_anchor]`

---

## 2. Scope / Non-scope

### 2.1 本 Gate(Gate B)只做

- 定义 100–200 条人工小金标集的**抽样策略**与样本清单 `[repo_anchor]`(用户指令)
- 产出 qrels / pooling / 标注 / 验收 四份 policy `[repo_anchor]`
- 基于 Wave 1 audit 的输出分层 `[repo_anchor]`
- 从 `duplicate_query_text_across_docs` + `hard_with_single_doc_evidence` 里
  识别"先标哪些"的优先级清单 `[repo_anchor]`

### 2.2 本 Gate 不做

- 不开 D 会话持久化 worktree `[repo_anchor]`
- 不处理 `stash@{0}`(遗留非 A 改动)`[repo_anchor]`
- 不做 Wave 2 启发式未知模板发现 `[repo_anchor]`
- 不做 Wave 3 检索 / 模型改动(bge 对照 / embedding 切换等)`[repo_anchor]`
- 不修 WebSearch / WebFetch 工具链 `[repo_anchor]`
- 不在本 Gate 内实际执行人工标注(本文档是**标注前的方案**)`[project_inference]`

---

## 3. 目标规模与分层

### 3.1 总规模

**目标 130 条**,在用户指定的 100–200 区间偏中,留 20–70 条浮动空间给标注过
程中新发现的 edge case 补位。`[project_inference]`

### 3.2 四个 strata

| Stratum | 条数 | 来源 | 目的 |
|---------|-----:|------|------|
| **S1** Template-balanced | 80 | 从 3269 模板 query 按 template_id 均匀采样 | 与现有评测语料可比,覆盖 8 个模板族 |
| **S2** Duplicate-heavy re-judge | 10 | 从 70 个 `duplicate_query_text_across_docs` 里选 top-fanout 10 个 unique text | 重建多对多 qrels,验证 fanout 问题真实规模 |
| **S3** Hard-single re-judge | 10 | 从 326 条 `hard_with_single_doc_evidence` 随机抽 | 检验 hard 定义是否实际可满足 |
| **S4** Non-template fresh | 30 | 用户或专家新编 | 覆盖 TOLF §9.4.2 五类真实文献问题 |
| **合计** | **130** | | |

### 3.3 S1 细分(template × difficulty stratified)

每个 template_id 采 10 条,要求:

- `[established_ir_convention]` stratified random sampling — 每层按比例抽,保证
  覆盖
- `[project_inference]` 在每个 template_id 内,若 unique_text < 10,优先全采
  unique text(如 simple:0 可能只有 ~11 个 unique),再在每个 unique text 下
  随机选 1 条
- `[project_inference]` 若 unique_text ≥ 10,采 10 条不同 unique text

| template_id | 分配条数 | 备注 |
|-------------|-------:|------|
| simple:0 | 10 | fanout 极高,优先 unique text |
| simple:1 | 10 | 同上 |
| simple:2 | 10 | 同上 |
| medium:0 | 10 | unique text 更多,正常 stratified |
| medium:1 | 10 | 同上 |
| medium:2 | 10 | 同上 |
| hard:0 | 10 | hard 数据稀疏,可能需要补 |
| hard:1 | 10 | 同上 |
| **小计** | **80** | |

### 3.4 S4 细分(TOLF §9.4.2 五类)`[repo_anchor]`

| 问题类型 | 条数 | 举例(供参考,非 final 样本) |
|---------|----:|-----------------------------|
| 参数-结果类 | 6 | "Ti-6Al-4V 在 2.5 kW CW 激光下 HAZ 硬度变化?" |
| 机理解释类 | 6 | "keyhole 形成如何受表面张力梯度影响?" |
| 图表证据类 | 6 | "EBSD 图谱能显示哪些关于晶粒细化的信息?" |
| 对比归纳类 | 6 | "CMT 冷金属过渡 vs 激光电弧复合在接头性能的差异?" |
| 多文献汇总类 | 6 | "钛合金激光焊接裂纹机制有哪些主流解释?" |
| **小计** | **30** | |

---

## 4. Qrels Policy

### 4.1 Relevance 等级

**graded {0, 1, 2}**,与 TREC 传统一致。`[established_ir_convention]`

| 等级 | 含义 | 判断依据 |
|----:|------|---------|
| **0** | Not relevant | chunk 完全不涉及 query 主题,或只有表面词匹配无实质内容 |
| **1** | Partial / background | chunk 提到 query 主题但是作为背景、literature 提及、对比对象,没有给出 query 想要的具体答案 |
| **2** | Directly relevant | chunk 直接回答 query 的事实 / 机理 / 数据 |

MVP 评测时可以把 `{1, 2}` 合并为 relevant=1,`0` → 0(binary 派生)。
`[established_ir_convention]`

### 4.2 多对多映射(关键改动)

- 旧 evidence_set 的语义:`query → [doc_id]`(只有 1 对 1)`[repo_anchor]`
- Gate B qrels 的语义:`query_text → {doc_id: relevance_grade}`
  `[project_inference]`
- 特别对 S2(duplicate-heavy),同一 query_text 在现有语料指向多个 doc,人工要
  为**每个**候选 doc 独立打分,允许存在多个 relevance=2 的 gold `[project_inference]`

### 4.3 Negative judgment 约定

- 人工只对 **pooling 结果**内的 doc 做 judgment `[established_ir_convention]`
- 未在 pool 里出现、且未被人工标注的 doc,**默认 relevance=0**
  (TREC "assumed non-relevant" 约定)`[established_ir_convention]`

### 4.4 数据格式

输出 `artifacts/eval_audit/gateb_qrels.tsv`,TREC 经典格式:

```
query_id  iteration  doc_id  relevance
q_g0001   0          mat_abc 2
q_g0001   0          mat_def 1
q_g0001   0          mat_xyz 0
```

`iteration` 固定 0(单轮标注)。`[established_ir_convention]`

---

## 5. Pooling Policy

### 5.1 Pool 构造

每条 query 的 candidate pool = 以下来源 **union,depth-10 pooling**:
`[established_ir_convention]`

| 来源 | 取法 | 说明 |
|------|------|------|
| BM25 | top-10 | 纯词匹配基线 |
| Dense (Qwen3-Emb-8B) | top-10 | 余弦相似度 |
| Graph (keyword bipartite) | top-10 | 关键词图召回 |
| RRF 融合 | top-10 | 三路融合结果 |
| Rerank (Qwen3-Rerank-8B) | top-10 | 跨编码器精排 |
| Current evidence_set | 全部 | 确保现有 gold 被纳入判断 |

合并去重后预期每 query pool 大小 = **20–40 docs**。`[project_inference]`

### 5.2 判断量估算

- 130 条 × 30 docs/pool (avg) = **~3900 judgments**
- 按人工 30 秒/judgment,~32.5 小时(单人)`[project_inference]`
- 可用 2 annotator 独立判一致性抽样(见 §6.3)分担 `[established_ir_convention]`

### 5.3 Pooling 不可少的原因

当前 v2.1 `evidence_set` 只登记 1 个 doc_id,其他正确 docs 被误认为 0。
如果不做 pooling,Gate B 会继承 Gate A 的"单 evidence"缺陷。`[project_inference]`

---

## 6. 标注指南

### 6.1 Annotator 资质

至少 2 人:主 annotator(任务负责人,材料/激光焊接领域)+ 副 annotator(用于
一致性抽样)。非专业背景的人不参与这批任务。`[project_inference]`

### 6.2 判断流程(每条 query)

1. 读 query_text,在心里形成"什么答案才算直接回答"(1 分钟内)
2. 按 pool 顺序过 20–40 个 chunk,逐个打 {0, 1, 2} `[established_ir_convention]`
3. 如果整 pool 都没有 relevance=2,打标 `q.no_gold=true`,交下一轮补 pool `[project_inference]`
4. 非常规情况(chunk 只是引用了 query 里的某个术语但完全不答)明确打 0

### 6.3 一致性抽检

- 在 130 条中随机抽 **20 条**,让两位 annotator 独立打分 `[established_ir_convention]`
- 计算 **Cohen's κ on binary collapsed {0, 1+2}**,通过门槛 **κ ≥ 0.6** `[established_ir_convention]`
- 若 κ < 0.6,需要开会统一判断口径,按统一后口径重标那 20 条,再抽 10 条
  复核 `[project_inference]`

### 6.4 记录字段(每条 query)

保存在 `artifacts/eval_audit/gateb_goldset.jsonl`(每行一个 query record):

```json
{
  "query_id": "q_g0001",
  "query_text": "...",
  "source_stratum": "S1|S2|S3|S4",
  "source_template_id": "simple:0 | null",
  "original_query_id": "q_0158 | null",
  "notes": "短注释,特殊情况才填",
  "annotator_id": "a1",
  "reviewer_id": "a2 | null",
  "qrels": [
    {"doc_id": "mat_abc", "relevance": 2, "source_hint": "bm25+dense+rerank"},
    {"doc_id": "mat_def", "relevance": 1, "source_hint": "bm25"}
  ],
  "notes_for_future_tolf": "此 query 的分级证据链期望(非必填,TOLF 用)"
}
```

---

## 7. 验收标准(Gate B pass criteria)

### 7.1 数量门

- `|goldset| ≥ 100` `[repo_anchor]`(用户约定)
- `|goldset| ≤ 200` `[repo_anchor]`(用户约定)

### 7.2 覆盖门

- 每个 template_id ≥ 5 条 `[project_inference]`
- 每个 difficulty ≥ 20 条 `[project_inference]`
- S4 non-template ≥ 20% of total `[project_inference]`

### 7.3 质量门

- Cohen's κ (binary collapsed) **≥ 0.6** on 20-query overlap sample
  `[established_ir_convention]`
- 每条 query 至少 **1 个 relevance=2 的 gold doc**,否则标 `no_gold=true`
  并从 Gate B 正评测里排除(记到 corpus gap,触发 Wave 2 候补)`[project_inference]`
- 每条 query 的 pool 至少有 **10 个判断**,避免过稀薄的 pool `[project_inference]`

### 7.4 指标门(Gate B 通过即解锁是否触发 C)

在 goldset 上跑 `eval_retrieval_runtime.py`,记录三组指标:

| 条件 | 记录 |
|------|------|
| 当前 Qwen 链路(no expansion / no rerank) | 基线 R@5、MRR、per_difficulty |
| Qwen 链路 + rerank | 带 rerank 的 Recall / MRR |
| Qwen 链路 + rerank + expansion | 当前主力配置 |

若三组的 **R@5 都低于 0.30** 且差异 < 5pp,说明问题不在"链路组合",
**触发 C**(`bge-m3 + bge-reranker-v2-m3` 对照组)。`[project_inference]`

若 Qwen 链路主力在 goldset 上达到 R@5 ≥ 0.40,**视为 C 的触发条件未满足**,
可以绕过 C 直接进 Wave 2 / Wave 3 讨论。`[project_inference]`

---

## 8. 第一批优先抽样清单(Priority Sample)

### 8.1 抽样对象(40 条)

| 层 | 条数 | 来源 | 优先级 |
|----|----:|------|------|
| S2 duplicate-heavy 优先 | 10 | 70 dup types 里 top-10 fanout 的 unique query_text,各采 1 条 | P0 |
| S3 hard-single 优先 | 10 | 326 hard-single 里随机抽 10 条 | P0 |
| S1 per-template 样本 | 16 | 8 template_id × 2 | P1 |
| S4 seed(示例性) | 4 | 用户编写 4 条非模板 query 作为冷启动 | P1 |
| **小计** | **40** | | |

具体 query_id 落盘到
`artifacts/eval_audit/gateb_initial_candidates.jsonl`(Task 7 产出)。

### 8.2 为什么第一批要先做 S2 / S3

- S2 直接验证"fanout-158 下,158 个 doc 是不是都真的 relevant"。这个判断决定
  qrels 的根本结构——如果只有 3-5 个真正 relevant,Gate A 的 R@5 天花板就不是
  3.2% 而是 15-30%;如果都是 relevant,模型要在 top-5 里覆盖 158 个正确答案就
  是强人所难,Gate B 必须换抽样方式。`[project_inference]`
- S3 验证 hard 定义是否现实可满足。`[project_inference]`

S1 / S4 在第二批做,避免 annotator 在初期就陷入大量重复模板。
`[project_inference]`

---

## 9. 后续 Gate B 执行步骤(本文档后)

1. **执行 Task 7**:跑一次性脚本从 audit JSON 生成 initial candidates(40 条) `[repo_anchor]`
2. 用户人工编 S4 冷启动样本(4 条) `[repo_anchor]`
3. 构造每条 query 的 pooling candidate(`gateb_build_pool.py`,Gate B 下阶段工具,非本 Gate scope) `[project_inference]`
4. Annotator A 独立标注 40 条 pool `[project_inference]`
5. Annotator B 独立标注其中 10 条的 overlap sample `[established_ir_convention]`
6. 计算 κ,若过门继续 S1 其余 64 条 + S4 其余 26 条 + S2/S3 补到 20 `[established_ir_convention]`
7. 产出 `gateb_qrels.tsv` + `gateb_goldset.jsonl` + kappa 报告 `[project_inference]`
8. 用 `eval_retrieval_runtime.py --queries gateb_goldset.jsonl --template-flags <opt>` 跑三组条件 `[repo_anchor]`
9. 按 §7.4 判断是否触发 C `[repo_anchor]`

---

## 10. 风险与回退

- **风险 A**:S2 抽样结果显示 fanout=158 大多数不是真 relevant。回退:放弃
  v2.1 的多对多 qrels 思路,Gate B 只保留 S1+S3+S4 共 ~120 条,S2 归入 `
  corpus_gap_report`,不入 goldset `[project_inference]`
- **风险 B**:κ < 0.6 且经过统一口径仍未过。回退:请领域专家直接 dictate
  判断口径,annotator 按 rulebook 执行,再测 κ `[established_ir_convention]`
- **风险 C**:goldset 最终 < 100(过多 no_gold)。回退:触发 Wave 2 补候选
  query,本 Gate 不扩 scope `[repo_anchor]`

---

## 11. 与 Gate A 产物的对接

| Gate A 产出 | Gate B 如何使用 |
|------------|---------------|
| `audit_v21_20260418.json` → `template_match.per_template_count` | S1 分层比例依据 |
| `audit_v21_20260418.json` → `bad_cases.duplicate_query_text_across_docs.samples` | S2 优先抽样池 |
| `audit_v21_20260418.json` → `bad_cases.hard_with_single_doc_evidence.samples` | S3 优先抽样池 |
| `audit_v21_20260418_template_flags.jsonl` | `eval_retrieval_runtime --template-flags` 的直接输入 |

---

## Appendix A — 来源标签分类统计

本文档共出现的规则来源分布:

- `[repo_anchor]` 条目:与用户指令 / Wave 1 audit / TOLF §9.4.x 一致的事实
- `[established_ir_convention]` 条目:TREC / BEIR / sentence-transformers 通行
  做法,训练知识内化
- `[project_inference]` 条目:基于 Gate A 证据的项目特化选择

一旦 WebSearch/WebFetch 恢复,Gate B 下一阶段可做的一手验证 URL 清单:

- https://github.com/beir-cellar/beir(qrels 结构与 evaluation 入口)
- https://www.sbert.net/docs/package_reference/evaluation.html
  (`InformationRetrievalEvaluator` 接口)
- https://trec.nist.gov/data/qrels_eng/(qrels 历史格式与 pooling 文档)

验证应做的比对项:

1. Cohen's κ ≥ 0.6 是否仍是通用门槛
2. graded relevance {0,1,2} 是否仍是 TREC 主流
3. pooling depth=10 在 shallow-pool 设置下是否足以代表分布

---

## 2026-04-25 Drift-Judge Addendum

### Formal conclusion

- `BASELINE_METRICS_phase5_qwen3.json` 与两个 canary 指标文件**只能作方向性参考**，不可继续用作 8B / 4B reranker 的决策依据。
- 已签核原因：full v2.1 存在极端 fanout + 单 doc evidence 失真；canary30 同时受低 fanout 偏样与 `n=30` 小样本波动影响。
- Gate B firstpass-100 说明“多文档 pooled judging 会显著抬高可解释信号”，但它还不是这轮的最终模型选择证据，因为当前缺少**同一 pooled qrels 下的 8B vs 4B 成对对照**。

### DO NOW slice（本轮收口后唯一执行面）

启动 **40-query Gate B pilot**，沿用本计划已锁定的首批组合，不再重开 full v2.1 / canary 争论：

- `S2 duplicate-heavy = 10`
- `S3 hard-single = 10`
- `S1 template-balanced = 16`
- `S4 non-template seed = 4`

### Pilot 执行约束

1. **同一套 pooled judgments 同时服务 8B 与 4B**，禁止先跑一个模型、后补另一套 qrels。
2. 每条 query 仍按 §5 的 pool union 规则构造候选，judging 保持 graded `{0,1,2}`。
3. 本 pilot 的输出必须记录完整 provenance（query 文件、slice、template flags、rerank model、主要 CLI 配置），避免再次出现“结果有数、来源不可比”。
4. 通过门槛沿用 Tank 要求：overlap 子集 binary-collapsed `κ >= 0.6`、每条 query `>=10` judged candidates、8B / 4B 共享同一 qrels。

### Pilot acceptance checks（冻结，执行前后都按此验）

> 这组检查是 Gate B 40-query pilot 的唯一验收合同；未全部通过即不进入模型结论讨论。

1. **AC-01 Frozen slice**
   - `gateb_goldset` 必须且仅包含 40 条 query。
   - 分层固定为 `S1=16, S2=10, S3=10, S4=4`，不得临时改配比。
2. **AC-02 Shared qrels（8B/4B 一致）**
   - 8B 与 4B 必须引用同一 query_id 集合。
   - 每个 query 的 `(doc_id, relevance)` judgment 集合必须逐条一致。
3. **AC-03 Judgment depth**
   - 每条 query 的 judged docs 数量必须 `>=10`。
4. **AC-04 Overlap / κ**
   - overlap 子集规模必须 `>=10`（40-query pilot 最低 25% 覆盖）。
   - binary-collapsed Cohen’s κ 必须 `>=0.6`。
5. **AC-05 Provenance completeness**
   - Goldset 记录需包含 `query_id/query_text/source_stratum/annotator_id/created_at`。
   - Eval 产物需包含 `run_provenance`，并至少记录：queries path+hash、slice(offset/limit)、template flags、rerank model、核心检索参数（top_k/recall_top_n/rerank_top_n/use_rerank/use_expansion）。
6. **AC-06 Fail-fast rule**
   - 任一 AC 失败，pilot 结论状态固定为 `REJECTED`，仅允许修复数据/标注工件后重跑，不允许先讨论默认模型切换。

### Deferred（不在本 slice 内）

- `eval_queries_v2.1.jsonl` 的 181 unique dedup 重跑
- canary30 fanout annotation
- full v2.1 / canary30 的任何 reranker 默认切换结论
- 扩大到 100-query / 130-query Gate B 正式集
