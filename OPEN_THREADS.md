# OPEN_THREADS — 跨计划阻塞与开放项总索引

> **用途**：四份在编计划（cost-and-defaults / advanced-retrieval-phased / playful-meadow / squad-audit）的未完成项汇总索引。任何 agent / Copilot / 用户接手前 **先 grep 这里**，避免重复发起已在 hold 的工作。
>
> **不是**：决策面（看 `.squad/decisions.md`）、执行日志（看 `.squad/orchestration-log/`）、squad 内部记忆（看 `.squad/memory/OPEN_THREADS.md`）。
>
> **维护契约**：
> - 新增开放项 → append 到 "Active"
> - 已关闭 → 移到 "Closed" 并写 resolution
> - 需要人操作的 → 标 ⏳ WAITING FOR USER / OPERATOR
> - 证据锚点必填（文件路径 + 行号或 commit）

---

## Active — 阻塞 / 待执行

### A1. [rerank-key-resolution-redesign] 🔵 待 Copilot 执行 2026-04-24

- **Description**：`reranker_client.resolve_rerank_config()` 按 provider 名字选 key，导致 38-char 的 `SILICONFLOW_API_KEY`（embedding-only）被误用到 rerank endpoint，返回 401。用户指令："不要只识别 siliconflow，重点识别 key"。
- **Scope**：`reranker_client.py:69-134` — 加 `_probe_rerank_key` 辅助 + 重写 `resolve_rerank_config` 为 validity-first；`tests/test_reranker.py` 补 §5.1-§5.4 四个单测。
- **Design spec**：`.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md`（Path B，含完整代码 + 执行 checklist）。
- **回滚杠杆**：`RERANK_KEY_PROBE_DISABLE=1` 环境变量一键回到旧静态顺序。
- **Blocks**：
  - `cost-and-defaults §3.3` E1-E4 contextual 对比（embedding 401）
  - `cost-and-defaults §3.6 DoD #2` 109 篇评测 cache hit 验收
  - `cost-and-defaults §3.7 DoD` precompute 用时记录
  - `advanced-retrieval §2026-04-18` Phase 5 full v2.1 评测的 ground-truth 对齐判定（需要 rerank 稳定才能比较）
- **Evidence**：`output/trinity_rerank_probe.log` / `output/trinity_rerank_probe_metrics.json` / `.squad/decisions/inbox/trinity-rerank-401-rootcause.md`
- **Owner**：Copilot（已交付 spec，待落代码）

### A2. [tier2-metrics-gating-unclosed] 🔧 阻塞在 A1 2026-04-24

- **Description**：Tier 2 门禁 Recall@5 ≥ 0.45 / MRR ≥ 0.30 在样本上未达标。Phase 5（translated-first, 30q 样本 R@5=0.500 / MRR=0.346）已接近达标但样本太小；Phase 6 contextual 在同样本上反而下降（-0.033）。
- **Blocked by**：A1（无可用 rerank 凭证，无法复现稳定基线）+ full v2.1 与 canary 指标落差根因未签核（疑似 qrels 结构问题）。
- **出处**：`advanced-retrieval-phased-execution.md §2026-04-24 补记`，`2026-04-20-latest-unified-plan.md §3.A-1`
- **Next step（A1 解封后）**：
  1. 在 goldset 上跑 8B rerank control
  2. 抽样 100 条 v2.1 query 的 `evidence_set` doc_id 做命中率体检（若 < 1.0 → qrels 问题，不是召回问题）
- **Owner**：待用户调度（当前挂）

### A3. [step3-24cell-sweep-not-launched] ✅ CLOSED 2026-04-24（晚间）

- **Resolution**：24 格 sweep 已跑完（`output/109papers_step3_*.metrics.json` 全部 24 份产物齐全）。Winner 选出：
  - `tag = 109papers_step3_r200_rr40_rerank`
  - `recall_top_n=200, rerank_top_n=40, use_rerank=true`
  - `recall@5 = 0.87`，`MRR = 0.6798`（与 control 匹配容差内，verdict `matches-control-within-tolerance`）
  - `avg_latency_ms = 3337.54`（相较 control `9912.58` -66%），`p95 = 4084.47`（-68%）
  - `ready_for_full_u1_eval = true`
- **Evidence**：`output/109papers_step3_best.json`
- **Caveat**：sweep rerank 用了 warm cache（winner `rerank_attempts=0` 且无 auth 失败），冷启动 latency 未保证 → 需在 full U1 eval 阶段复验
- **Next**：用 winner 配置跑 full v2.1 U1 eval（Copilot 已在做 2400/3269 checkpoint）
- **原 Description**：Step 3 参数优化 24 格 sweep（`recall_top_n × rerank_top_n × use_rerank`）契约见 `.squad/decisions/inbox/ralph-u1-closure-prep.md:85-138` + `.squad/decisions.md → "Step 3 24-Cell Sweep Contract"`

### A4. [ghost-running-step3-sweep] 🔴 需终端核实 2026-04-24

- **Description**：`oracle-step3-sweep-run` 仍"running"但 `output/109papers_step3_r*` 与 summary 产物 **0/24**。按 `routing.md rule 21-22` ghost-running = 硬失败。
- **Blocked by**：需人工在本机核 PID 是否真的还在跑；squad 的 stale-cleanup 未自动触发。
- **Evidence**：`.squad/decisions/inbox/morpheus-step3-parallelization.md:4`
- **Owner**：用户（核 PID → 决定 kill / 等待）

### A5. [bad-chunk-quarantine-pending] 🟡 待维护窗口 2026-04-24

- **Description**：两条 material 被识别为检索污染源（Elsevier 索引页，标题泄漏）：
  - `laser_welding_109 / mat_f3a6d624e49b`
  - `laser_welding_30 / mat_b47cec6097cb`
  - Reslice 无法修复（标题在 manifest / metadata 层泄漏）。
- **Scope**：需从 corpus 中 quarantine，manifest 标注 `quarantined_at`。
- **Evidence**：`.squad/decisions/inbox/oracle-bad-chunk-optimization.md`
- **Blocks**：U1 全量评测指标稳定性
- **Owner**：用户（corpus 变更需在维护窗口）

### A6. [routers-init-missing] ✅ CLOSED 2026-04-24（晚间）

- **Resolution**：`routers/__init__.py` 存在，`python -m pytest tests/test_runtime_router_contract.py --collect-only -q` 返回 **5 tests collected**（无 collection error）。5 个 case：
  - `test_runtime_events_route_supports_incremental_polling`
  - `test_runtime_session_routes_cover_workspace_lookup_resume_rewind_and_fork`
  - `test_runtime_router_handles_invalid_session_ids`
  - `test_runtime_router_handles_invalid_job_ids`
  - `test_runtime_router_rejects_invalid_session_mode`
- **Closed by**：Claude 2026-04-24 晚间验证

### A7. [conversation-persistence-mvp-followthrough] 🟢 S-1~S-5 全部收口 2026-04-25

- **Description**：会话级 `/runtime/sessions` `/resume` `/rewind` `/fork` 后端 + 前端 MVP，分 5 个 sprint task：
  - S-1 后端存储（SQLite + blob spill）— **✅ 2026-04-25 D-plan 收口（Claude）**：
    - spill 阈值对齐 SPEC §S-1.3：8 KB → 64 KB，`MODULAR_BLOB_SPILL_BYTES` env 可调
    - 新增 `_rehydrate_payload` + 在 `load_transcript` 里做 read-through（填补了 Morpheus 复核发现的"resume 后 payload 仍是 blob_ref 壳"缺口）
    - `_prepare_transcript_event` 对已 spill 的事件幂等（`replace_transcript` 修复路径不会 orphan blob）
    - `tests/test_writing_runtime_blob_spill.py`（3/3 green）+ `tests/test_writing_runtime_persistence.py`（4/4 无回归）
    - 新增 `scripts/migrate_modular_sessions.py --dry-run` 健康检查 + mkdir idempotent
    - **暂缓**（记账给 §10.4）：表重命名 `jobs/events/artifacts → turns/tool_calls/branches`、blob 路径 `blobs/{sid}/{bid}.bin`、数据迁移
  - S-2 E2E 测试 — **✅ 2026-04-25 晚间收口（Claude squad-manager 终端）**：`tests/test_conversation_persistence_e2e.py` 从 5 case 扩到 8 case，新增 S-2.6 fork-of-fork（grandchild parent 指直接父，不是 root）、S-2.7 timeline 游标分页（full == paged，无 gap 无 dup）、S-2.8 migration health-check 幂等（第二次 `applied_actions == []`，counts 不变）。8/8 green。未做 speculative 的 concurrent-writers / 人造 perf budget — 按 CLAUDE.md §2 拒绝为测试造不存在的契约。
  - S-3 前端 types + service — **✅ 2026-04-24 晚间完成（Claude）**（见前次 entry）
  - S-4 Workbench Session Drawer — **✅ 2026-04-24 晚间完成（Claude）**：`SessionDrawer.tsx` + helpers + `node --test` 11/11 + Workbench trigger
  - S-5 Rewind 安全弹窗 — **✅ 2026-04-24 晚间完成（Claude）**：`RewindConfirmModal.tsx`（mode selector + 回滚快照提示）
- **Blocks**：无（`unified-plan §U3` 可以整体收口 — S-1 ~ S-5 全绿）
- **Spec**：`CONVERSATION_PERSISTENCE_DESIGN.md` + `docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §10`（D-plan addendum 2026-04-25）
- **Owner**：Claude（已全部落地），团队验收

### A8. [ai-adapter-downstream-llm-cost-wiring] 🟢 等效完成（已无扩散目标）2026-04-25

- **Description**（原）：§2.1.1 Site 1-7 已接入 `_chat` helper；下游 `inspiration_engine.py` / `extractor_full.py` / `summarizer*.py` 仍需扩散。
- **Resolution 2026-04-25**（Claude manager 复核 Dozer worker 升级）：独立 grep 验证三项事实 ——
  1. `chat.completions.create` 全仓**仅剩 1 处**，就是 `layers/ai_adapter.py:212` 的 `_chat` helper 自己（即扩散的终点，不是扩散的源）。
  2. 主仓 `inspiration_engine.py` 和 `extractor_full.py` 均**零 LLM 直调**（`openai` / `AIAdapter` / `model_call_gateway` / `litellm_gateway` import 零匹配）——文件里根本没有 call site 可供 wrap。
  3. `summariz*.py` 主仓**不存在**（glob 命中只有 `.venv` / `.rollback_snapshots` / 三方 `github\sa-rag-0.1.0`，不可触碰）。
- **Judgement（CLAUDE.md §2/§3）**：为了"扩散"而**发明**一个本不存在的 LLM call 再包装，等于凭空扩大作用域。A8 的实际目标——"所有 LLM call 都走 task-tagged 统一通道"——已经被 `_chat` helper + 下游已迁移到 `AIAdapter` / `litellm_gateway` 的路径等效满足。没有剩余 diffusion 目标。
- **Evidence**：`.squad/decisions/inbox/dozer-a8-diffusion-escalation.md`（worker 原子落盘的升级申请）；本文件 manager 复核 grep 落 `.squad/orchestration-log/2026-04-25T03-00-00Z-a8-dozer-escalation-ruling.md`。
- **Next**：若未来有 agent 新加 LLM call site（不走 `AIAdapter._chat` / `litellm_gateway`），直接走新任务流程，不复活 A8。
- **Owner**：Claude manager（已裁决）+ Dozer worker（已无需执行代码）

### A9. [lightrag-kv-feasibility-memo] 🟢 FILLED — 推荐不采纳 2026-04-25

- **Description**：P2-L5 "调研一份 1 页的可行性 memo 落 `notes/lightrag-kv-feasibility.md`，不写代码"
- **Status**：2026-04-25 已填（Claude squad-manager，task #31）。Memo 推荐**不采纳** `BaseKVStorage` 作为统一 KV 抽象，理由：上游接口 async + 绑定 `embedding_func` + `StorageNameSpace` 父类，是 RAG 专用 KV 不是通用 KV；我们 43 处 cache 调用里 LLM cache + rerank cache 根本不该持有 embedding 语义。推荐"只借 `filter_keys` 语义"做 10-20 行小助手，不抄接口。432 词，符合 1 页限。
- **Evidence**：`notes/lightrag-kv-feasibility.md`（§1 上游事实已验 / §2 3 FOR + 3 AGAINST / §4 推荐 / §6 引用）
- **Next**：等 engineering override 或签字同意；同意后可开"在 `chunk_vector_store` 加 `missing_keys` 辅助"小任务。
- **Owner**：Claude（memo 已写），team（审阅 + 签字）

### A10. [p2-l3-runtime-router-persistence] 🔵 待升级范围审批 2026-04-24

- **Description**：P2-L3 `routers/runtime_router.py` 缺 resume/rewind/fork/checkpoint。已在 A7 通过 MVP 落地 `/runtime/sessions` 端点；但完整 persistence schema（§5.2 U7 A 档）**仍在升级范围内**，本批次不触碰。
- **Owner**：用户 / Morpheus（触发 §5.2 审批条件才启动）

### A11. [embedding-rerank-testing-gaps] 🟢 3/4 修完 + R5 defer-per-decision 2026-04-25

- **Description**：外包 AI 执行 `docs/superpowers/plans/2026-04-25-embedding-rerank-test-handoff.md` E1-R5 清单（2026-04-25 完成，39 passed / 4 skipped / 2 xfailed），发现 4 个行为 gap。Claude squad-mode 2026-04-25 晚间批量修复。
- **Gaps 状态**：
  1. **E1 – Embedding provider resolver** ✅ CLOSED 2026-04-25：`runtime_env.py` 加 `_select_embedding_provider()`（priority: `EMBEDDING_PROVIDER` env → SiliconFlow if key → Jina if key → SiliconFlow default）+ `resolve_embedding_config` 按 provider 分支，Jina 分支走 `JINA_API_KEY` + Jina URL/model，SiliconFlow 分支逐字保留 legacy 行为。`tests/test_embedding_provider_resolution.py` 3 skip 翻 pass（no-key case 保持 None-return 以维持 backward-compat，test 下调为 `assert api_key is None`）。
  2. **R4.1 – 单候选 short-circuit** ✅ CLOSED 2026-04-25：`reranker_client.py` L568 加 `if len(candidates) == 1: return candidates[:top_k]`（在空 list 检查之后），不再打 HTTP。`test_single_candidate_short_circuits` xfail 翻 pass。副作用：`test_rerank_async_honors_retry_after_header` 原用 1 candidate 也被短路，已同步改为 2 candidates + 注释。
  3. **R4.2 – top_k ≤ 0 raise ValueError** ✅ CLOSED 2026-04-25：同点改为 `if top_k <= 0: raise ValueError(...)` 前置，显式 fail-fast。`test_negative_or_zero_top_n_raises` xfail 翻 pass。
  4. **R5 – `retrieve_then_rerank(query, corpus, top_k)` 单入口** 🔵 DEFERRED 2026-04-25（决策见 `.squad/decisions.md`）：分析 3 个 retrieve→rerank callsite（`r_layer_hybrid_retriever.py` / `chat_router.py` / `eval_retrieval_runtime.py`）发现 config / context / 签名不重叠（hybrid fuse 前 vs. router 调度 vs. eval harness），按 CLAUDE.md §2 Simplicity First 判定此抽象尚无统一契约 → 维持 `test_retrieve_then_rerank_smoke.py` skip。触发条件：任一 U4/U6 计划决定把 retrieval→rerank 提到 router 级 helper 时，翻出此 defer 评审。
- **Final verification**：`py -3.14 -m pytest tests/test_embedding_provider_resolution.py tests/test_embedding_batch_chunking.py tests/test_reranker.py tests/test_rerank_cache_key_stability.py tests/test_rerank_budget_concurrency.py tests/test_rerank_short_circuit_and_budget.py tests/test_retrieve_then_rerank_smoke.py -v` → **44 passed, 1 skipped**（仅 R5 defer 的 skip 保留）。Broader regression sweep `pytest tests/test_writing_runtime_persistence.py tests/test_writing_runtime_blob_spill.py tests/test_conversation_persistence_e2e.py tests/test_rerank_budget.py tests/test_rerank_cache_mode.py -v` → **20 passed**，无回归。
- **Changed files**：`runtime_env.py`（+~50 行 provider branch）、`reranker_client.py`（L568 prelude 重写）、`tests/test_embedding_provider_resolution.py`（3 skip → assert）、`tests/test_rerank_short_circuit_and_budget.py`（2 xfail → 直接 assert/raises）、`tests/test_reranker.py`（retry-after test 2 candidates + comment）。
- **Rollback**：git revert 以上 5 个文件即可。
- **Owner**：Claude（已收口 3/4 + R5 决策）

---

## Closed — 已关闭（保留索引，便于追溯）

### C1. [rerank-401-canonical-fix-v1] ✅ CLOSED 2026-04-24 → 升级为 A1
- **Resolution**：config-only 修复（`SILICONFLOW_RERANK_API_KEY = RERANK_API_KEY`）已进 `.squad/decisions.md`。用户随后指出应 "重点识别 key"，已升级为 validity-first 方案（A1）。config-only 保留为兜底。

### C2. [inbox-canonical-merge-15-items] ✅ CLOSED 2026-04-24
- **Resolution**：15 份 inbox decision 已于 squad 审计中归并为 6 条 canonical decisions（prepend 到 `.squad/decisions.md`）。
- **Closed by**：Squad Coordinator 2026-04-24 audit

### C3. [scribe-gap-2h15m] ✅ CLOSED 2026-04-24
- **Resolution**：2026-04-24 19:32 之后的 Scribe gap 已补 `.squad/log/2026-04-24-late-session-audit.md` + `.squad/orchestration-log/2026-04-24T22-00Z-audit-scribe-catchup.md`。

### C4. [chunk-size-guard-reslice] ✅ CLOSED 2026-04-22
- **Resolution**：80 个 oversize material 已定向重切，`oversize_materials_report.json` 归零。

### C5. [u1-conversation-persistence-api-mvp] ✅ CLOSED 2026-04-24
- **Resolution**：`/runtime/sessions` / `/resume` / `/timeline` / `/rewind` / `/fork` / `/checkpoints` 后端已落地，Tank 批准。前端 U3 留给 A7。

### C6. [routers-init-missing] ✅ CLOSED 2026-04-24（晚间）
- **Resolution**：原 A6。`routers/__init__.py` 存在，runtime_router contract test 5/5 collected。移出 Active。

### C7. [step3-24cell-sweep] ✅ CLOSED 2026-04-24（晚间）
- **Resolution**：原 A3。24 格全部跑完，winner = `r200_rr40_rerank`（recall@5=0.87, MRR=0.6798, verdict `matches-control-within-tolerance`），`output/109papers_step3_best.json` 落地。`ready_for_full_u1_eval=true`。移出 Active。

---

## 索引：哪份计划要看哪个 Active 项

| 计划 | 直接相关 Active |
|---|---|
| `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` | A1 A2 A8 A9 A10 |
| `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md` | A1 A2 |
| `.kilo/plans/1776608354894-playful-meadow.md` | A2 A3 A7 |
| `.claude_squad/decisions/2026-04-24-squad-audit.md` | A3 A4 A5 A6（全部审计列出的 Scope C） |
| `docs/superpowers/plans/2026-04-20-latest-unified-plan.md` | A2 A3 A7 |

---

**Last updated**: 2026-04-25 晚间 (Claude squad-manager: A7.S-2 closed, A9 memo filled "不采纳", A8 ruled "等效完成-无扩散目标" after Dozer worker escalation; A11 batch closed earlier)
