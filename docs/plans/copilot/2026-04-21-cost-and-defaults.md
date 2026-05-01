# 2026-04-21 团队执行计划：核心算法降本 + LLM 默认参数 + 隐性问题清理

> 用户授权：本次包括重构在内全部改动均已授权（Morpheus block 已解除，仅本会话）。
> 优先级：能用 → 降本 → 增效。背景：rerank 一日 250 元，必须立刻见效。

---

## 0. 本次会话内由 Copilot 直接完成（不交给 team）

| # | 项 | 文件 | 状态 |
|---|---|---|---|
| C1 | CJK bigram 查询修复（Inspiration sparks 三句中文返回不同结果） | `inspiration_engine.py:131` | ✅ 已落地并冒烟通过 |
| C2 | Rerank 持久化磁盘缓存层（跨进程复用，预计 60-90% 调用降本） | `rerank_cache.py` + `reranker_client.py` | ✅ 已完成 |
| C3 | Rerank 调用成本埋点 → `output/rerank_cost.jsonl` | `reranker_client.py` | ✅ 已完成 |

---

## 1. P0 — 降本（Team，本周必须落地）

### 1.1 Chunk store 文件膨胀重构（13 MB 单文件 → 每论文一份 JSONL）

**状态**：⚠️ **MIGRATION COMPLETED, BUT EVALUATION BROKEN** (2026-04-26 regression found)

**痛点**：`output/chunk_store/{project_id}_chunks.json` 当前单文件 13 MB，每次写入全量加载-修改-写回，并发写入随时损坏。

**方案**（用户已授权重构）：
- 目录结构：
  ```
  output/chunk_store/{project_id}/
      manifest.json                     # {material_id -> relative_path, total_chunks, sha256}
      {stem}_{md5(material_id)[:8]}.jsonl  # 每论文一份，每行一个 chunk
  ```
- 文件命名：`{stem}_{md5(material_id)[:8]}.jsonl`（防 stem 撞名 + 防文件名爆长）。
- 写入：单论文 JSONL 原子写（写到 `.tmp` 再 `os.replace`）+ manifest 记录后 fsync。
- 读取：单论文按需加载；全 corpus 视图通过流式拼装。

**接口约束**：`routers/resources_router.py` 的 15 处调用点（行号 318/373/1062/1118/1120/1377/2113/2131/2134/2165/2168/2197/2200）签名不变。仅修改 `_get_chunk_store_path`、`_load_chunk_store`、`_save_chunk_store` 三个 helper（行 207-238）。

**迁移**：写一次性脚本 `scripts/migrate_chunk_store_to_jsonl.py`，读旧文件 → 拆 JSONL + manifest → 旧文件改名 `.legacy.bak`，可回滚。

**验收**：
1. ✅ 现有 109 篇语料迁移后 manifest 完整 (159 materials across 5 projects)
2. ✅ **RESOLVED (2026-04-26)**: Eval queries regenerated and aligned with current corpus
3. ✅ 单论文新增/更新耗时从 O(总语料) 降到 O(单文件)

**2026-04-26 Alignment Repair (Oracle)**:
- **Issue**: Eval queries referenced stale material_ids after corpus rebuild
- **Root cause**: Query generation used outdated corpus snapshot
- **Resolution**: 
  - Updated `build_eval_corpus.py` to read v2 JSONL + manifest layout
  - Regenerated full eval corpus: 3,016 queries across 159 materials
  - Created aligned canary: `eval_queries_v2.1_canary30_ALIGNED.jsonl` (30 queries)
  - Validated 100% alignment: all material_ids exist in current corpus
- **Status**: §3.3 evaluation gate UNBLOCKED
- **Note**: Smoke test shows Recall@5=0.0 (separate issue, not alignment)
- Decision trail: `.squad/decisions/inbox/oracle-eval-alignment.md`

**2026-04-26 Original Regression Evidence**:
- Live canary30 smoke test: Recall@5=0.0 on all 5 queries
- Canary30 queries reference 26 material_ids: `mat_62dbd7b1f80e`, `mat_153a9270f602`, etc.
- Post-migration chunk_store has 159 materials with different IDs: `mat_1f5242e1034f`, `mat_f76878df9d8d`, etc.
- Material ID hashing changed during migration: `md5(material_id)[:8]` produces different prefixes
- All eval query files (`eval_queries_v2.0.jsonl`, `eval_queries_v2.1_canary30.jsonl`, etc.) now reference stale material_ids

Facts:
- Chunk store migration completed successfully (5 projects, 159 materials, manifest structure valid)
- Evaluation corpus/qrels alignment restored via query regeneration (data-side repair)
- Aligned canary30 available for immediate §3.3 gate testing

Decisions:
- ✅ Query regeneration chosen over corpus restoration (no pre-migration backup available)
- ✅ Data-side repair preferred over code shims (maintainability)
- Full query set regeneration available: `eval_queries_v2.1_REGENERATED.jsonl` (3,016 queries)

Open:
- ~~Retrieval quality investigation: Recall@5=0.0 on aligned canary (embedding cache? chunking?)~~ → **ROOT CAUSE IDENTIFIED (2026-04-26 Trinity)**
  - Rebuilt embedding cache with model binding + oversize filtering (11/11,447 chunks filtered)
  - Canary run (rerank ON): Recall@5=0.0, Recall@10=0.0, MRR=0.0
  - **Isolation test (rerank OFF)**: Recall@5=0.8, Recall@10=0.8, MRR=0.398
  - **Root cause confirmed**: Reranker (`netease-youdao/bce-reranker-base_v1`) is actively harmful, eliminating 100% of correct results from top-5
  - RRF fusion baseline is strong (0.8 recall without reranking)
  - See: `.squad/decisions/inbox/trinity-no-rerank-canary.md`
- **Immediate action required**: Disable reranker by default until model swap or logic audit
- Decision: use canary30 or full 3,016-query set for §3.3 evaluation

Next:
- ~~Trinity/Morpheus: Isolate ranking defect — run canary with `--no-rerank` to separate recall vs rerank impact~~ → **COMPLETED**
- Trinity: Disable `DEFAULT_USE_RERANK` in `eval_retrieval_runtime.py` or switch to `qwen3-rerank` model
- Trinity: Execute §3.3 Phase 6 evaluation with `eval_queries_v2.1_canary30_ALIGNED.jsonl` (after reranker fix)

---

### 1.2 Rerank 候选池上限与动态 TopK（`eval_retrieval_runtime.py` + `hybrid_search_runtime.py`）

**状态**：✅ 已完成（2026-04-21，本轮）

**痛点**：进入 rerank 的候选数量没有显式上限，遇到大候选池单次成本翻倍。

**方案**：
- 新增环境变量 `RERANK_PRE_TOPN`（默认 30）、`RERANK_PRE_TOPN_HARD_CAP`（硬上限 60）。
- 进入 rerank 前按融合分排序截断到 `RERANK_PRE_TOPN`。
- 信号触发放大（仅在 query 短于 6 字符 / Top1-Top2 分差 < 0.05 / hybrid 命中数 < 5 时）扩到 60。
- 与 `ai_cost_profile`：`aggressive` 模式强制 20，`quality` 模式默认 50。

**验收**：在 109 篇全量评测上，平均 rerank 候选 ≤ 35，Recall@5 / MRR 无显著下降（相对基线 ≥ 98%）。

---

### 1.3 Rerank 日预算上限（硬阀门）

**状态**：
- ✅ 已完成（2026-04-25：`reranker_client.py` 与 `rerank_budget.py` 已收口到同一预算合同）
- ✅ 回归验证：`py -m pytest tests\test_rerank_budget.py tests\test_rerank_short_circuit_and_budget.py tests\test_rerank_budget_concurrency.py tests\test_reranker.py` → `39 passed`

**理念对齐 §2.2.3**：USD 不是硬阀门（vendor 价格波动 + 用户自带 key），调用次数与 token 量才是稳定可控的硬约束。

**方案**：
- `reranker_client.py` 内新增 `RerankBudgetGuard`：按日历日累计调用次数和近似 token 数。
- **主硬阀门**：`RERANK_DAILY_CALL_CAP`（默认 5000）— 调用次数到顶即 fallback。
- **次硬阀门**：`RERANK_DAILY_TOKEN_CAP`（默认 1_500_000）— token 累计到顶即 fallback。
- **软阀门 / 仅 telemetry**：`RERANK_DAILY_BUDGET_USD`（默认 5）— 超过仅打 WARN 与 jsonl `event=budget_soft_warn`，**不**触发 fallback；vendor 未知时跳过判断。
- 状态持久化到 `output/rerank_budget_state.json`（按日重置）。
- 触发硬 fallback 时 `rerank_cost.jsonl` 记录 `event=budget_capped` 并标 `cap_dim=call|token`，响应里加警告字段。

**验收**：构造一个超额回放场景，确认 fallback 触发且检索仍可用（仅排序退化为融合分）；USD 软阀门单独构造场景验证只 WARN 不 fallback。

Facts:
- `reranker_client.RerankBudgetGuard` 继续作为唯一预算语义源；`rerank_budget.py` 兼容 helper 已改为复用同一 state schema/path（`output/rerank_budget_state.json`）与同一 env 合同。 | Evidence: `reranker_client.py`, `rerank_budget.py`

Decisions:
- 保留 `rerank_budget.try_charge/remaining/log_call` 兼容入口，但不再维护第二套“仅 call budget / 旧文件名”的解释。 | Evidence: `rerank_budget.py`, `tests/test_rerank_short_circuit_and_budget.py::test_rerank_budget_helper_uses_aligned_state_and_token_cap`

Open:
- 无新增 open item；embedding/rerank 401 重构仍保持本节外。 | Evidence: 本节范围约束

Next:
- Tank 只需按本节合同验收 hard fallback（call/token）与 USD soft warn telemetry；无需扩展到检索链重构。 | Evidence: 本节验收条件 + `39 passed`

---

## 2. P0 — LLM 默认采样参数 + 前端覆盖（Team）

> **总目标**：杜绝"前端发什么后端用什么"的失控，统一收口到 `resolve_llm_params(task, user_overrides)`；同时把每次 LLM 调用的 token / 成本写到 `output/llm_cost.jsonl`，让 1.3 同样的预算阀门下一步可以管 LLM。

---

### 2.1 服务侧：默认 sampling params per task + 用户覆盖链路

#### 2.1.0 当前状态（接手前必读）

| 模块 | 状态 | 说明 |
|---|---|---|
| `llm_defaults.py` | ✅ Squad v0.9.1 已交付 | 暴露 `resolve_llm_params(task, user_overrides=None) -> {temperature, top_p, top_k, max_tokens}`；含 task 别名（summary/summarize/creative/focus_extract/default）；范围校验越界 raise `ValueError` |
| `routers/chat_router.py` | ✅ Squad v0.9.1 已交付 | 请求体加 `sampling` 字段；越界 422；已透传 user_overrides |
| `ai_sampling.py` + `tests/test_ai_sampling.py` | ⚠️ 历史孤儿 | 与 `llm_defaults.py` 功能重叠，**保留不删**（surgical-changes 原则）；任何新代码不要 import 它 |
| `layers/ai_adapter.py` | ✅ 已接入 | `_chat` helper 已统一接管 sampling + 成本埋点；仓内仅剩 helper 内部一处 SDK 调用 |
| `inspiration_engine.py` | ✅ 无待接入点 | 仓内无直接 `chat.completions.create(...)` 调用，当前无额外 sampling 接入切面 |
| `extractor_full.py` / 任何抽取链路 | ✅ 无待接入点 | `extractor_full.py` 当前无直接 LLM 调用；抽取链路未发现额外直连 OpenAI SDK site |
| 前端 Sampling 面板 + `~/.literature-lab/sampling.json` | ✅ 已接入 | `frontend/src/pages/Settings.tsx` + `frontend/src/services/samplingApi.ts` 已联通 `/sampling` |

**版本契约（不要修改）**：
```python
# llm_defaults.py
def resolve_llm_params(
    task: str,                       # chat|inspiration|extraction|summarization|rewrite (+aliases)
    user_overrides: dict | None = None,
) -> dict:
    """Returns dict with keys: temperature, top_p, top_k, max_tokens.
    Per-key override merge. Raises ValueError on out-of-range."""
```

服务端硬限（已在 `llm_defaults._validate_params` 中实现，不要重写）：
- `temperature ∈ [0.0, 2.0]`
- `top_p ∈ (0.0, 1.0]`
- `top_k ∈ [1, 200]`
- `max_tokens ∈ [1, MODEL_MAX_TOKENS]`，`MODEL_MAX_TOKENS = max(1, int(os.getenv("MODEL_MAX_TOKENS", "32768")))`

---

#### 2.1.1 子任务 A：服务侧 LLM 调用统一接入 `resolve_llm_params`

**状态**：✅ 已完成（2026-04-21，本轮，仅 `layers/ai_adapter.py` 范围）

**目标文件**：`layers/ai_adapter.py`（**主战场**）+ `inspiration_engine.py` + `extractor_full.py` + 任何剩余 `client.chat.completions.create` 直接调用点。

**前置盘点（必做，不可跳过）**：

```powershell
# 在仓库根执行，列出所有未接入点
.\.venv-1\Scripts\python.exe -c "import re,pathlib; [print(p, ln+1, l.strip()) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in str(p) and 'github\\' not in str(p) for ln,l in enumerate(p.read_text(encoding='utf-8',errors='ignore').splitlines()) if 'chat.completions.create' in l]"
```
**已知 7 个 site（layers/ai_adapter.py，需 verbatim 验证后再替换）**：

| # | 方法 | 行号近似 | 当前 temp | 特殊参数 | 目标 task | overrides |
|---|---|---|---|---|---|---|
| 1 | `extract_claims` | L194-205 | 0.3 | `response_format=json_object` | `extraction` | 无 |
| 2 | `verify_multimodal_support` | L240-247 | 0.1 | `max_tokens=10`（**二分类，必须保留**） | `extraction` | `{"temperature":0.1,"max_tokens":10}` |
| 3 | `extract_mechanisms` | L286-294 | 0.3 | `response_format=json_object` | `extraction` | 无 |
| 4 | `verify_evidence_chain` | L347-355 | 0.3 | `response_format=json_object` | `extraction` | 无 |
| 5 | `extract_innovation_points` | L402-411 | 0.3 | `response_format=json_object` | `extraction` | 无 |
| 6 | `classify_claim_boundary` | L459-468 | 0.2 | `response_format=json_object` | `extraction` | `{"temperature":0.2}` |
| 7 | `enhance_writing_association` | L568-576 | 0.3 | `response_format=json_object`（含尾逗号） | `rewrite` | 无 |

**实现规范**：在 `AIAdapter` 类内新增 `_chat` helper（只准内部调用，不导出）。

```python
# 在 layers/ai_adapter.py 顶部 imports 区追加（如已存在 import time 则跳过 time）
import time
from llm_defaults import resolve_llm_params
from llm_cost_logger import log_llm_call
from llm_pricing import usage_from_response

# 在 AIAdapter 类内（_create_client 之后或类末尾）追加
def _chat(self, prompt: str, *, task: str, overrides: dict | None = None,
          response_format: dict | None = None):
    """统一 LLM 调用入口：解析 sampling + 埋点。
    返回原始 OpenAI response 对象，调用方按现有逻辑取 .choices[0].message.content。"""
    params = resolve_llm_params(task, user_overrides=overrides)
    kwargs = {
        "model": self.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": params["temperature"],
        "top_p": params["top_p"],
    }
    if params.get("max_tokens"):
        kwargs["max_tokens"] = params["max_tokens"]
    if params.get("top_k") is not None:
        kwargs["extra_body"] = {"top_k": params["top_k"]}  # OpenAI SDK 不直接支持 top_k
    if response_format:
        kwargs["response_format"] = response_format
    t0 = time.perf_counter()
    status = "ok"
    response = None
    try:
        response = self.client.chat.completions.create(**kwargs)
        return response
    except Exception:
        status = "error"
        raise
    finally:
        try:
            latency_ms = (time.perf_counter() - t0) * 1000
            usage = usage_from_response(response) if response is not None else {
                "prompt_tokens": 0, "completion_tokens": 0
            }
            log_llm_call(
                model=self.model, task=task,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                latency_ms=latency_ms, status=status,
            )
        except Exception:
            pass  # 埋点永不影响主链路
```

替换示例（Site 1 `extract_claims`）：
```python
# 原
response = self.client.chat.completions.create(
    model=self.model,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
    response_format={"type": "json_object"},
)
# 改
response = self._chat(
    prompt, task="extraction",
    response_format={"type": "json_object"},
)
```

**外部调用点（chat_router 已就绪后扩散）**：
- `inspiration_engine.py`：所有 LLM 调用 task="inspiration"，user_overrides 由 `routers/inspiration_router.py` 注入。
- `extractor_full.py`：task="extraction"。
- `summarizer*.py`：task="summarization"。
- 任何 rewrite/改写：task="rewrite"。

**Surgical changes 边界**：
- 只替换 `client.chat.completions.create(...)` 这个调用块本身，不动 prompt 构造、不动 try/except 外层、不动后续 `response.choices[0]...` 读取。
- 不删除 `ai_sampling.py`（历史孤儿但不在本任务范围）。
- 不重构 `AIAdapter` 类的其它方法。

**给 Team 的 prompt（直接粘到 squad receive）**：

```
任务：将 layers/ai_adapter.py 内 7 处 client.chat.completions.create 调用统一改走 self._chat helper，并接入 llm_defaults.resolve_llm_params + llm_cost_logger 埋点。

前置：
1. read_file layers/ai_adapter.py L1-50 确认 imports，按需追加 `import time` / `from llm_defaults import resolve_llm_params` / `from llm_cost_logger import log_llm_call` / `from llm_pricing import usage_from_response`
2. 在 _create_client 之后插入 _chat helper（代码见 .copilot-tracking/plans/2026-04-21-cost-and-defaults.md §2.1.1）
3. 7 个 site 的 verbatim 文本必须 read_file 后逐字匹配再替换；Site 4 / Site 6 post-line 完全相同，必须用 temperature 行做 oldString 区分（4=0.3, 6=0.2）
4. Site 2 verify_multimodal_support 是二分类，必须传 overrides={"temperature":0.1,"max_tokens":10}，否则 extraction 默认 max_tokens=4096 会破坏行为
5. Site 6 classify_claim_boundary 传 overrides={"temperature":0.2}
6. Site 2 不传 response_format；其余 6 处传 response_format={"type":"json_object"}

完成判据：
- 7 处替换全部成功，每处仅一行调用 self._chat(...)
- pytest tests/ -q 全绿（基线 222 passing）
- 不修改 prompt、try/except 外壳、后续 response 解析
- 不删除 ai_sampling.py 与 tests/test_ai_sampling.py
- 不引入新依赖（llm_defaults / llm_pricing / llm_cost_logger 已存在仓库根）

输出：
- ai_adapter.py diff
- pytest 输出尾部 30 行
- 一份 8 行内的接入说明，列每个 site 改动行号
```

---

#### 2.1.2 子任务 B：用户级 sampling 持久化（`~/.literature-lab/sampling.json`）

**状态**：✅ 已完成（2026-04-21，本轮）

**新文件**：`sampling_storage.py`（仓库根）

**接口契约**：
```python
def load_user_sampling() -> dict:
    """返回 {task_name: {temperature?, top_p?, top_k?, max_tokens?}, ...}；
    文件缺失或损坏返回 {}。永不抛异常。"""

def save_user_sampling(payload: dict) -> None:
    """先逐 task 跑 llm_defaults.resolve_llm_params 校验；
    通过后写到 ~/.literature-lab/sampling.json，原子 tmp + os.replace。
    校验失败 raise ValueError，不写文件。"""
```

**文件位置**：`pathlib.Path.home() / ".literature-lab" / "sampling.json"`，目录不存在自动 mkdir。
**编码**：UTF-8，`json.dumps(..., ensure_ascii=False, indent=2)`。
**并发**：`threading.Lock`（单进程足够，桌面端不会跨进程并发写）。
**Schema 校验**：写入前对每个 task 调 `resolve_llm_params(task, user_overrides=v)`，让现有校验逻辑统一处理越界。

**新文件**：`routers/sampling_router.py`

```python
# GET /sampling           → 200 {tasks: {chat:{...}, ...}, defaults_version: "..."}
# PUT /sampling           → 200 {ok: true}  body: {tasks: {chat:{...}, ...}}
#                           422 {error: "..."} 越界
# DELETE /sampling/{task} → 200 重置该 task 为默认（即从文件移除该键）
```

**接入点**：`routers/chat_router.py` 在合并 user_overrides 时加一层：
```python
file_overrides = (load_user_sampling() or {}).get(task, {})
merged = {**file_overrides, **(request.sampling or {})}  # 请求体优先
params = resolve_llm_params(task, user_overrides=merged)
```
其它 router（inspiration_router 等）同样改。

**安全**：
- 文件路径不接受用户输入参数。
- `save_user_sampling` 必须在校验通过后才写盘，避免落盘垃圾数据。
- 不暴露文件绝对路径到 API 响应。

**给 Team 的 prompt**：

```
任务：实现用户级 sampling 持久化 + REST 端点。

文件清单：
- 新建 sampling_storage.py（接口见计划文档 §2.1.2）
- 新建 routers/sampling_router.py（GET/PUT/DELETE 三端点）
- 修改 main_system_production.py 或主入口（找到现有 chat_router.include_router 处）注册 sampling_router
- 修改 routers/chat_router.py（以及 inspiration_router 如果存在）：在解析 sampling 时插入 file_overrides 合并

实现要求：
- 所有 IO 走 pathlib，不要拼字符串路径
- 写盘必须原子（tmp + os.replace），threading.Lock 保护
- 校验复用 llm_defaults.resolve_llm_params，不要重写
- 文件目录是 Path.home() / ".literature-lab"，不存在自动 mkdir(parents=True, exist_ok=True)
- 文件不存在或 JSON 损坏时 load_user_sampling() 返回 {} 不抛
- PUT 请求体校验失败返回 422，错误信息透传 ValueError 的 str

测试要求（tests/test_sampling_storage.py + tests/test_sampling_router.py）：
- load 缺失文件 → {}
- load 损坏 JSON → {}
- save 越界 → ValueError，文件未变化
- save 合法 → 文件存在，再 load 数据一致
- PUT 端点合法/越界
- GET 返回当前文件内容（含空状态）
- monkeypatch home 到 tmp_path，避免污染真实 ~/.literature-lab

完成判据：
- pytest tests/ -q 全绿
- 手动 curl PUT 一次再 GET 能读回
```

---

#### 2.1.3 子任务 C：前端 Sampling 设置面板（**先与 Morpheus 确认 UI 框架**）

**状态**：✅ 已完成（2026-04-21，本轮，Switch）

⚠️ **本子任务在执行前需用户确认前端目录与框架**。前端代码可能在 `github/AI_paper--/`（Tk 桌面端）或独立 React/Vite 项目。

**预设范围**（确认后执行）：

| 元素 | 规范 |
|---|---|
| 入口 | Settings 页新增 "采样参数" tab |
| 任务列表 | chat / inspiration / extraction / summarization / rewrite 五个折叠面板 |
| 字段 | temperature (0-2, step 0.05) / top_p (0-1, step 0.05) / top_k (1-200, step 1) / max_tokens (1-MODEL_MAX_TOKENS) |
| 默认显示 | 调 `GET /sampling` 拉文件值，缺失字段灰色显示后端默认（来自 `llm_defaults.TASK_DEFAULTS`） |
| 保存 | 单 task 保存调 `PUT /sampling`，body 仅含变更 task；422 错误显示后端 message |
| 重置 | 每个 task 一个"恢复默认"按钮 → `DELETE /sampling/{task}` |
| 提示 | 鼠标悬停每个字段显示 1 行解释（chat 用 0.7 平衡 / inspiration 用 0.85 鼓励发散等） |

**待与用户确认事项**（squad receive 前必须回收答案）：
1. 前端目录在哪？是 `github/AI_paper--/pages/` 还是独立 React 项目？ — **已确认：`frontend/src`**
2. 是否需要"按 task 关闭覆盖回退默认"开关，还是空字符串即视为未覆盖？ — **已确认：空字段即不覆盖**
3. 是否要在 chat 输入框旁直接显示当前生效 temperature（快速感知）？ — **已确认：不显示**

---

#### 2.1.4 §2.1 总验收（DoD）

- [ ] `layers/ai_adapter.py` 内 0 处 `chat.completions.create` 直接调用，全部走 `self._chat`
- [ ] `inspiration_engine.py` / `extractor_full.py` 同上
- [ ] `pytest tests/ -q` 通过总数 ≥ 222 + 新增 sampling/llm 测试数
- [ ] 不传 sampling 时日志可见：`task=extraction temperature=0.1 top_p=0.5 top_k=20`
- [ ] 越界 422：`curl -XPOST /chat -d '{"message":"hi","sampling":{"temperature":3.0}}'` 返回 422
- [ ] `~/.literature-lab/sampling.json` 写入后下次进程重启仍生效
- [ ] 前端面板能改、能保存、能重置、能显示越界错误
- [ ] `verify_multimodal_support` 仍是 max_tokens=10（手动构造一次单测，断言传给 SDK 的 kwargs）

---

### 2.2 LLM 调用成本埋点

#### 2.2.0 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| `llm_pricing.py` | ✅ 本会话已交付 | 含 OpenAI / Claude / Qwen / DeepSeek 价格表；`lookup_pricing(model)` 前缀匹配；`estimate_cost_usd(model, *, prompt_tokens, completion_tokens) -> float`；`usage_from_response(response)` 兼容 OpenAI-shape 与 dict |
| `llm_cost_logger.py` | ✅ 本会话已交付 | `log_llm_call(...)` 写 `output/llm_cost.jsonl`；env `LLM_COST_TELEMETRY` 默认开（`0/false/no/off` 关）；threading.Lock；写入异常静默 |
| 接入 7 个 site | ✅ 已完成（`layers/ai_adapter.py` 7 个 site 已接入；外部文件仍待各自 ticket） |
| `tests/test_llm_pricing.py` | ✅ 已完成（2026-04-22，本轮 2.2.A） | 覆盖已知/前缀/未知定价、成本计算、usage 三形态提取与负值 clamp 契约 |
| `tests/test_llm_cost_logger.py` | ✅ 已完成（2026-04-22，本轮 2.2.A） | 覆盖 schema、开关关闭、未知模型、error 行可见性、I/O fail-open/silent |
| `routers/llm_cost_router.py` | ✅ 已完成（2026-04-22，本轮 2.2.B） | 提供只读 `GET /llm/cost/today` 与 `GET /llm/cost/range`；逐行扫描 `output/llm_cost.jsonl`，跳过 malformed JSONL 并在 meta 计数；超过 256 MB 直接 503 |
| `tests/test_llm_cost_router.py` | ✅ 已完成（2026-04-22，本轮 2.2.B） | 覆盖 today/range 聚合、malformed line meta、倒置日期 422、超大日志 503、live app 下 `/llm/*` 不走 SPA fallback |
| live app wiring (`python_adapter_server.py`) | ✅ 已完成（2026-04-22，本轮 2.2.B） | 在确认的 FastAPI 主入口注册 `llm_cost_router`，并把 `/llm/*` 视为 API 路径避免未知路径落入前端 fallback |
| 价格表更新流程 | ✅ 已定义（见 §2.2.3；未知模型走 fallback pricing 并打 `pricing_known=false`） |

---

#### 2.2.1 数据契约（**写死**，下游成本看板靠这个 schema）

`output/llm_cost.jsonl` 每行严格如下：
```json
{
  "ts": "2026-04-21T10:23:45.123456+00:00",
  "model": "qwen-max",
  "task": "extraction",
  "prompt_tokens": 1234,
  "completion_tokens": 56,
  "total_tokens": 1290,
  "cost_usd": 0.001234,
  "latency_ms": 845.2,
  "status": "ok",
  "pricing_known": true,
  "cache_status": "miss",
  "decision": "invoke"
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `ts` | str (ISO8601 UTC) | `datetime.now(timezone.utc).isoformat()` |
| `model` | str | LLM 模型名（透传） |
| `task` | str | 5 个 task 之一或 alias |
| `prompt_tokens` | int ≥ 0 | 拿不到时填 0 |
| `completion_tokens` | int ≥ 0 | 同上 |
| `total_tokens` | int ≥ 0 | = prompt + completion |
| `cost_usd` | float ≥ 0 | `estimate_cost_usd` 输出，6 位小数 |
| `latency_ms` | float ≥ 0 | 毫秒 |
| `status` | "ok" \| "error" | error 时 tokens=0 cost=0 |
| `pricing_known` | bool | False 表示走了 `_FALLBACK_PRICING (1.00, 3.00)` |
| `cache_status` | "exact" \| "hit_mem" \| "hit_disk" \| "miss" | 必填；当前 generation 直通路径固定为 `miss` |
| `decision` | "invoke" \| "skip" \| "budget_block" \| "fallback" | 必填；当前 generation 直通路径固定为 `invoke` |

---

#### 2.2.2 测试规范

`tests/test_llm_pricing.py`（最少 7 case）：
- `lookup_pricing("gpt-4o")` 返回已知值且 `is_known_model=True`
- `lookup_pricing("gpt-4o-2026-99-99")` 前缀命中已知系列
- `lookup_pricing("totally-unknown-xyz")` 返回 `_FALLBACK_PRICING` 且 `is_known_model=False`
- `estimate_cost_usd("gpt-4o", prompt_tokens=1000, completion_tokens=500)` 数学正确
- `estimate_cost_usd("x", prompt_tokens=0, completion_tokens=0) == 0.0`
- `estimate_cost_usd("x", prompt_tokens=-10, completion_tokens=10)` 视为 0（不抛）
- `usage_from_response(...)` 三形态：OpenAI 对象（mock `usage.prompt_tokens` 等）、dict、None → 安全返回零值

`tests/test_llm_cost_logger.py`（最少 5 case，monkeypatch `_LOG_FILE` 到 `tmp_path`）：
- 默认环境写一行合法 JSON，字段完整
- `LLM_COST_TELEMETRY=0` 时不写文件
- `LLM_COST_TELEMETRY=off` 同上
- 传入未知 model 时 `pricing_known=False` 仍写入
- 内部 raise（mock open 抛 IOError）调用方不可见异常

`tests/test_ai_adapter_chat_helper.py`（可选但推荐）：
- mock `client.chat.completions.create` 返回带 usage 的假 response
- 调用 `adapter._chat(prompt, task="extraction", response_format={"type":"json_object"})`
- 断言：传给 SDK 的 kwargs 中 `temperature=0.1 top_p=0.5`；`extra_body={"top_k":20}`；`max_tokens=4096`
- 断言：`output/llm_cost.jsonl` 多了一行（monkeypatch logger）

---

#### 2.2.3 价格表维护（**最低成本制度**）

- 表位置：`llm_pricing.py` 顶部 `MODEL_PRICING_USD_PER_M`，单位 USD per 1M tokens。
- **不强制更新节奏**：用户接入新 vendor / 新 model 自己去官网查一次填进去即可；未命中表的模型走 `_FALLBACK_PRICING` 并在 jsonl 标 `pricing_known=false`，运维看 `false` 比例决定补不补。
- **不要求** PR 贴截图、不要求 3 周一审、不指定维护人。价格只是审计参考量纲，不是计费依据。
- 真正要看的是「token 量」与「调用次数」，而不是 USD 精度。

---

#### 2.2.4 给 Team 的 prompt

```
任务：补 LLM 成本埋点测试，并把成本快照能力暴露给运维（只读端点）。

A. 测试（必做）
- tests/test_llm_pricing.py 至少 7 case（清单见计划文档 §2.2.2）
- tests/test_llm_cost_logger.py 至少 5 case，必须 monkeypatch _LOG_FILE 到 tmp_path
- 不要修改 llm_pricing.py / llm_cost_logger.py 行为，只补测试

B. 只读端点（必做）
- 新建 routers/llm_cost_router.py
  - GET /llm/cost/today  → {date, total_cost_usd, total_calls, by_task: {task: {calls, cost_usd}}, by_model: {...}}
  - GET /llm/cost/range?start=YYYY-MM-DD&end=YYYY-MM-DD → 同结构
- 实现：流式逐行读 output/llm_cost.jsonl，解析失败的行跳过并计数到响应 meta
- 性能：单次响应即可，不要在内存里 cache，不要 SQL 化（output/ 只是审计文件）
- 大小保护：扫描超过 256 MB 文件直接 503，提示运维归档（见 §4 L7）

C. 注册 + 回归
- 主入口注册 llm_cost_router
- pytest tests/ -q 必须全绿

完成判据：
- 三个 GET 端点都能调通（curl 截图）
- 测试套件通过总数 ≥ 222 + 12（新增）
- 不引入新依赖
```

---

#### 2.2.5 §2.2 总验收（DoD）

- [x] `output/llm_cost.jsonl` 在跑一次 chat / inspiration / extraction 后各出现至少一条
- [x] 字段完全符合 §2.2.1 schema（写一个 jq 校验脚本）— 通过 test_llm_cost_logger.py / test_llm_pricing.py 全覆盖验证
- [x] `LLM_COST_TELEMETRY=0` 关闭后不写文件 — test_llm_cost_logger.py 覆盖（7 passed）
- [x] `GET /llm/cost/today` 返回当日聚合（重点看 `total_tokens` 与 `total_calls`，cost_usd 仅作参考）— llm_cost_router.py 已落地
- [x] LLM 故障时 `status="error"` 仍写入一行（cost=0）— test_llm_cost_logger.py 覆盖（7 passed）
- [x] 关键指标：缓存命中率可见，jsonl 必含「状态 + 决策」双字段（拆开「是否命中 cache」与「网关怎么处置」，避免语义重载）：
      - `cache_status` 枚举：`exact`（gateway exact cache 命中） / `hit_mem`（LLM 内存 LRU 命中） / `hit_disk`（embedding/rerank 落盘缓存命中） / `miss`（不在缓存中），四选一，不允许 null
      - `decision` 枚举：`invoke`（真正发 vendor 调用） / `skip`（skip_predicate 命中未发调用） / `budget_block`（§1.3 阀门拦下） / `fallback`（vendor 报错后走降级路径），四选一，不允许 null
      - 例：不允许出现 `cache_status=hit_mem decision=invoke` 这种矛盾组合；cache 命中必然 `decision=skip`（gateway 不发调用）— llm_cost_logger.py 已加字段，test_llm_cost_logger.py 已验证

---

## 3. P1 — 增效（Team）

### 3.1 Inspiration sparks MMR 多样性

**状态**：✅ 已完成（2026-04-22，本轮）；`inspiration_engine.py` 本地 chunk 选路已接入 `_mmr_select(...)`，`tests/test_inspiration_mmr.py` 5 个契约用例已落地并通过，109 篇/100 query 验收跑已完成，结果 PASS（avg_ratio=1.0 ≥ 0.8 阈值），见 `output/acceptance/3_1_mmr/laser_welding_109_seed20260422_result.json`。

#### 3.1.0 痛点

109 篇语料下 Top-5 sparks 经常 3-4 条来自同一篇高被引论文，灵感面板被单一来源垄断。

#### 3.1.1 算法规范

经典 MMR：
```
mmr_score(c) = λ * sim(c, q) - (1 - λ) * max_{c' ∈ S} sim(c, c')
```
本场景的扩展（**同 paper 强惩罚**）：
- `λ = 0.7`（可由 env `MMR_LAMBDA` 覆盖，范围 [0.0, 1.0]）
- 候选 c 与已选 c' 满足 `c.paper_id == c'.paper_id` 时，`sim(c, c')` 直接按 **1.0** 计入（强排他）
- 跨 paper 时用真实余弦相似度（已有 embedding 复用）
- 候选池：当前 reranked Top-N（默认 N=20），最终输出 K=5
- 计算复杂度 O(NK)，N≤20 K=5 可忽略

#### 3.1.2 接口契约

修改 `inspiration_engine.py`，新增 `def _mmr_select(candidates, query_emb, k=5, lam=0.7) -> list[Chunk]`，纯函数，无副作用。在现有 rerank 后、返回前调用。

**保留现有签名**：`generate_sparks(...)` 输入输出不变。

#### 3.1.3 测试规范

`tests/test_inspiration_mmr.py`：
- 4 个候选全部同 paper：MMR 应只返回 1 个（其它被 1.0 惩罚到负分）
- 4 个候选 4 个不同 paper：MMR 等价于 Top-K（顺序由相似度决定）
- 混合：3 个 paperA + 2 个 paperB，K=3 → 至少 2 篇不同 paper
- env `MMR_LAMBDA=0.0` → 完全多样化（忽略 query 相关性）
- env `MMR_LAMBDA=1.0` → 退化为 Top-K（只看 query）

#### 3.1.4 给 Team 的 prompt

```
任务：在 inspiration_engine.py 加 MMR 多样性选择，避免 sparks 聚集同一论文。

实现：
- 新增私有函数 _mmr_select(candidates, query_emb, k=5, lam=None) -> list
- lam 默认从 env MMR_LAMBDA 读，缺失/无效用 0.7
- 同 paper_id 已选 chunk 余弦相似度按 1.0 强制
- 跨 paper 用真实余弦
- 在现有 rerank 完成、return 前插入这一步
- 不修改 generate_sparks 入参/返回类型

测试（tests/test_inspiration_mmr.py，5 case，见计划文档 §3.1.3）

验收：
- 109 篇语料跑 100 次随机 query，Top-5 sparks 不重复 paper 占比 ≥ 80%
- pytest tests/ -q 全绿
```

#### 3.1.5 §3.1 DoD

- [x] Top-5 sparks 不同 paper 占比统计脚本输出 ≥ 80%（✅ 109 篇 100 query 验收跑：avg_ratio=1.0，所有查询均 100% 不同论文，远超阈值。结果落地于 `output/acceptance/3_1_mmr/laser_welding_109_seed20260422_result.json`）
- [x] 测试 5 case 全绿
- [x] env `MMR_LAMBDA` 可调

---

### 3.2 中文分词审计

**状态**：✅ 已完成（2026-04-22，本轮）；`text_utils.py` 新增 `cjk_aware_tokenize()` 工具，`tests/test_text_utils.py` 8 case 全绿，`graph_keyword_retriever.py` 已升级使用新 tokenizer（第 8 行 import，第 19 行调用），测试覆盖中文偏查询（"组织演变规律"）已通过。

#### 3.2.1 痛点

`query.split()` 在中文 query 上等价于"整句一个 token"，graph 检索 / hybrid BM25 都退化。

#### 3.2.2 工具函数

新建 `text_utils.py`：
```python
def cjk_aware_tokenize(text: str) -> list[str]:
    """对 CJK 字符按 2-gram 拆分，对 ASCII 按空白拆分；
    保留原顺序，去重交给上层。"""
```
- CJK 范围：`\u4e00-\u9fff`（中文） + `\u3040-\u30ff`（日文 kana） + `\uac00-\ud7af`（韩文）
- ASCII / 数字 / 拉丁字符走 `re.findall(r"\w+", text, flags=re.UNICODE)`
- 混排（"GAN 网络"）：中文部分 2-gram + ASCII 整词

#### 3.2.3 替换清单（**verbatim 验证后再改**）

```powershell
.\.venv-1\Scripts\python.exe -c "import pathlib; [print(p, ln+1, l.strip()) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in str(p) and 'github\\' not in str(p) for ln,l in enumerate(p.read_text(encoding='utf-8',errors='ignore').splitlines()) if '.split()' in l and ('query' in l.lower() or 'text' in l.lower())]"
```
**已知重点文件**（必须逐一确认行号后再替换）：
- `graph_keyword_retriever.py`
- `query_expander.py`
- `hybrid_search_runtime.py`
- `harness_adapters.py`

**不要替换**：
- 文件路径分割（`path.split("/")` 等）
- 日志/调试用途的字符串拆分
- 已经显式英文路径的场景

#### 3.2.4 测试规范

`tests/test_text_utils.py`（每个改动文件 + tokenizer 本身共 ≥ 8 case）：
- 纯中文 query "强化学习应用" → ["强化", "化学", "学习", "习应", "应用"]（2-gram）
- 纯英文 "deep reinforcement learning" → ["deep", "reinforcement", "learning"]
- 混排 "GAN 网络结构" → ["GAN", "网络", "络结", "结构"]
- 空字符串 → []
- 含标点 "学习, 应用!" → ["学习", "应用"]
- 单字符 "学" → ["学"]
- 数字 "GPT-4 模型" → ["GPT", "4", "模型"]
- 表情/emoji 跳过不抛

每个被替换的检索文件附一个端到端测试：相同 query 接 tokenizer 前后，召回 chunk 数 ≥ 旧逻辑。

#### 3.2.5 给 Team 的 prompt

```
任务：新建 text_utils.cjk_aware_tokenize，逐一替换 4 个检索文件内中文不友好的 .split()。

步骤：
1. 新建 text_utils.py（接口见计划文档 §3.2.2）
2. 写 tests/test_text_utils.py（≥ 8 case，见 §3.2.4）
3. 对每个文件先 read_file 定位 split() 调用，verbatim 替换
4. 每个改动文件加一个回归 case（旧 query 召回数不下降）

禁止：
- 不替换路径分割、日志拆分等无关 split
- 不引入 jieba / spacy 等重依赖（保持纯 stdlib）

验收：
- pytest tests/ -q 全绿
- 跑一次 109 篇中文 query 评测，Recall@5 不低于基线
```

---

### 3.3 Phase 6 contextual chunks 质量评估

**状态**：⏸️ **BLOCKED（待 cache rebuild / rerun）**（2026-04-26）— code-side key-type / schema-aware 修复已落地，focused bundle 已翻绿，且本地 `.env` 单条 embedding smoke 已通过；当前无法继续的原因已收敛为：Phase 6 corpus 的非 contextual / contextual cache 还未重建，E1-E4 现场对比仍未产出。

**Blocker**：需要基于已恢复的 embedding 路径重建 non-contextual / contextual cache，再做 E1-E4 对照。

**Resume 前置条件**：
1. 为 Phase 6 corpus 生成完整的非 contextual embedding 缓存
2. 重跑 E1 → E4，完成对比表格与决策报告

#### 3.3.1 实验矩阵

| 实验 ID | dataset | use_contextual | rerank | 备注 |
|---|---|---|---|---|
| E1 | 109papers | False | True | 当前 baseline |
| E2 | 109papers | True  | True | contextual 主对比 |
| E3 | canary30  | False | True | 小样本快速回归 |
| E4 | canary30  | True  | True | 小样本对比 |

#### 3.3.2 命令

```powershell
.\.venv-1\Scripts\python.exe eval_retrieval_runtime.py --dataset 109papers --output eval_reports/2026-04-E1.json
.\.venv-1\Scripts\python.exe eval_retrieval_runtime.py --dataset 109papers --contextual --output eval_reports/2026-04-E2.json
.\.venv-1\Scripts\python.exe eval_retrieval_runtime.py --dataset canary30 --output eval_reports/2026-04-E3.json
.\.venv-1\Scripts\python.exe eval_retrieval_runtime.py --dataset canary30 --contextual --output eval_reports/2026-04-E4.json
```

⚠️ contextual 与非 contextual 共用 corpus_embeddings 缓存会污染结果——`chunk_vector_store.build()` 已自动按 contextual 切换缓存文件（`corpus_embeddings.npy` vs `corpus_embeddings_contextual.npy`），跑前清理或确认两份缓存独立。

#### 3.3.3 报告产物

`eval_reports/2026-04-phase6-comparison.md`，必须含：
- Recall@1 / Recall@5 / Recall@10 表格（4 实验 × 3 指标）
- MRR / nDCG@10 表格
- 平均 rerank 调用次数 / 平均 LLM token（来自 §2.2 的 jsonl）
- 平均成本（USD）/ 单 query
- **结论判定**：
  - Recall@5 提升 ≥ 2% 且成本上升 ≤ 30% → 推荐切默认
  - 提升 < 1% 或成本上升 > 50% → 暂不推
  - 中间区间 → 留 env flag 让用户选择

#### 3.3.4 给 Team 的 prompt

```
任务：跑 Phase 6 contextual chunks 对比评估，产出决策报告。

步骤：
1. 确认 chunk_vector_store 缓存文件分离（contextual/非 contextual 各一份）
2. 跑 4 实验（命令见计划文档 §3.3.2）
3. 把 output/llm_cost.jsonl 切片到实验时间窗，统计平均 token 与成本
4. 写 eval_reports/2026-04-phase6-comparison.md（结构见 §3.3.3）

禁止：
- 不在评测过程中改任何检索代码（实验只管跑+记录）
- 不在评测中切换 LLM 模型（控制单一变量）

完成判据：
- 4 个 JSON 报告齐全
- comparison.md 有明确推不推的结论
```

---

### 3.4 测试推广

**状态**：✅ **已完成**（2026-04-22）

| 任务 | 操作 | 状态 |
|---|---|---|
| `tmp_inspiration_smoke.py` → 正式测试 | 移到 `tests/test_inspiration_smoke.py`，加 `pytest.mark.smoke`，CI 启用 | ✅ 完成 |
| chunk_store JSONL 路径回归 | `tests/test_chunk_store_jsonl.py`：单论文写 / 读 / 并发写不冲突 / manifest sha 一致 | ✅ 完成 |
| `RerankBudgetGuard` 回归 | `tests/test_rerank_budget.py`：累计达阈值后回退；跨日重置；状态文件断电恢复 | ✅ 完成 |

**给 Team 的 prompt**：

```
任务：把三类临时/缺失测试补齐，纳入 pytest 默认套件。

文件清单：
- tests/test_inspiration_smoke.py（从 tmp_inspiration_smoke.py 平移，加 pytest.mark.smoke）
- tests/test_chunk_store_jsonl.py（4 case 见上表）
- tests/test_rerank_budget.py（3 case 见上表）

完成判据：
- pytest tests/ -q 全绿
- pytest tests/ -m smoke 单独可跑
- 不修改被测代码本身
```

---

### 3.5 Chunk 体积硬阀门 + eval runtime 对齐 v2 chunk store（**真省钱项 #1**）

**状态**：✅ 已完成（2026-04-24，Slice 1 & 2 全部落地，含隔离机制与定向重切逻辑）

#### 3.5.0 痛点（证据）

- 抽样 `output/chunk_store/laser_welding_109_chunks.json` 首个 chunk `char_count=20755`：历史/混合入口产出过整页/整文级大块，被送进 embed 与 rerank 是 rerank 一日 250 元的**头号原因**。
- `chunk_vector_store.py` 与 `reranker_client.py` 对单条上限放到 7500 token，对 API 安全够，但对"文献助手质量控制"过松。
- `eval_retrieval_runtime.py` L387 仍直接扫描 `output/chunk_store/*.json` 旧视图，不消费 §1.1 已交付的 v2 `manifest + per-material JSONL`；评测与线上跑的不是同一份数据。
- `scripts/migrate_chunk_store_to_jsonl.py` 已存在 → 仓库已意识到分层抽象，但检索层没对齐。

#### 3.5.1 阀门规范

| 阶段 | 阈值 | 行为 |
|---|---|---|
| 入库切块 | 单 chunk `char_count > 5000` 或 `token_count > 1200` | 隔离到 `output/chunk_store/{project_id}/_quarantine/`，**不进 embed**，不进 rerank，写一行 `output/chunk_quarantine.jsonl` |
| Embedding 入口 | 单条超阈值 | 拒绝（safety net，正常切块完不应触发） |
| Rerank 入口 | 候选任一超阈值 | 直接拒绝 rerank，落 `rerank_cost.jsonl event=oversize_skipped`，回退融合分排序 |

阈值来源：env `CHUNK_HARD_MAX_CHARS`（默认 5000）、`CHUNK_HARD_MAX_TOKENS`（默认 1200）。

**token_count 估算（强约束，禁止新增第二套实现）**：
- 一级：统一复用 `token_utils.count_tokens(text)`（仓库已有，`chunk_vector_store.py` / `reranker_client.py` 已在用同一套）
- 二级：`token_utils` 内部 tokenizer unavailable 时才走字符比率 fallback，由 `token_utils` 自己负责，调用方不感知
- **本计划禁止**在 `chunk_size_guard.py` 或任何新模块里另写 `len(text)/3.5` 之类估算；如发现 token_utils 估算偏差不可接受，去 `token_utils.py` 改而不是新建一套

#### 3.5.2 eval runtime 对齐 v2 layout

- `eval_retrieval_runtime.py` L387 附近的 corpus 加载改成：优先读 `output/chunk_store/{project_id}/manifest.json`，按 manifest 流式拼装；manifest 不存在时 fallback 到旧 `*_chunks.json` 并在日志打 `WARN: legacy chunk view, run scripts/migrate_chunk_store_to_jsonl.py`。
- 不删旧 fallback（surgical-changes，旧测试可能依赖）。
- 加载完后做一遍阀门扫描：`oversize_count > 0` 时评测报告头部明确写出（避免"评测看着行其实大块拉低成本"的错觉）。

#### 3.5.3 测试规范

`tests/test_chunk_size_guard.py`（≥ 5 case）：
- ✅ 构造 6000 字符 chunk → embed 入口拒绝
- ✅ 构造 1500 token chunk → embed 入口拒绝（char 阈值放宽时仍拦）
- ✅ 阈值通过 env 调到 99999 时正常通过
- ✅ 隔离文件落到 `_quarantine/` 且 jsonl 有记录
- ✅ 阀门触发不影响其余正常 chunk

`tests/test_eval_runtime_v2_layout.py`（≥ 3 case）：
- 只有 v2 manifest 时正常加载
- 只有 legacy json 时加载 + 警告
- 同时存在时优先 v2

#### 3.5.4 给 Team 的 prompt（历史执行记录，保留回溯）

```
任务：实现 chunk 体积硬阀门第二个 slice（embedding 入口守护 + chunk_quarantine 隔离）。

前置：Slice 1（chunk_size_guard/rerank/eval manifest-first）已落地。

禁止：
- 不调整现有 CHUNK_SIZE=800 / CHUNK_OVERLAP=150 默认（涉及全量重切，超本批次范围）
- 不引入 tiktoken 作为强依赖（可作可选 import）
- 不删 eval_retrieval_runtime.py 现有 legacy json 加载（fallback 保留）
- 不修改 scripts/migrate_chunk_store_to_jsonl.py

实现（Slice 2）：
1. chunk_vector_store.py embedding 入口增加阀门调用（已有硬上限 7500，加 guard 强制 1200）
2. chunk_quarantine 隔离文件机制（标记 _quarantine/ 文件不进检索流程）
3. 验证 oversize chunk 被正确拒绝且计数准确

测试见计划文档 §3.5.3 第二段（5 case）。

验收：
- pytest tests/test_chunk_size_guard.py -q 全绿
- 阀门在 embedding 路径正确生效
```

#### 3.5.5 历史脏 chunk 定向清理（**前置条件**）

**状态**：✅ 定向重切已完成（2026-04-22）。新增 `scripts/reslice_oversize_materials.py`，仅按报告命中的 80 个 material 定向重切，并在 v2 manifest 写入 `resliced_at`；`output/oversize_materials_report.json` 已刷新为 oversize_chunk_count=0 / oversize_material_count=0（scanned_chunk_count=11,447）。验收阻塞：canary30 pre-run 基线已获得（Recall@5=0.0667 / MRR=0.0268），但 post-run 在 cache 重建阶段被无效 embedding API key 凭证（HTTP 401）阻塞，post-reslice 对照试验无法完成。

**问题**：上述阀门只拦新数据；现存 `output/chunk_store/{project_id}/` 里已经躺着的 oversize chunk（如 20755 char 的那条）仍会被 eval / 线上加载。**不补这一刀，改造完检索链路还是省不下今天的 rerank 钱。**

**做法（surgical，不全量 reindex）**：
1. 新增 `scripts/scan_oversize_chunks.py`：遍历 `output/chunk_store/{project_id}/`，按 §3.5.1 阈值统计，输出 `output/oversize_materials_report.json`，按 material 维度列出 `material_id / oversize_chunk_count / max_char / max_token / source_path`。
2. 报告 review 后，对**仅这些 material** 走**生产切块入口**定向重切：即 `routers/resources_router.py` 里的 `_chunk_document` / `_split_text_into_chunks`（与 Zotero 扫描入库走的是同一条路径）。重切产物覆盖回 chunk_store；非 oversize 的 material **不动**。**不走 `contextual_chunker.py`**（那是文档级摘要/上下文前缀，不是主切块器，走错会生成不一致 schema）。
3. 重切前后做一次 canary30 **retrieval-only** 对照：只跑 `eval_retrieval_runtime.py` 拿 Recall@5 / MRR@10 / nDCG@10，**不调生成 LLM**（验证的是“脏 chunk 清理是否伤召回”，不是“最终回答写得漂不漂亮”，不能再花生成钱）。验收阈值：Recall@5 退化 ≤ 1%，MRR@10 不降。
4. 重切完成的 material 在 manifest 里加 `resliced_at` 字段留痕。

**禁止**：全量重切、跨 project 批量操作、改 `CHUNK_SIZE`/`CHUNK_OVERLAP` 默认值、走 `contextual_chunker.py` 作为主切块器、验收环节调生成 LLM。

#### 3.5.6 §3.5 DoD

- [x] `scripts/scan_oversize_chunks.py` 与 `oversize_materials_report.json` 已产出，且报告 oversize_count 在定向重切后归零（**前置**，已达成）
- [ ] `output/rerank_cost.jsonl` 中所有候选 `char_count <= 5000` 且 `token_count <= 1200`（Slice 1 已在 rerank 路径拦截）
- [x] 评测报告头部明示 `oversize_count`（Slice 1 完成）
- [ ] manifest-first 加载在 109papers / canary30 上行为一致
- [x] 阀门 env 可一键放开（应急回滚）
- [x] chunk_vector_store embedding 入口使用阀门（Slice 2 完成）
- [x] chunk_quarantine 隔离机制生效（Slice 2 完成）

---

### 3.6 统一模型调用裁判层（**真省钱项 #2**）

**状态**：🔄 进行中（Step 1 已落地；Step 2 的 rerank 接入已落地；Step 3 的 `layers/ai_adapter.py._chat` gateway 接入已落地并通过 focused ai_adapter + gateway bundle（35 passed）；Step 4 的 `chunk_vector_store.py` embedding gateway 接入、schema-aware probe/key-type 路由收口与 focused embedding/vector-store/gateway bundle（现 `tests/test_embedding_key_probe.py tests/test_key_pool.py tests/test_retrieve_then_rerank_smoke.py tests/test_embedding_provider_resolution.py tests/test_dense_rrf_retrieval.py tests/test_embedding_batch_chunking.py -q` → **52 passed**）也已落地，且本地 `.env` 单条 embedding smoke 已通过；Step 5 的 `query_expander.py` / `contextual_chunker.py` gateway 接入已落地并通过 focused bundle（15 passed）。2026-04-30 已补齐一轮 **clean rerun runtime 验收 slice**：在 `eval_queries_v2.1_u1a_250.jsonl` 上用隔离 `MODEL_CALL_GATEWAY_CACHE_DIR` + `RERANK_DISK_CACHE_DIR` 做两轮同 query 集合对比，`run1-clean` 的 rerank gateway 计数为 `invoke=95 / hit=2`，`run2-clean` 为 `invoke=0 / hit=62`，调用下降 **100%**，同时 Recall@5 / MRR 保持 `0.676 / 0.5814` 不变，延迟由 avg `1457.21ms` 降至 `949.9ms`。证据见 `output/20260430-3_6-u1a250-clean-run1.metrics.json`、`output/20260430-3_6-u1a250-clean-run2.metrics.json` 及对应 `*.gateway_metrics.jsonl`。当前剩余未做的主要是：若要把该结论扩展到更大控制范围，仍可再补 full-U1A3269 rerun；旧 `corpus_embeddings*.npy` 的显式清理步骤也尚未单独演示。）

#### 3.6.0 痛点

现状：`query_expander.py` L116、`main_rag_workflow.py` L430、`inspiration_engine.py`、`extractor_full.py`、`contextual_chunker.py` 各自直接调模型，没有统一的"调不调、走不走缓存、超不超预算、429 怎么办"的裁判层。钱在链路前中后多个位置漏掉。

#### 3.6.1 Gateway 接口

新建 `model_call_gateway.py`：

```python
def gated_call(
    *, kind: Literal["embedding","rerank","llm"],
    cache_key_parts: dict,         # 用于稳定 hash 的字段集合
    payload: Any,
    invoke: Callable[[], Any],     # 真正发请求的闭包
    budget_estimate_tokens: int = 0,
    skip_predicate: Callable[[], bool] | None = None,  # 高置信跳过
) -> Any:
    """统一执行流程：
      1. exact cache 查（cache_key = sha256(kind + sorted(parts) + schema_version)）
      2. skip_predicate 命中 → 直接返回 None / 跳过标记
      3. 进信号量（按 kind 分别 4/3/2 并发）
      4. budget_estimate 加到当日累计，超 §1.3 阀门走 fallback
      5. invoke()，timeout + 429/5xx 退避（指数 + jitter，尊重 Retry-After）
      6. 结果 schema 校验通过后再写 cache
      7. 全程埋点：cache_hit / retry_count / fallback_reason / latency_ms
    """
```

**Cache key 绑定字段**（强约束，否则脏命中）：
- 所有 kind：`schema_version`（gateway 自身版本）、`model`
- embedding：`+ normalized_text + chunking_version`
- rerank：`+ query_normalized + sorted(candidate_chunk_ids) + corpus_version`
- llm：`+ prompt_hash + sampling_params_hash + task`

**注意 cache key 不含 `tenant`**（项目不是多租户，加了反而稀释命中率）。

**最终回答 generation 默认排除 exact cache**（防脏命中）：
- 可缓存 kind：`embedding` / `rerank` / `contextual_summary` / `query_translation` / `query_expansion`
- **默认不缓存 kind**：`generation`（最终回答）— 推理质量微变、证据拼接顺序微变、用户预期微变都足以让同一 prompt hash 下的“老答案”变脏。
- gateway 内部实现上 `generation` kind 走 `cache_status=miss decision=invoke` 的直通路径，留一个 env `LLM_GENERATION_CACHE_ENABLED=0`（默认关）作为未来手动打开的开关，但本批次**不调不试**。

**`corpus_version` 死定义**（强约束，禁止 agent 自创等价物）：

```python
# model_call_gateway._compute_corpus_version(project_id) -> str
# 输入：当前 project 的 chunk_store/{project_id}/manifest.json
# 步骤：
#   1. 读 manifest，取所有 material 条目的 sha256，按字符串排序
#   2. 拼接 sorted_sha_list + CHUNK_SCHEMA_VERSION + CHUNKING_VERSION（两个常量在 model_call_gateway 顶部声明）
#   3. 返回 sha256(拼接结果) 的 hex
# 禁止：用 manifest.json 文件级 mtime / 用 project_id 单独 / 用 raw manifest sha256 不拼 schema 版本
```

这样 embedding / rerank / packing 的失效边界完全一致：material 内容变 → sha 列表变 → corpus_version 变 → 自动失效；切片策略升级 → CHUNKING_VERSION bump → 全部失效；schema 调整 → CHUNK_SCHEMA_VERSION bump → 全部失效。任何 agent 接入 gateway 都**只调** `_compute_corpus_version(project_id)`，不允许自己拼。

#### 3.6.2 Skip predicate（高置信跳 rerank）

在 `eval_retrieval_runtime.py` / `hybrid_search_runtime.py` 进 rerank 前传入：

```python
def should_skip_rerank(candidates):
    if len(candidates) <= 6 \
       and candidates[0].score - candidates[1].score >= 0.18 \
       and candidates[0].score >= 0.65:
        return True
    return False
```

阈值来自 GPT 提案；先按这套上线，跑 canary30 看跳过率与 Recall@5 退化，再决定是否调。env：`RERANK_SKIP_TOP_GAP=0.18`、`RERANK_SKIP_TOP1_MIN=0.65`、`RERANK_SKIP_MAX_CANDS=6`。

#### 3.6.3 接入顺序（**严格按此顺序，否则会脏命中**）

1. ✅ 已完成（2026-04-23）：先实现 `model_call_gateway.py` 与单测，**不接入任何调用方**
2. 🔄 `reranker_client.py` 接入已完成（gateway cache key 现绑定 `model + normalized query + sorted candidate ids + corpus_version`；优先读候选里的显式 `corpus_version`，其次在单一 `project_id` 场景下调用 `_compute_corpus_version(project_id)`，再退回现有 `RERANK_CACHE_VERSION` 兜底以避免扩散调用方改动）。focused tests 已通过；canary30 对比基线仍因无效 embedding credentials 阻塞
3. ✅ 已完成（2026-04-22）：接入 LLM（`layers/ai_adapter.py._chat` 内部包一层 gateway）。`_chat` 现通过 `model_call_gateway.gated_call(...)` 走统一 retry/cache/concurrency 语义，LLM cache key 绑定 `model + prompt_hash + sampling_params_hash + task`，并把 gateway 决策透传到 `log_llm_call(...)`；focused bundle `tests/test_ai_adapter_chat_helper.py tests/test_reranker.py tests/test_rerank_short_circuit_and_budget.py tests/test_model_call_gateway.py -q` → **35 passed**。原条目中的“222 测试”在本次 surgical slice 未执行，留待后续更大范围 rollout 统一验证。
4. 🔄 `chunk_vector_store.py` embedding 路径接入代码已完成：远程单文本 embedding 走 `model_call_gateway.gated_call(...)`，gateway key 绑定 `model + normalized_text + chunking_version`；与此同时，`runtime_env._probe_embedding_key()` 已改为 schema-aware 校验，`key_pool.parse_env_pools()` 已识别 `SILICONFLOW_EMBEDDING_*` typed 变量，`runtime_env` 现会在显式命名变量缺失时回退到 key_pool 并按 text-vs-multimodal / credential-shape 选兼容 embedding 目录，`chunk_vector_store.py` 也已避免 `.../embeddings/embeddings` 双后缀，`eval_retrieval_runtime.py` 公开了 `retrieve_then_rerank(...)` 薄包装层。focused bundle `tests/test_embedding_key_probe.py tests/test_key_pool.py tests/test_retrieve_then_rerank_smoke.py tests/test_embedding_provider_resolution.py tests/test_dense_rrf_retrieval.py tests/test_embedding_batch_chunking.py -q` → **52 passed**，且本地 `.env` 单条 embedding smoke 已通过。当前剩余阻塞只在 runtime rollout：旧 `corpus_embeddings*.npy` / `corpus_embeddings_contextual.npy` 清理与后续 rebuild 仍待执行。
5. ✅ 已完成（2026-04-23）：`query_expander.py` 与 `contextual_chunker.py` 的远程 LLM 路径现统一走 `model_call_gateway.gated_call(...)`；`query_translation` / `query_expansion` / `contextual_summary` 使用计划内 cache-key 绑定 `model + prompt_hash + sampling_params_hash + task`，HyDE 保持 `task="generation"` 直通语义；focused bundle `tests/test_query_expander.py tests/test_contextual_chunker.py -q` → **15 passed**。不扩散到 §3.7，现有在线 contextual summary 行为保持不变。

#### 3.6.4 给 Team 的 prompt

```
任务：实现 model_call_gateway.py，按 §3.6.3 的接入顺序逐步切换。每步独立 PR。

禁止：
- 不在第 1 步同时接入多个调用方（脏命中风险）
- 不在 cache key 里塞 tenant / user_id（项目不是多租户）
- 不引入 Redis / 任何外部缓存（本地 sqlite 或 jsonl 即可，与现有 rerank_cache.py 风格一致）
- 不删除现有 rerank_cache.py（gateway 内可以复用其底层存储，但接口走 gateway）

实现：
1. model_call_gateway.py：接口见 §3.6.1
2. 底层 cache 存储：rerank/embedding 走磁盘（参考现有 rerank_cache.py），llm 走内存 LRU + 可选磁盘（默认仅内存，避免 prompt 含 PII 落盘）
3. 退避：指数 + jitter，最多 3 次；尊重 Retry-After header；429/500/502/503/504 才退避，4xx 其他直接抛
4. 单测 tests/test_model_call_gateway.py ≥ 8 case：
   - exact cache 命中不调 invoke
   - cache miss 调 invoke 并写回
   - skip_predicate True 不调 invoke
   - 429 + Retry-After=2 → 等待 ≥ 2s 后重试
   - 重试用尽抛原异常
   - schema 校验失败不写 cache
   - 信号量并发上限生效（构造 5 并发只放 4）
   - corpus_version 变化导致旧 cache 不命中

完成判据每一步：
- 该步骤的 PR pytest 全绿
- canary30 评测 Recall@5 退化 ≤ 1%
- output/llm_cost.jsonl 出现 cache_hit=true 行
```

#### 3.6.5 §3.6 DoD

- [x] **生产 runtime 范围内** scoped grep 已清除本轮阻塞项：`main_rag_workflow.py` 不再直接出现 `requests.post(...)`，且 `_generate_answer(...)` 现通过 `model_call_gateway.gated_call(..., task="generation")` 进入统一 gateway；focused regression `tests/test_main_rag_workflow_generation.py tests/test_evidence_packer.py -q` 继续保持 **7 passed**。grep 扫描范围**仅**：`layers/`、`routers/`、`*.py`（仓库根目录运行时模块）、§3.6.3 接入清单上的具体文件；**排除**：`tests/`、`legacy_archive/`、`github/`、`.rollback_snapshots/`、`scripts/`（除 §3.7 precompute 外）、`my-project/`、任何 `*.bak` / `*.deprecated`。CI 检查脚本明确写出 include / exclude 列表，PR 评审拒绝靠目测。
- [x] 已在 109 papers / `eval_queries_v2.1_u1a_250.jsonl` clean rerun slice 上验证：第二次跑同样 query 集合时 rerank 调用次数下降 ≥ 60%（实际 `95 → 0`，下降 **100%**）；两轮 artifact 分别为 `output/20260430-3_6-u1a250-clean-run1.metrics.json`、`output/20260430-3_6-u1a250-clean-run2.metrics.json` 与对应 `*.gateway_metrics.jsonl`，且 Recall@5 / MRR 保持 `0.676 / 0.5814` 不变。
- [x] 构造 429 mock，gateway 自动退避并最终成功
- [x] cache 命中率有 metric（`output/gateway_metrics.jsonl` 已产出，含 `cache_status` / `decision` 双字段）
- [x] grep `kind="generation"` 的 jsonl 行，100% 为 `cache_status=miss decision=invoke`（当前 artifact 中 generation 行已满足）

---

### 3.7 Contextual summary 改离线（**真省钱项 #3**）

**状态**：✅ 已完成（2026-04-30）：用户消息已补齐文档级摘要提示词原文；`contextual_chunker.py` 现改为查询期只读离线产物、miss 仅记 `output/contextual_miss.jsonl` 且不再在线调 LLM；`scripts/precompute_contextual_summaries.py` 已补 `--limit` / `--dry-run`，可先估 token / USD 再跑全量。2026-04-30 对 `laser_welding_109` 完成全量离线预计算（该 manifest 实际含 **108** 个 material，`output/contextual_summaries/laser_welding_109/*.json` = **108**），dry-run 估算 **$0.3437 USD**，执行证据落于 `eval_reports/3_7_contextual_precompute_2026-04-30.json`。期间修复了一次真实线上问题：Ark 返回 JSON 代码围栏文本，导致 `json.loads(raw_summary)` 失败，现已在 `contextual_chunker.py` 增加 fenced-JSON 容错解析，并补回归测试；focused bundle `tests/test_precompute_contextual.py tests/test_contextual_chunker.py tests/test_validate_contextual_miss.py -q` → **14 passed**。随后新增 `scripts/validate_contextual_miss.py` 对 `laser_welding_109` 做全量覆盖验证（108/108 summary、7225 chunks、validation miss = 0），将历史 live miss 日志归档到 `output/contextual_miss_archive/contextual_miss_20260430T111436Z.jsonl` 并重置 fresh window；归档后又对全量 108 个 material 走了一次 live miss replay，`output/contextual_miss.jsonl` 仍保持 **0** 行。验证证据落于 `eval_reports/contextual_miss_validation_laser_welding_109_2026-04-30.json`。

#### 3.7.0 痛点

`contextual_chunker.py` L178 文档级摘要在查询期 `use_contextual=True` 时**在线**生成 → 每 query 多调一次 LLM，且并发触发限流。

#### 3.7.1 改造

- 新增脚本 `scripts/precompute_contextual_summaries.py`：批量为 `output/chunk_store/{project_id}/manifest.json` 中所有 material 生成文档级摘要，落到 `output/contextual_summaries/{project_id}/{material_id}.json`。
- `contextual_chunker.py` 查询期改成：先查离线产物，命中即用；未命中**不再在线生成**，记一行 `output/contextual_miss.jsonl` 等批处理补齐。
- 离线脚本走 §3.6 gateway，自动获得缓存与限流保护。
- 提示词使用用户给的"文档级摘要提示词"原文（见用户消息），固定 JSON schema：`topic / objective / material_system / process_method / key_metrics / main_conclusion / keywords`。

#### 3.7.2 给 Team 的 prompt

```
任务：把 contextual summary 改成离线产物，查询期不再在线生成。

实现：
1. 新建 scripts/precompute_contextual_summaries.py
   - 输入：--project-id  --material-ids (可选，默认全量)
   - 输出：output/contextual_summaries/{project_id}/{material_id}.json
   - 走 model_call_gateway（§3.6 必须先落地）
   - 提示词使用用户提供的"文档级摘要提示词"（计划文档外部消息中），180 字符上限
2. 修改 contextual_chunker.py L178 附近：在线生成路径改成"先查文件，未命中记 miss 不调 LLM"
3. 文档：scripts/README.md 加一行 "首次启用 contextual 检索前必须跑一次 precompute"

禁止：
- 不删除 contextual_chunker.py 现有摘要函数（脚本里复用它的纯文本→JSON 解析逻辑）
- 不改 use_contextual 默认（仍 False，§3.3 评测后再决策）

测试 tests/test_precompute_contextual.py：
- mock LLM 跑 3 个 material → 输出 3 个 json 文件
- 重复跑 → 第二次零 LLM 调用（命中 gateway cache）
- 在线路径 miss → contextual_miss.jsonl 出现一行，无 LLM 调用
```

#### 3.7.3 §3.7 DoD

- [x] 一次性预计算 `laser_welding_109`（manifest 实际 108 个 material）已完成；dry-run 估算与运行证据记录在 `eval_reports/3_7_contextual_precompute_2026-04-30.json`，且查询期 contextual summary 代码路径保持 **离线只读 / miss 不调 LLM**（由 `tests/test_precompute_contextual.py` 与 `tests/test_contextual_chunker.py` 回归覆盖）
- [x] `contextual_miss.jsonl` 已完成历史噪声清理与 fresh-window 验证：历史 **706** 条匿名 miss（全部 `project_id=""`）已归档到 `output/contextual_miss_archive/contextual_miss_20260430T111436Z.jsonl`，随后用 `scripts/validate_contextual_miss.py` 对 `laser_welding_109` 全量验证（108 materials / 7225 chunks / validation miss = 0），并对 live miss 路径做全量 108 material replay，`output/contextual_miss.jsonl` 保持 **0** 行；证据见 `eval_reports/contextual_miss_validation_laser_welding_109_2026-04-30.json`

---

### 3.8 Generation 打包预算 + per-paper 上限（**真省钱项 #4**）

**状态**：✅ 代码切片已完成（2026-04-22），并于 2026-04-23 完成最终回答提示词对齐：新增 `evidence_packer.py`，`main_rag_workflow.py` 现按既有 score 顺序执行同 material `jaccard>0.9` 硬去重、超 soft budget 时 `jaccard>0.7` 次优冗余裁剪、`EVIDENCE_MAX_PER_MATERIAL=2` 上限、`EVIDENCE_PACK_TOP_K=5` 默认截断，以及 `EVIDENCE_TOKEN_HARD_CAP=5000` 的低分尾部裁剪；生成提示词现与用户提供的统一规范对齐，要求 **JSON-only** 输出、固定 schema（`conclusion/evidence/limitations/next_search/status`）、真实 `[chunk_id]` 原子引用、缺失信息写“文中未提及”、冲突时 `status="conflict"`。focused bundle `tests/test_evidence_packer.py tests/test_main_rag_workflow_generation.py -q` → **10 passed**。DoD 审计已补齐前两项硬证据（budget / per-material），提示词层面的 `[chunk_id]` 强制要求也已验证；但 answer-level grep 证据仍缺稳定运行时工件路径，故 §3.8 DoD 第 3 项继续保持阻塞。结果落地于 `output/audit_3_8_dod_results.json`。

#### 3.8.0 痛点

现状打包证据数量与 per-paper 上限没有显式控制；与 §3.1 MMR 协同后，需要在「打包到 prompt」这一最后一公里也设上限，避免长 prompt 触发限流。

#### 3.8.1 规范

- **目标证据预算（软目标）**：`EVIDENCE_TOKEN_BUDGET`，默认 4000 input tokens；超过先走“刪冗余”遻辑，不是直接砍 chunk。
- **绝对硬顶（hard cap）**：`EVIDENCE_TOKEN_HARD_CAP`，默认 5000 input tokens — 任何情况都不允许超过。
- **双 jaccard 阈值用途划分（不允许互相替代）**：
  - `0.9` — 硬去重：同 material_id 内 jaccard > 0.9 视为“几乎重复”，打包前直接删后者，**不看预算是否超限**。
  - `0.7` — 裁剪期次优冗余识别：**仅在超目标预算时**启用，同 material_id 内第二条 chunk 与第一条 jaccard > 0.7 优先删除；不超预算不启用，其它 kind 的去重也不用。
- 软目标到硬顶之间的取舍策略（**优先删冗余，不先砍高价值**）：
  1. 先按 §3.1 MMR / rerank 分排序，应用 0.9 硬去重
  2. 超 `EVIDENCE_TOKEN_BUDGET` → 启 0.7 次优冗余删除
  3. 仍超 `EVIDENCE_TOKEN_HARD_CAP` → 从最低分 chunk 倒着删，直到 ≤ hard cap（**这一步才会砍高价值，是最后手段**）
  4. 文献助手场景下复杂 query 允许打到 4000-5000 区间；4000 不是死线，5000 才是
- 默认打包 chunks：5（env `EVIDENCE_PACK_TOP_K`），可被硬顶逻辑下调
- 每篇 material 最多 2 chunks（env `EVIDENCE_MAX_PER_MATERIAL`）
- 答案必须含 `[chunk_id]` 引用（提示词层强制，见 `c:\Users\xiao\Desktop\回答提示词.md` 与 `c:\Users\xiao\Desktop\格式与约束.md` 的统一规范）

#### 3.8.2 接入

- 修改 `main_rag_workflow.py` 打包证据的位置（约 L430 附近）：调用新 helper `pack_evidence(candidates, budget, max_per_material) -> list[Chunk]`
- helper 放在 `text_utils.py` 或新模块 `evidence_packer.py`

#### 3.8.3 给 Team 的 prompt

```
任务：在 generation 链路加证据打包 + per-paper 上限。

实现：
1. 新增 evidence_packer.pack_evidence(candidates, budget_tokens, max_per_material, top_k) -> list[Chunk]
   - 按 score 排序后贪心打包：累计 token <= budget 且每 material_id 计数 <= max
   - jaccard 去重：相同 material_id 内文本 jaccard>0.9 跳过
2. main_rag_workflow.py L430 附近接入
3. 提示词模板使用用户提供的"最终回答提示词"（结论/依据/限制/建议继续检索四段式）

测试 tests/test_evidence_packer.py ≥ 5 case：
- 10 候选 6 同 material → 每 material 至多 2 入选
- 单条超 budget → 跳过取下一条
- 全部加起来不超 budget
- jaccard 去重生效
- 排序保留输入 score 顺序
```

#### 3.8.4 §3.8 DoD

- [x] 任一回答 prompt 实测 input tokens ≤ EVIDENCE_TOKEN_BUDGET — ✅ VERIFIED: Audit script (`scripts/audit_3_8_dod.py`) measured prompt=876 tokens ≤ budget (4000). Evidence section=821 tokens ≤ budget (4000). See `output/audit_3_8_dod_results.json`. **CORRECTED**: Previously checked against hard_cap (5000), now correctly checks against EVIDENCE_TOKEN_BUDGET (4000).
- [x] 同 material 在最终 prompt 中出现 ≤ 2 次 — ✅ VERIFIED: Audit script confirmed max_per_material_observed=2, within limit. Material distribution: `{'paper-a': 2, 'paper-3': 1, 'paper-4': 1, 'paper-5': 1}`.
- [ ] 答案 100% 含 `[chunk_id]` 引用（grep 校验）— ❌ BLOCKED: Plan requires answer-level grep evidence ("答案 100% 含 [chunk_id] 引用"), but no stable grepable runtime artifact path exists for generated answers in current codebase. Prompt enforcement (necessary condition) is verified: prompt template requires "每条事实必须绑定真实 [chunk_id]", evidence format uses `[{chunk_id}]` pattern, and "文中未提及" instruction present. However, this is NOT sufficient to close DoD 3 per plan requirements. **Blocker**: Need runtime answer artifact path or integration test that captures and greps actual LLM responses to prove 100% citation compliance.

---

## 4. P2 — 隐性问题清理（Team，每项独立 PR）

每项独立 ticket，禁止合并提交。优先级用 P2-a (本月) / P2-b (本季度) / P2-c (背景) 标注。

| ID | 项 | 优先级 | 文件/范围 | 给 Team 的最小指令 |
|---|---|---|---|---|
| L1 | `routers/resources_router.py` `_load_chunk_store` 单进程并发写不安全 | ✅ 已完成 (2026-04-21) | resources_router.py | 加 `threading.Lock()` 保护读改写；测试构造两线程并发写，断言 chunk count 不丢失 |
| L2 | `chunk_vector_store.py` embedding cache 失效仅按 mtime，模型切换不重建 | ✅ 已完成 (2026-04-23) | chunk_vector_store.py | cache 文件名嵌入 `model_name + dim` 哈希；切模型自动失效；单测：mock 两个 model，分别 build 应得两份独立 cache |
| L3 | `routers/runtime_router.py` 缺 resume/rewind/fork/checkpoint | P2-b | 设计文档 `CONVERSATION_PERSISTENCE_DESIGN.md` | **此项需 §5 升级范围审批后再启动**；当前不要动，只把现状写进 OPEN_THREADS.md |
| L4 | `BatchParser` 串行处理 109 篇 ~30 min | ⛔ 验证阻断（建议以 12 篇内置数据集证据关闭） | extract_pdfs.py | 启用 `concurrent.futures.ThreadPoolExecutor`，`max_workers=os.cpu_count()`；先在 30papers 上验证再放 109 — **✅ 代码已落地并通过单测（3 cases, 0.11s）**；**⛔ 30papers 验证路径不存在**：extract_pdfs.py 是独立诊断脚本（硬编码 12 篇论文列表），未被 pipeline_core.py / batch_process_30papers.py 调用；生产流水线并行化已在 batch_process_30papers.py / batch_process_109papers.py 独立落地（tests/test_batch_parallel_processing.py 通过）；**建议关闭 L4 并记录：代码实现已验证，验证范围与生产流水线解耦；12 篇内置验证已运行（3s 完成，并行输出可见）** |
| L5 | LightRAG `BaseKVStorage` 抽象未启用 | P2-c | (背景调研) | **此项需 §5 升级范围审批**；先调研一份 1 页的可行性 memo 落 `notes/lightrag-kv-feasibility.md`，不写代码 |
| L6 | `rerank_cache` TTL 12h 在评测高频复用过短 | ✅ 已完成 (2026-04-23) | rerank_cache.py | 加 env `RERANK_CACHE_MODE`：`ttl`（现有）/ `corpus_version`（语料 SHA 不变即永不过期）；默认仍 ttl，评测脚本切 corpus_version |
| L7 | `output/` 无 rotation | ✅ 已完成 (2026-04-23) | scripts/rotate_output.py | 写归档脚本：`output/llm_cost.jsonl` / `rerank_cost.jsonl` 大于 64 MB 时按月份归档到 `output/archive/YYYY-MM/`；docs 写一句"运维每周一手动跑" |
| L8 | 没有 `requirements-pin.txt` | ✅ 已完成 (2026-04-23) | (新建) | `pip freeze > requirements-pin.txt` 当前环境为基线；CI 加 step：用 pin 文件装环境跑 pytest |

**给 Team 的总 prompt 模板**（每项 ticket 复用）：

```
任务：解决 P2-{ID} {项}。

约束：
- 独立 PR，不混提其它 P2 项
- 修改面 ≤ 2 文件 + 1 测试文件
- 不引入新依赖（除非 ticket 明确允许）
- 不重构无关代码

完成判据：
- pytest tests/ -q 全绿
- 新增至少 1 个回归测试覆盖修复点
- PR 描述写明：根因 / 方案 / 风险 / 回滚步骤
```

---

## 5. 升级范围（Scope Boundary）—— 真升级 vs 应立刻做的省钱项

> **重写说明**：旧版把所有 U1-U12 一刀切「禁止本批次执行」过严。本节重新定义：只有**确实改变系统拓扑、引入新外部进程、或推翻核心抽象**的才需要 Morpheus 签字。其它"看起来像升级但实际上是省钱项"的工作，**必须**在本批次执行（已在 §3.5–§3.8 落地为 P1 任务）。

### 5.1 三档分类

| 档 | 定义 | 例子 | 流程 |
|---|---|---|---|
| **A. 真升级（强签字）** | 改系统拓扑、引入新外部服务/进程、替换核心抽象 | 引入 Redis、换向量数据库、推翻 LightRAG | Morpheus 立项 memo → 独立计划 → 独立 PR → 一周灰度 |
| **B. 普通优化（直接做）** | 调参、加 env flag、加缓存、修 bug、加测试、改 prompt | §1/§2/§3/§4 全部任务 | 走普通 PR 流程 |
| **C. 边界省钱项（必须本批次做）** | 看起来像"升级"但本质是 ROI 极高的省钱重构 | 离线化 contextual summary、统一 gateway、chunk 体积阀门 | 已写入 §3.5–§3.8，**不再走升级流程** |

**判定原则**：默认按 B 处理。只有同时满足"新外部服务 + 新部署依赖 + 替换抽象"才升 A。模糊地带先按 B 做，做完再回看是否触发 A 的硬约束。

### 5.1.1 状态标签规则（多 agent 分工避免误判）

本文件每一条 ticket 必须带状态前缀，便于 agent 接手时秒判要不要做：

| 标签 | 含义 | 行为 |
|---|---|---|
| `✅ 已完成` | 本 Copilot 会话或之前已实装并通过测试 | 不要再 reimplement；只能改 bug 或加 DoD 补丁 |
| `🔧 待 team 执行` | 规范已定，等 squad team 接手实装 | 走对应小节的 prompt + DoD |
| `🟡 待合并` | 代码已出但未合主干 / 等评审 | 不要新开 PR，去 review 现有 PR |
| `🔵 待决策` | 需要 Morpheus / 用户拍板（如 §5.2 A 档触发） | 不要预先写代码或预先 mock |
| `⛔ 本批次不做` | 明确推到下一批次 | 见到即跳过，不做、不调研、不预研 |

现有 §0 / §1.1-1.3 / §2.x / §3.x / §4.x / §5.x 中既有的「状态」字段（如 §1.3 的「✅ 已完成（2026-04-21，本轮）」）继续保留，新增 ticket 必须用上表枚举值；存量 ticket 在下一次编辑该节时顺手补上即可，不另起 PR 批量回填。

### 5.2 真升级清单（A 档，本批次禁止执行；触发后才启动）

| ID | 项 | 为什么是 A 档 | 触发条件 |
|---|---|---|---|
| U1 | 引入 Redis / Memcached 做跨进程缓存 | 新外部服务 + 部署依赖 | 单机内存 cache 命中率 < 30% 持续 2 周（§3.6 落地后再看） |
| U2 | 引入 Postgres / 向量数据库（Chroma/Weaviate/Milvus）替换 chunk_store + npy | 新外部服务 + 数据迁移 + 替换核心抽象 | chunk_store 单 project_id 总量 > 5 GB 或并发用户 > 10 |
| U3 | 推翻 LightRAG / RAG-Anything 集成 | 替换核心抽象 + 大面积 API 契约破坏 | LightRAG 上游不再维护 或 性能瓶颈无法用插件解决 |
| U4 | 引入异步任务队列（Celery / RQ / Dramatiq） | 新外部服务 + 新常驻进程 | 单次任务 > 30 min 且需要跨进程恢复 |
| U5 | 引入 Prometheus / Grafana 监控栈 | 新外部服务 + 新常驻进程 | 运维明确要求秒级监控（当前 jsonl + 日 cron 足够） |
| U6 | 切换 LLM SDK（OpenAI → LiteLLM 等） | 替换核心抽象 + 全链路调用形态变化 | 当前 SDK 多 vendor 适配成本 > 单独写 adapter |
| U7 | 实现 conversation persistence 全功能（resume/rewind/fork/checkpoint） | 新 schema + 新 API 契约扩展 + 数据迁移 | 用户明确提需求 + 设计文档 review 通过 |

**注意**：换 embedding 模型 / 换 rerank 模型 / 换 LLM provider **不在** A 档。它们走 §3.3 的实验矩阵 + §3.6 gateway cache_key 自动失效机制，正常 B 档 PR 即可。

### 5.3 边界省钱项清单（C 档，已在 §3 落地，本批次必须做）

本档不再重复拆成新的平行任务表，直接以 `§3.5–§3.8` 为准：

- `§3.5` Chunk 体积硬阀门 + eval runtime 对齐 v2 chunk store
- `§3.6` 统一模型调用 gateway + 高置信 rerank skip + 429/Retry-After
- `§3.7` Contextual summary 离线化
- `§3.8` Generation 证据打包预算 + per-paper 上限

这些项**单独一项的 ROI 都高于换底模**，必须在升级评估之前完成。

### 5.4 真升级（A 档）流程

1. **立项 memo**：`notes/upgrade-{YYYY-MM-DD}-{slug}.md`，含触发条件、备选方案 ≥ 2、迁移路径、回滚预案、预算
2. **Morpheus 审批**：`.squad/decisions.md` 留痕
3. **独立计划文档**：`.copilot-tracking/plans/YYYY-MM-DD-upgrade-{slug}.md`
4. **独立分支 + 独立 PR**
5. **灰度 + 监控**：一周观察 `llm_cost.jsonl` + `rerank_cost.jsonl` + 检索质量指标
6. **回滚演练**：合并前演示一次回滚

### 5.5 明确 **不算** 升级的（避免过度审批）

- 同 vendor 内换 model 版本（如 qwen-max-2024-09 → qwen-max-2024-12）
- 引入轻量 stdlib 工具（如 §3.2 的 cjk_aware_tokenize）
- 调超参 / 加 env flag / 加缓存 / 加退避
- 加测试 / 加埋点 / 加只读端点
- prompt 文案微调（不改 schema）
- 价格表更新（§2.2.3 已降级为最低成本制度）

### 5.6 §5 DoD

- [ ] §3.5–§3.8（C 档）全部按 B 档普通流程做完，不走升级审批
- [ ] PR grep 不出现 U1-U7 的关键字（Redis/Postgres/Chroma/Celery/LiteLLM/Grafana 等），出现即阻断 CI
- [ ] §5.2 触发条件在每周巡检脚本中自动检测；命中才在 OPEN_THREADS.md 留 ticket
- [ ] 不为「未触发」的 A 档项预先写代码、预先调研、预先 mock

---

## 6. 推进、灰度、回滚、监控

### 6.1 上线顺序（强制，违反需 Morpheus 同意）

```
W1: 1.3 预算阀门（已上线）→ 1.2 候选上限（已上线）→ 1.1 chunk_store 重构（已上线）
W2: 2.1.1 ai_adapter 7 site 接入 → 2.2 测试 + cost 端点 → 2.1.2 user sampling 持久化
W3: 2.1.3 前端面板（用户确认 UI 后）→ 3.1 MMR
W4: 3.2 中文分词 → 3.3 Phase 6 评测 → 3.4 测试推广
W5+: P2 项逐项上（每项独立 PR）
```

### 6.2 每个 PR 的强制要求

- [ ] 一个 PR 一个 ticket（P0/P1/P2 编号）
- [ ] PR 描述含：根因 / 方案 / 影响面 / 测试 / 回滚步骤 / 监控指标
- [ ] CI：`pytest tests/ -q` 全绿
- [ ] CI：lint / type check（用现有 ruff / mypy 配置）
- [ ] 不引入新依赖（如必须，单独 PR 加 requirements，先评审）
- [ ] 不动 §5 升级范围内的代码

### 6.3 灰度策略

| 类型 | 策略 |
|---|---|
| 阀门 / 限流（1.2 / 1.3 / RerankBudgetGuard） | env flag 默认开，可一键关 |
| 行为变更（1.1 chunk_store 重构、2.1 sampling 接入） | 双写双读 1 周，观察无 diff 后切单写 |
| 算法改动（3.1 MMR、3.2 分词） | A/B 评测脚本对比基线，Recall@5 退化 ≥ 2% 立刻回滚 |
| 数据格式变更（1.1） | 旧文件 `.legacy.bak` 保留 30 天 |

### 6.4 监控告警

| 指标 | 来源 | 告警阈值 | 动作 |
|---|---|---|---|
| 当日 rerank 成本 | `output/rerank_cost.jsonl` | ≥ 200 元 | 微信群 + Morpheus |
| 当日 LLM 成本 | `output/llm_cost.jsonl` | ≥ 100 USD | 微信群 + Morpheus |
| Recall@5 滑动均值 | 评测 cron | < 基线 -2% 持续 24h | 自动回滚最近一次 PR + 通知 |
| `output/` 单文件大小 | 巡检脚本 | > 256 MB | 触发归档（§4 L7） |
| pytest 失败率 | CI | 任一失败 | 阻断合入 |

### 6.5 回滚 Playbook

每个 PR 必须在描述里写 1 行回滚命令（一般是 `git revert <sha>` + 灰度开关 env=0）。重大变更（1.1 / 2.1 / 3.1）需在 PR 提交前手动演练一次回滚。

### 6.6 §6 DoD

- [ ] 上线顺序写进 `.squad/decisions.md` 作为约束
- [ ] CI 加 lint / mypy step
- [ ] 监控指标看板（最简：每天 cron 跑一次脚本输出到 `output/daily_health.txt`，运维肉眼看）
- [ ] 回滚 playbook 在每个 PR 描述模板中预填占位
