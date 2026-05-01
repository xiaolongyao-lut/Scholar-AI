# Plan: v2.1 eval dataset audit + template/non-template 评测分桶 (Wave 1)

## Context

今天 Phase 5 full v2.1 3269q eval 跑出 Recall@5=0.022,远低于 canary 30q 的 0.1667,且比旧 broken baseline 的 0.0667 还低。infra 干净(smoke 6/6, 0 零行, rerank timeout 0/3269)
,怀疑指向 query 侧:

- 手动核了 `eval_queries_v2.1.jsonl`:3269 条 query 只有 **181 个 unique query_text**(5.5%)。每条 query 都由 `build_eval_corpus.py` 的固定模板(simple 3 + medium 3 + hard 2 = **8 个模板**)× 关键词填充生成,同一模板在不同 material 上产出相同字面 query 高达 158 次,显著偏离 TREC/BEIR 对 qrels 的成熟要求。
- doc_id coverage 已确认 100%(evidence_set 的 doc_id 全部能在 `output/chunk_store/*.json` 里找到),所以主因**不是**数据丢失。

用户要求:修评测先于调模型。Wave 1 落**已知模板精确识别 + 评测按 template/non-template 分桶**两件事,为后续建 100-200 条人工小金标集、以及 Wave 2 启发式发现未知模板、Wave 3 query instruct / IR evaluator 升级打好指标基础。

## 目标(Wave 1 only)

1. 独立 audit 工具,对任意 eval jsonl + chunk_store 做一次性体检并产出可机读 JSON + 可读摘要。
2. audit 产物里包含每条 query 的 `is_template` + `template_id` 标签 → 以 JSONL sidecar 形式导出。
3. `eval_retrieval_runtime.py` 支持可选 `--template-flags` 参数,加载 sidecar 后在 `aggregate_metrics` 里额外给出 `per_template_bucket`(template vs non_template)指标,不改动 per_difficulty 逻辑。

**不做(留给后续 wave)**:
- Wave 2 的启发式未知模板发现 / n-gram 聚类。
- Wave 3 的 query instruct、IR evaluator 升级(NDCG/MAP)、embedding config 统一(`chunk_vector_store.py` vs `layers/r_layer_hybrid_retriever.py` 默认 model 不一致)。
- 人工小金标集标注工具 —— Wave 1 产出审计结果后,用户按 TREC/BEIR 口径手工写样本文件,无需工具。

## 改动范围

### 改动 1 — 新文件 `scripts/audit_eval_dataset.py`

**CLI**

```
python scripts/audit_eval_dataset.py \
  --queries eval_queries_v2.1.jsonl \
  --chunk-dir output/chunk_store \
  --output output/eval_query_audit_v21.json \
  --flags-output output/eval_query_audit_v21_template_flags.jsonl \
  --top-n 10
```

- `--queries` 必填,eval jsonl 路径。
- `--chunk-dir` 可选。未给则跳过 doc_id coverage 检查,相关字段置 `null`。
- `--output` 默认 `output/eval_query_audit.json`。
- `--flags-output` 默认与 `--output` 同名但后缀 `_template_flags.jsonl`。
- `--top-n` 控制 `top_repeated_query_text` / `top_sources_by_fanout` 的返回条数,默认 10。

**核心函数(纯函数 + 类型标注,便于单测)**

```python
def load_queries(path: Path) -> list[dict]: ...
def load_chunk_material_ids(chunk_dir: Path) -> set[str]: ...

# 直接 from build_eval_corpus import QUERY_TEMPLATES
# 把 {topic}/{topic1}/{topic2}/{topic3} 替换为 (.+?) 编译正则
def compile_template_patterns(templates: dict[str, list[str]]) -> list[tuple[str, str, re.Pattern]]:
    """返回 [(difficulty, raw_template, compiled_regex), ...]"""

def classify_query(query_text: str, patterns) -> tuple[bool, str | None]:
    """返回 (is_template, template_id)。template_id 形如 'simple:0' / 'hard:1'。"""

def compute_totals(queries) -> dict: ...
def compute_per_difficulty(queries) -> dict: ...
def compute_doc_id_coverage(queries, material_ids: set[str] | None) -> dict: ...
def compute_top_repeated_query_text(queries, top_n: int) -> list[dict]: ...
def compute_per_source_fanout(queries, top_n: int) -> dict: ...
def compute_template_match(queries, patterns) -> dict: ...
def collect_bad_cases(queries, coverage_result, patterns) -> list[dict]: ...

def run_audit(queries_path, chunk_dir, top_n) -> tuple[dict, list[dict]]:
    """orchestrates the above; returns (audit_json, per_query_flags)."""

def print_stdout_summary(audit: dict) -> None: ...
```

**Template 检测(Wave 1 主方案)**

- 直接 `from build_eval_corpus import QUERY_TEMPLATES` — 权威来源,8 个模板。
- `{topic}` / `{topic1}` / `{topic2}` / `{topic3}` 在模板里替换为 non-greedy `(.+?)`,头尾加锚点 `^…$`。中文无需转义。
- 一条 query 命中**第一个**匹配到的 template 就停,优先顺序按 simple → medium → hard(按字典 order)。
- `template_id` 用 `"{difficulty}:{index}"` 形式,便于 aggregation 按 difficulty 二次下钻(可选)。
- Wave 1 不做启发式回退;未命中 query 统计在 `non_template_count`,留给 Wave 2。

**Bad case 规则(仅 2 + 3 + 4)**

- **type `duplicate_query_text_across_docs`**:同一 `query_text` 指向 ≥ 6 个不同 doc_id。每类样一个,输出 `{"type", "query_text", "distinct_doc_count", "sampled_doc_ids"}`。阈值用常量 `BAD_CASE_MULTI_DOC_THRESHOLD = 6` 便于调整。
- **type `missing_doc_id`**:evidence_set 里 doc_id 不在 chunk_store。当前已知 0 条,仍保留统计 + 样本字段。
- **type `hard_with_single_doc_evidence`**:`difficulty_level == "hard"` 但 `len(evidence_set) <= 1`。单条 evidence 不足以支撑"hard"语义。

每类最多 sample 5 条(`BAD_CASE_SAMPLE_LIMIT = 5`),避免 JSON 膨胀。

**Stdout 摘要格式**

```
[audit] eval_queries_v2.1.jsonl
  total=3269  unique_text=181  unique_doc_ids=168  source_titles=131
  per_difficulty: simple=1488 medium=1455 hard=326
  template_match: matched=3269/3269 (100.0%)  non_template=0
  per_template (top 5): ...
  doc_id_coverage: 168/168 hit  missing=0
  fanout: min=3 median=20 mean=19.5 max=23
  bad_cases:
    duplicate_query_text_across_docs: 164 types, sampled 5
    missing_doc_id: 0
    hard_with_single_doc_evidence: 326 (100%)
  wrote output/eval_query_audit_v21.json  (15 kb)
  wrote output/eval_query_audit_v21_template_flags.jsonl  (245 kb)
```

**输出 JSON schema**

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-18T12:34:56Z",
  "input_queries": "eval_queries_v2.1.jsonl",
  "input_chunk_dir": "output/chunk_store",
  "totals": {
    "total_queries": 3269,
    "unique_query_text": 181,
    "unique_doc_ids_in_evidence": 168,
    "unique_source_titles": 131
  },
  "per_difficulty": {
    "simple": {"count": 1488, "unique_text": 99, "template_matched": 1488},
    "medium": {"count": 1455, ...},
    "hard": {"count": 326, ...}
  },
  "doc_id_coverage": {
    "total_distinct_doc_ids": 168,
    "hit": 168,
    "missing": 0,
    "missing_samples": []
  },
  "top_repeated_query_text": [
    {"query_text": "激光焊接的最新研究进展", "count": 158, "difficulty": "simple"},
    ...
  ],
  "per_source_fanout": {
    "mode": "by_material_id",
    "unique_sources": 168,
    "min": 3,
    "median": 20,
    "mean": 19.46,
    "max": 23,
    "top_sources_by_fanout": [{"material_id": "mat_...", "count": 23}, ...]
  },
  "template_match": {
    "templates_checked": 8,
    "matched": 3269,
    "non_template": 0,
    "non_template_samples": [],
    "per_template_count": {
      "simple:0": 158, "simple:1": 158, ...
    }
  },
  "bad_cases": {
    "duplicate_query_text_across_docs": {
      "type_count": 164,
      "samples": [{"query_text": "...", "distinct_doc_count": 158, "sampled_doc_ids": [...]}]
    },
    "missing_doc_id": {"type_count": 0, "samples": []},
    "hard_with_single_doc_evidence": {"type_count": 326, "samples": [...]}
  }
}
```

**Template flags sidecar (`..._template_flags.jsonl`) schema**

```jsonl
{"query_id": "q_0001", "is_template": true, "template_id": "simple:0"}
{"query_id": "q_0002", "is_template": true, "template_id": "simple:1"}
...
```

### 改动 2 — 新文件 `tests/test_eval_dataset_audit.py`

单测(纯函数优先,fixture 用内联 dict 构造小样本,不依赖 jsonl 文件):

- `test_compile_template_patterns_matches_known_literal` — `"激光焊接的最新研究进展"` 必中 `simple:0`。
- `test_compile_template_patterns_rejects_non_template` — `"what is the weld penetration of Ti-6Al-4V in CW laser at 3 kW"` 返回 `(False, None)`。
- `test_compute_totals_basic` — 3 条 query 返回正确 counts。
- `test_compute_doc_id_coverage_missing_path` — evidence 里有一个不在 material set 的 doc_id → 报告 `missing=1`。
- `test_compute_doc_id_coverage_no_chunk_dir` — material_ids=None 返回 coverage=None。
- `test_collect_bad_cases_multi_doc` — 构造 6 条相同 query_text 指向 6 个不同 doc_id → 触发 `duplicate_query_text_across_docs`。
- `test_collect_bad_cases_hard_single_doc` — 一条 hard + 单 doc evidence → 触发 `hard_with_single_doc_evidence`。
- `test_classify_query_returns_template_id` — 覆盖 simple / medium / hard 各一例。
- `test_run_audit_returns_schema_v1` — 跑一个 mini 3-query 场景,断言 JSON 里 `schema_version == 1` 且所有必填顶层 key 存在。

目标 ≥ 9 cases,全部 pytest 绿,<1s。

### 改动 3 — `eval_retrieval_runtime.py` 加 `--template-flags` 可选参数

**CLI 层(argparse)**

```python
parser.add_argument(
    "--template-flags",
    type=str, default=None,
    help="可选,audit 工具产出的 template_flags.jsonl;载入后按 template/non_template 分桶输出指标。",
)
```

**载入点**

在主流程(~460 行附近,`aggregate_metrics` 调用之前)把 flags 读入 `dict[query_id, is_template]`,然后给每条 result 附加 `"is_template"` 字段(基于 `q["query_id"]` 查找;找不到则 `False`,记为 non_template)。

**aggregate_metrics 扩展**

在 `per_difficulty` 计算后、return 前加:

```python
if any("is_template" in r for r in results):
    per_template_bucket = {}
    for flag in [True, False]:
        subset = [r for r in results if r.get("is_template") is flag]
        if not subset:
            continue
        key = "template" if flag else "non_template"
        per_template_bucket[key] = {
            "count": len(subset),
            "recall_at_5": round(mean(r["recall_at_5"] for r in subset), 4),
            "mrr": round(mean(r["mrr"] for r in subset), 4),
        }
    metrics["per_template_bucket"] = per_template_bucket
```

不加字段时(未传 `--template-flags`)输出 schema 完全不变 → 向后兼容。

### 改动 4 — `tests/test_eval_runtime.py` 加 bucketing case

- `test_aggregate_metrics_per_template_bucket` — 构造 4 条 result,2 条 `is_template=True` + 2 条 `is_template=False`,断言 `per_template_bucket.template.recall_at_5` 和 `non_template` 都正确,且 template 组 recall 可以与 non_template 组明显不同。
- `test_aggregate_metrics_no_template_flag_preserves_schema` — results 都没有 `is_template` 字段时,返回 dict 里**不出现** `per_template_bucket` 键。

### 改动 5 — `.gitignore` 追加

确保 audit 产物不入版本库。`output/` 已在 `.gitignore:8`,但 flags sidecar 也在 `output/` 下,所以**不需要改 .gitignore**。如果用户后续决定把 audit JSON 提交到仓库作为基线,再单独开白名单即可。

## 关键文件清单

- **新** `scripts/audit_eval_dataset.py`(~250 行)
- **新** `tests/test_eval_dataset_audit.py`(~200 行,9+ cases)
- **改** `eval_retrieval_runtime.py`(argparse + aggregate_metrics 扩展,+~25 行)
- **改** `tests/test_eval_runtime.py`(+2 cases,+~30 行)
- **复用**:
  - `build_eval_corpus.py:78` 的 `QUERY_TEMPLATES`(直接 import,不拷贝)
  - `eval_retrieval_runtime.py:96` 现有 `aggregate_metrics` 结构(per_difficulty 同款模式)
  - `build_eval_corpus.py:23` 的 `load_all_chunks`(audit 只要 material_id 集合,自己写轻量版;不引入完整 chunks 加载)

## 不做 / 留待后续

- Wave 2 启发式未知模板发现(n-gram / 骨架聚类)—— 新建 plan 再接。
- Wave 3 IR evaluator 升级到 Precision/NDCG/MAP / query instruct 非对称编码 / embedding model 默认值统一 —— 独立 plan。
- 100-200 条人工小金标集标注工具 —— 用户手工写样本文件,Wave 1 不提供。
- 已知 `layers/r_layer_hybrid_retriever.py` 默认仍是 `BAAI/bge-m3` 而 `chunk_vector_store.py` 是 `Qwen/Qwen3-Embedding-8B` —— **埋点在 plan 文档**,Wave 1 不修改(改动面扩散,应独立 plan)。

## 验证步骤

```bash
# ① 单元测试(audit + 老 eval runtime 分桶新测试)
cd C:/Users/xiao/Desktop/tools/Modular-Pipeline-Script-cleanpush
pytest tests/test_eval_dataset_audit.py tests/test_eval_runtime.py -q
# 期望:全绿,~1s

# ② 跑 audit 产出 JSON + flags
# 注意 cleanpush 没有 output/chunk_store/(output/ 在 .gitignore);
# 需要先从原 repo 软/硬复制:
#   cp -r ../Modular-Pipeline-Script/output/chunk_store output/
python scripts/audit_eval_dataset.py \
  --queries eval_queries_v2.1.jsonl \
  --chunk-dir output/chunk_store \
  --output output/eval_query_audit_v21.json \
  --flags-output output/eval_query_audit_v21_template_flags.jsonl
# 期望:
#   stdout 摘要 total=3269, unique_text=181, template_match=100%, bad_cases 有计数;
#   JSON 按 schema_version=1 输出;
#   sidecar JSONL 3269 行,每行 {query_id, is_template, template_id}

# ③ 跑一次带 template-flags 的 eval 验证 bucketing 正常工作
# 由于 full eval 代价高(>80min),先用 canary 样本(需要重建 canary30 文件,或从原 repo 拷贝)
python eval_retrieval_runtime.py \
  --queries eval_queries_v2.1_canary30.jsonl \
  --expansion --strict-cache-guard \
  --template-flags output/eval_query_audit_v21_template_flags.jsonl \
  --output BASELINE_METRICS_canary30_with_template_bucket.json
# 期望:JSON 里 per_template_bucket.template 存在且 count == 30
#      per_template_bucket.non_template 不存在(v2.1 全是模板)

# ④ commit + push 到 codex/v21-eval-audit
git add scripts/audit_eval_dataset.py tests/test_eval_dataset_audit.py \
        eval_retrieval_runtime.py tests/test_eval_runtime.py
git commit -m "feat(eval): v2.1 dataset audit + template/non-template bucketing (Wave 1)"
git push -u origin codex/v21-eval-audit
```

## 交付顺序

0. **建回档点**:
   - 保留已有分支 `codex/v21-eval-audit`(不切换)。
   - `git tag -a pre-wave1-eval-audit-20260418 -m "backup before Wave 1 audit tool"`(与 `pre-v21-eval-audit-20260418` 并存,分别标记"审计分支初建"和"开始 Wave 1 编码"两个节点)。
0.5. **成熟规范核对**(一次性文档 read,不改代码):
   - BEIR / TREC qrels:`queries` + `corpus` + `qrels` 三件套,qrels 是 tab-separated `query_id doc_id relevance` 的金标准。本 audit 的 `evidence_set` 结构与其语义一致(relevance 隐含 1)。
   - Sentence-Transformers `InformationRetrievalEvaluator`:接受 `queries: dict[qid, text]` + `corpus: dict[cid, text]` + `relevant_docs: dict[qid, set[cid]]`,输出 MRR / Recall / NDCG / MAP / Accuracy@k。本 plan Wave 1 **不实现这些额外指标**,只埋注释点,Wave 3 接入。
   - 确认本 plan 的 JSON schema 与上述规范语义对齐(evidence_set ↔ qrels,query_text ↔ queries,material_id ↔ doc_id),**不引入新的字段歧义**。
1. 写 `scripts/audit_eval_dataset.py` 主体(纯函数 + CLI)。
2. 写 `tests/test_eval_dataset_audit.py`(9+ cases),pytest 绿。
3. 改 `eval_retrieval_runtime.py` 加 `--template-flags` + bucket。
4. 加 `tests/test_eval_runtime.py` 新 2 case,pytest 绿。
5. 从原 repo `cp -r ../Modular-Pipeline-Script/output/chunk_store output/` 准备 audit 数据(不入 git)。
6. 跑 audit,inspect JSON + flags sidecar。
7. 跑 canary 带 `--template-flags`,inspect per_template_bucket。
8. commit + push `codex/v21-eval-audit` 分支。
9. 给用户:audit JSON 摘要 + canary 分桶结果,决定下一步(走 Wave 2 / 建人工金标集 / 其他)。

## 风险与回退

- **Template import 路径**:`build_eval_corpus.py` 在 repo root。`scripts/audit_eval_dataset.py` 用 `from build_eval_corpus import QUERY_TEMPLATES`;pytest 正常能找,CLI 需要 `PYTHONPATH=.` 或用 `sys.path` 修正。回退:小函数 `_load_templates()` 动态读 `build_eval_corpus.py` 源码用 `ast.parse` 抽取(过度工程,不做)。
- **Chunk store 绝对路径跨 repo**:cleanpush 没有 `output/chunk_store/`,验证步骤需手工复制。audit 脚本对 `--chunk-dir` 不存在或为空要优雅 fallback(coverage=None,不 raise)。
- **JSON schema 演进**:现版本 `schema_version=1`,将来加字段用 `schema_version=2` + 兼容字段,不默改现有字段语义。
- **per_template_bucket 与 per_difficulty 的组合基数爆炸**:Wave 1 只做一级 bucket(template/non_template),不做二级 (template × difficulty)交叉。如需要交叉,Wave 2 独立加。
