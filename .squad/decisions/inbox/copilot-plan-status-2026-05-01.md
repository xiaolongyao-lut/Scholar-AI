# Copilot Plan Status — 2026-05-01

Meta-review of active plans and status snapshots, validated against the actual repository state as of 2026-05-01.

## Facts

### Plan A — `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` (972 lines)
Estimated completion: **~85%**. Inline annotations in the plan and verified artefacts in the repo agree:

| Slice | Status | Evidence |
| --- | --- | --- |
| §2.1.1 ai_adapter._chat 7 sites | ✅ done | `ai_adapter.py` (本会话已落) |
| §2.1.2 sampling storage + router | ✅ done | `ai_sampling.py`, `python_adapter_server.py:424-449`, `tests/test_sampling_router.py:7-15` |
| §2.1.3 前端 sampling 面板 | ✅ done | frontend Switch wired |
| §2.1.4 总验收 (curl checks) | ⚠️ open | 多项 `[ ]` 未勾, 仅缺手动验证 |
| §2.2 llm_pricing/llm_cost_logger | ✅ done | `llm_pricing.py`, `llm_cost_logger.py:1-77` (fail-open JSONL `output/llm_cost.jsonl`, `pricing_known=false` for unknown models) |
| §2.2.A/B 测试 + router 接线 | ✅ done | `tests/test_llm_pricing.py`, `tests/test_llm_cost_logger.py` |
| §2.2.5 DoD | ⚠️ open | 余 2 项: `LLM_COST_TELEMETRY=0` 关闭路径验证 + `status="error"` 路径覆盖 |
| §3.1 MMR 多样性 | ✅ done | 109 篇 / 100 query 验收 PASS (2026-04-22) |
| §3.2 cjk_aware_tokenize | ✅ done | 2026-04-22 |
| §3.3 Phase 6 contextual eval | ⏸️ BLOCKED | 需重建 cache 才能跑 E1-E4 |
| §3.4 测试推广 (smoke/chunk/rerank) | ✅ done | 2026-04-22 |
| §3.5 chunk 体积阀门 | ✅ done | 历史脏 chunk 重切归零 (scanned=11447, oversize=0) |
| §3.5.6 DoD | ⚠️ open | 余 2 项: `rerank_cost.jsonl` 候选 ≤5000 字符校验 + manifest-first 109/canary 一致性 |
| §3.6 model_call_gateway | 🔄 in-progress | Step 1-5 全落地, focused tests 52+35+15 passed; clean rerun: rerank invoke 95→0, hit 2→62, latency 1457→950ms; 余: full-U1A3269 rerun (可选), `corpus_embeddings*.npy` 显式清理演示 |

Open items (4): §2.1.4 curl 验收, §2.2.5 余 2 项, §3.3 cache 重建 (BLOCKED), §3.6 余项 (可选).

### Plan B — `.kilo/plans/2026-04-27-squad-official-capability-reuse.md` (599 lines) — REVISED 2026-05-01
Estimated completion: **gate-passed (≈100%)**. T5 实际已由 codex 在 2026-05-01 落地, Phase A 五段验收已由用户当面签收。

| Task | Status | Evidence |
| --- | --- | --- |
| T1 Squad-only entry | ✅ done | `.github/agents/claude-squad.agent.md` 描述明示 "Read-only bridge — Claude Code is the primary Squad runtime. Use Squad agent for main coordination workflow." |
| T2 Plan agent 复用 | ✅ done (decision) | `.github/copilot-instructions.md` Decision Map **D4=B** |
| T3 官方 subagents 复用 | ✅ done | `.github/agents/` 已含 Frontend Orchestrator / Expert React Frontend Engineer / Frontend Performance Investigator / gem-designer |
| T4 Copilot CLI 长跑接管 | ✅ done | Decision Map **D7=B**; `tools/squad/squad.ps1.deprecated` + `README-DEPRECATED.md` |
| T5 拆 prompts/skills | ✅ done | `.github/prompts/{squad-doctor,squad-plan,squad-round}.prompt.md` 三件套齐全; `prompts.md` 已重命名 `.deprecated`; `.github/skills/{squad-startup-packet,squad-cli-handoff}/SKILL.md` 均存在 |
| T6 Hooks + diagnostics | ✅ minimal | `.github/hooks/squad-governance.json` 存在; 触发点黑盒验证留作未来长跑时观察 |
| Phase A 五段验收 | ✅ USER-APPROVED PASS | smoke 6/6 + profile-version v4 + check-ghost + skill validate ×2; 见 `.squad/decisions/inbox/copilot-2026-05-01-phasea-user-signoff.md` |
| Phase E 留痕 | ✅ done | `.github/copilot-instructions.md` "Squad 0.9.3-modular Decision Map" 整段已固化 |
| HR1 写入门禁 (旁证) | ✅ deployed | `.squad/tools/pool_append.py` 含 lock / SHA-256 dedup50 / G1 / G3 / atomic replace; 之前 smoke 标缺失为假阴性,见 `copilot-smoke-test-2026-05-01.md` Check 6 修订 |

Open items: 0 (Plan B 闭环)。

## Decisions

1. **Cost plan**: 视为"主体已完成, 待手动闭环". 无需重新规划; 4 个 open items 由后续 ad-hoc slice 收尾即可. §3.3 标记为 `BLOCKED—cache rebuild` 而非 gap (受外部前置依赖阻塞).
2. **Squad plan**: 视为 **gate-passed / signed off**。T5 拆分已完成，Phase A 五段验收已由用户签收；后续只保留 hooks 真实触发的低优先观察项，不再作为 Plan B open gap。
3. **Master plan**: `.kilo/plans/2026-04-27-full-project-build-master-plan.md` is the active execution source. Its 2026-05-01 Wave 9/10 E2E gate evidence supersedes the older TASK-192 timeout assessment in this snapshot.
4. **WeChat/OpenClaw spec**: usable manual integration, tracked as an operational validation lane, not as a master build blocker.
5. **Playful Meadow**: historical strategic ancestor; do not dispatch new work directly from it unless a new slice explicitly reopens it.
6. **本 review 自身**: documentation-only, no runtime code, no secret/provider/config changes.

## Evidence

- Cost plan: `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` (内联 ✅ 标记) + `llm_cost_logger.py:1-77` + `python_adapter_server.py:424-449` + `tests/test_sampling_router.py:7-15`.
- Squad plan: `.kilo/plans/2026-04-27-squad-official-capability-reuse.md` + `.github/copilot-instructions.md` "Squad 0.9.3-modular Decision Map" + `.github/agents/claude-squad.agent.md` + `.github/hooks/squad-governance.json` + `tools/squad/squad.ps1.deprecated` + `tools/squad/README-DEPRECATED.md` + `tools/squad/{smoke-test,profile-version-check,check-ghost}.ps1` + `.squad/decisions/inbox/copilot-2026-05-01-phasea-user-signoff.md`.
- 仓库实际目录列举（修订后）: `.github/prompts/` = `prompts.md.deprecated` + `squad-doctor.prompt.md` + `squad-plan.prompt.md` + `squad-round.prompt.md`; `.github/skills/` 已包含 `squad-startup-packet/SKILL.md` 与 `squad-cli-handoff/SKILL.md`.

## Rollback

本轮同步前已建立回档点：`C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.rollback_snapshots\codex-all-plan-evaluation-20260501_011352`。

### Plan C — `.kilo/plans/2026-04-27-full-project-build-master-plan.md` (Master Build Plan, ~750+ lines)

补评 (此前漏列, 这才是当前真正的 master plan, 前两份是它的子线):

估算完成度: **near-close / backend hardening remaining**。此前记录的前端 E2E runner 阻塞已被 master plan 2026-05-01 独立复跑证据取代。

| Wave | 状态 | 关键证据 |
| --- | --- | --- |
| Wave 0 控制面/预检 | ✅ done | TASK-000/090/091/092 全 ✅; smoke-test 5/5; FastAPI route count=108; `npm run build` 6.54s |
| Wave 1 评测资产/输出隔离 | ✅ done | TASK-010/011/100/101 全 ✅; `artifacts/eval_audit/run_manifest_template.json` + manifest discipline 已落 |
| Wave 2 会话持久化 | ✅ done | TASK-030/110/111/112 全 ✅; `runtime_router.py` resume/fork/rewind/checkpoints + SQLite reload 测试通过 |
| Wave 3 前端检索/扫描闭环 | ✅ done | TASK-040/120/121/122 全 ✅; Settings `retrievalTopK` + KnowledgeBase 失败占位 |
| Wave 4 reranker 矩阵/默认门控 | ✅ done (provisional verdict) | TASK-011~014/130 全 ✅; DashScope `qwen3-rerank` / `qwen3-vl-rerank` / `gte-rerank-v2` 三条 c16 canary 全部显著劣于 no-rerank control (Recall@5=0.6667 vs ≤0.10); 短期默认 `--no-rerank`, reranker 保留为一等能力; runtime cliff 已修复 (`c48=48/48`) |
| Wave 5 主运行时对齐 | ✅ done | TASK-050/140/141 全 ✅; shared local retriever 接回 `reranker_client.rerank_async()`; `last_answer.json` 持久化恢复; TOLF embedding 切回 `chunk_vector_store.batch_embed_texts` |
| Wave 6 TOLF text-only pilot | ✅ done | TASK-060/150/151/152 全 ✅; fixed/MAQ × evidence × richer mask ablation; representative rerank 接口 default-off 预留 |
| Wave 7 academic connector + UI | ✅ done | TASK-160~164 全 ✅; 只读 Zotero/EndNote/Obsidian connector 设计; `Evidence` / `Citation Chain` / `Review` 三视图最小实现; shared-page 自动 UI 协议固化 |
| Wave 8 backend export contract + schema 复盘 | ✅ done | TASK-070/170~175 全 ✅; `/resources/.../export` 新增 `evidence_rows` / `citation_chain` / `review_findings`; `ProjectExportPayload` 固化为 `#/components/schemas/...`; 独立 review `PASS WITH NOTES` |
| Wave 9 前端产品化 | ✅ done | TASK-176~182 + TASK-192 已由 2026-05-01 前端 gate 收口；`npm run test` -> `34 passed`; `npm run build` -> success; `npm run test:e2e -- --reporter=line` -> `16 passed (50.7s)` |
| Wave 10 用户 Skill 扩展层 | ✅ frontend/runtime MVP done; backend hardening remains | TASK-183~191 已完成后端合同、运行时、前端 Skill Manager、Actions 映射、Skill Manager E2E；剩余是非前端 hardening：approval decision 持久化与卸载/回滚 API |
| TASK-192 Playwright runner 稳定化 | ✅ done | Windows/Vite/Playwright 稳定化已完成；E2E mock 限定 fetch/xhr，独立 Vite E2E config，root warm-up + sidebar navigation；16/16 passed |

Master plan 自定 Close 条件中的前端 gate 已满足。当前不再卡 TASK-192；项目主线转入 Skill 后端 hardening 与后续运维/审计专项。

### Master plan 关键 open items (≤5)

1. **TASK-193** Skill approval decision 持久化：设计已进入 master plan，下一步是 contract tests + implementation。
2. **TASK-194** Skill 卸载 / 回滚 API：依赖 TASK-193，必须只允许 user skill，builtin skill 403。
3. **Skill approval/uninstall frontend UI**：后端 API 落地后另开前端切片。
4. (低优先) embedding provenance observability (Wave 4 follow-up, 已转入 TASK-130 后续)。
5. (低优先) main runtime 与 eval 间 query-embedding / strict_cache_guard 差异 (TASK-050 残留, 不阻塞收口)。

## Self-Decisions Log

1. 选择本文件名 `copilot-plan-status-2026-05-01.md` (符合 `.squad/decisions/inbox/` 既有 `<owner>-<topic>.md` 命名风格, 加日期是因为这是周期性 status, 不是单次修复).
2. 把 cost-plan §3.3 (contextual eval) 归类为 `BLOCKED` 而非 `open gap`, 因前置 cache 重建是已知外部依赖, 不是计划内未完成项.
3. (补) 2026-05-01 后续复核确认 master plan 已记录 `npm run test:e2e -- --reporter=line` -> `16 passed`，因此撤销旧的 "TASK-192 pending" 判断。
4. 本轮新增综合评估记录：`.squad/decisions/inbox/codex-2026-05-01-all-plan-evaluation.md`。
