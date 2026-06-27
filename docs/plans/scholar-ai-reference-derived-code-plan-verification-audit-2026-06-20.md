# Scholar AI Reference-Derived Code Plan — 验证证据对抗性审查

Date: 2026-06-20
Audited object: `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`（Phase 0–9 + Final Requirement-To-Evidence Audit）与 `docs/plans/longrun-goal-state-2026-06-19.json`（`completion_claim` 标 complete）
Mode: 只读对抗性审查，不修改任何产品代码
Reviewer: Claude（Staff 级工程代理，外部独立复核）
Rounds: 五轮均 2026-06-20，递进 —— 第一轮=测试真假复核（实跑预言验证）；第二轮=plan vs 工作树 `git diff` 逐文件对账（实施忠实度）；第三轮=逐行代码审查 vs codex L1-L5 lessons（reference 忠实度）；第四轮=修复验证；第五轮=residual-closure 独立复核。

经五轮对抗审查：代码与验证声明**全部真实、零造假**，实施忠实度高，对照业界 lessons 的代码级缺口已全部修复。P0（执行记录不可审查）与 P1（completion 措辞 / provider-capabilities 残留 / full suite 未跑）**均已解决**——核心执行记录进版本控制、full backend suite 4175 passed、frontend 804 passed、build passed。残留仅剩 desktop pywebview 与 real provider smoke（环境/凭证依赖，属合理门禁）。

> 下方"一句话结论（历史，第一轮时）"保留原始判断供追溯；P0/P1 的解决证据见各轮章节与 codex follow-up 记录。

## 一句话结论（历史，第一轮时）

代码与验证声明全部真实、零造假；但"完成"的可信度地基有硬伤——约 80% 验证证据是 `.gitignore` 的本地文件，不可审查、不可 CI、不可复现，且全程零真实 provider / 端到端验证。

## 审查方法

不是读声明，而是实跑复核：

1. 核对 `git status` 与 plan 声称的改动文件是否一致。
2. Grep 验证声称的核心类/函数/endpoint 是否真实存在于代码（非空定义、真实被调用）。
3. 实跑每个 phase 声称"已通过"的测试文件，用 plan 声称的通过数做预言验证。
4. 跑 `npm run build` + 前端组件测试，验证前端声明。
5. 跑后 `git status` 复查 tracked 文件是否被污染。
6. 检查 runtime state 残留与 OpenAPI 类型同步。

## 复跑结果（预言 vs 实跑）

| 对象 | plan 声称 | 实跑 | 判定 |
|---|---|---|---|
| `tests/test_mcp_phase2_tool_loop.py` | ≥55（Phase 3a 声明 55） | 55 passed | ✅ 命中 |
| `agent_mcp_server/tests/test_source_tools.py`(tracked) | 11（Phase 4a） | 11 passed | ✅ 命中 |
| `tests/test_wiki_export.py` + `test_wiki_permissions.py`(tracked) | ~11 子集 | 29 passed | ✅ |
| `tests/test_api_chat_local_literature_tool_use.py` + `test_api_probe_semantics.py` | ~18 | 19 passed | ✅ |
| `tests/test_runtime_router_contract.py` + `test_writing_runtime_persistence.py` + `test_writing_submission_export.py` | Phase 6/7/8 | 32 passed | ✅ |
| `tests/test_evidence_pack_build_contract.py` + `test_live_api_chat_full_writing_chain_smoke_harness.py` | Phase 5a/5c/9a | 12 passed | ✅ |
| `frontend/src/components/chat/MessageRenderer.test.tsx` + `AgentWorkspace.test.tsx` | 5+1 | 6 passed | ✅ 命中 |
| `npm run build` | passed | ✓ 10.88s，无类型错误 | ✅ |

跑测试后 `git status` **零 tracked 变化**（用 `-p no:cacheprovider`，`frontend/dist/` 为 ignored 构建产物）。

## 代码层真实性确认

声称的核心类/函数/endpoint 全部真实存在且被实际使用（非空定义、非 TODO）：

- `provider_capabilities.py`：`ProviderCapabilityRecord`、`ProviderCapabilityStore`、`ensure_tool_call_capability()`
- `tool_use_runner.py`：`ToolLoopStopReason`/`ToolLoopTerminalState`/`ToolLoopEventType`/`ToolLoopEvent`/`ToolLoopDiagnostics`/`RunCaps`；事件 `TOOL_LOOP_STARTED`/`PROVIDER_NO_TOOL_CALLS`/`TOOL_LOOP_COMPLETED`/`TOOL_LOOP_MAX_ROUNDS`/`TOOL_LOOP_TIMEOUT` 在 runner 内**真实 emit**（约 30 处 `ToolLoopEvent(...)` 调用）
- `writing_runtime.py`：`update_writing_workflow_state()`、`get_writing_workflow_state()`、`add_job_artifact()`
- `writing_router.py`：`_build_project_export_bundle_manifest()`、`_record_project_export_workflow_state()`
- `runtime_router.py`：`_writing_workflow_state_summary()`、`POST/GET /runtime/job/{job_id}/writing-workflow-state`
- `endpoints_materials_drafts.py`：`_resolve_project_source_file_for_unlink()`
- `wiki/export.py`：`_build_wiki_export_bundle_manifest()`
- 前端 `MessageRenderer.tsx`："语义质量已验证"三重门控（`status==='canonical' && semantic_quality_claim_allowed===true && canonicalCount>0`）逻辑正确
- `frontend/src/generated/openapi.ts` 与 `modular-pipeline-openapi.json` 同步包含 `RetrievalQrelsStatusPayload`、`WritingWorkflowStatePayload`、`WritingWorkflowStateRequest`、`writing_workflow_state_summary`、`/api/chat/tool-capability/test`

## 第二轮：Plan vs 工作树 diff 对账（实施忠实度）

对账范围：plan 声称的 24 个改动文件（23 `M` + 1 `??`）逐个对照工作树 `git diff`，验"声明 vs 实际改动是否一致"。

| 类别 | 文件 | 判定 |
|---|---|---|
| 纯 additive（0 删除） | model_config_router / writing_runtime / models/{runtime,evidence,__init__} / MessageRenderer.tsx / Dialog.tsx / test_source_tools / test_wiki_export | ✅ 与"additive/preserving"声明一致 |
| 包裹式重构，原逻辑保留 | chat_router（`runner.run` 在 else 分支仍调用）、writing_router（`export_project_resource` 仍调用，recording 包在 `try/except` non-fatal，`return response` 保留原 payload）、endpoints_materials_drafts（`candidate.unlink()` 仍在，前置 containment）、wiki/export（`zf.writestr(page_archive_path, content)` 仍在，权限过滤未动） | ✅ 与各 Phase 声明一致 |
| 安全语义正确 | chat_router fail-closed（抛 `ProviderToolCapabilityError`→空 answer + 诊断，**不调 provider**）；`_resolve_project_source_file_for_unlink` `resolve()` + `root not in candidate.parents` 严格 containment；evidence_router 固定文件名白名单只读计数（无递归/写/删除）；tool_use_runner budget 累计 + `context_budget_remaining_chars` 非负校验 + 诊断 message 标注"without secrets or raw provider payloads" | ✅ |
| 删除行全部对应 plan 描述的重构 | source.py `rglob("*")`→denylist-pruning walker(11 删)、AgentWorkspace `resource_ingest` 过滤→含 `artifact_export`(4 删)、test_wiki_permissions 精确 `namelist()` 相等→包含断言(1 删)、evidence_router import 重排 `runtime_state_path` 仍保留(1 删) | ✅ **无 plan 未声明的删除** |

结论：逐文件语义对账**零偏差**——无"plan 未提及的删除"，所有"包裹式重构"保留原逻辑，所有"additive/只读/non-fatal"声明与实际 diff 吻合。第一轮证"声明真实"，第二轮证"实施忠实"，代码层无任何造假或偏差。

## 第三轮：逐行代码审查 vs codex 学习记录（reference 忠实度）

对照 codex `docs/plans/github-reference-learning-notes-2026-06-19.md` 的 L1-L5 lessons，逐行审 `mcp_runtime/tool_use_runner.py`（run 主体 890-1151）与 `tool_result_formatter.py`（全文）。

**符合 reference lessons**：

- L3 显式 stop reasons：8 种独立 `typed_stop_reason` 全覆盖（TIMEOUT / NO_TOOL_CALLS / MAX_ROUNDS / COMPLETED / ADAPTER_CONVERSION_ERROR / TOOL_CALL_FAILED_NO_MODEL_PAYLOAD / CONTEXT_BUDGET_EXCEEDED / PROVIDER_TOOL_PROBE_FAILED）；provider `chat_call` 异常与非 dict payload 都转 typed failed diagnostics 而非逃逸为裸异常（run:939-1005）。
- L1 tool-level error 可见：`is_error` record 走 `TOOL_RESULT_RENDERED`/error event 回传 provider，让 LLM 自纠（run:1072-1092），符合"tool 失败应作为 result 让 LLM 看到"。
- L3 budget：char-based 确定性估算（`(len+3)//4`），over-budget 返回非空 `context_budget_exceeded` summary（formatter:385），不发空结果。
- L4 untrusted 注入防护：`format_generic_xml` 转义 `&<>` 并标 `source="untrusted_mcp_output"`（formatter:470-487）。
- L5 envelope 在 adapter 之下：`ToolResultRecord.raw_content` 保留原始 MCP content blocks（formatter:59），provider 消息由 `format_for_*` 渲染。

**对照 lessons 的偏差（新代码级发现）**：

- **[P2] structured_content 非一等公民**：`ToolResultRecord` 仅有 `raw_content`（in-memory，run 生命周期，**不持久化**）+ `llm_payload`（flatten text）+ `source_provenance`（身份字段）。codex L1/L5 明确"preserve structured content and metadata before provider-specific rendering"，当前 structured 数据只在 `_compact_refs_payload`/`_compact_audit_payload` 里被部分重新解析提取白名单字段，无独立 `structured_content` 字段流转到 audit/workflow state。`_flatten_content`（formatter:62-76）把所有 block 压成 text，非 text block 仅留 `<type>` marker + 计数。plan Priority#1"Make ToolResultRecord the stable internal envelope"**未完全达成**（属 future phase，非当前 slice bug，但应记录为 envelope 保真度的已知缺口）。
- **[P3] `llm_payload or record.preview` 回退混淆 L1 边界**：`format_for_claude/openai/xml`（formatter:447/457/478）在 `llm_payload` 为空时回退到 `preview`，而 L1 明确 `preview` 必须 audit-only。当前 `preview` 与 `llm_payload` 同源（均 `redact_text_for_audit` over 同一 `flat`）且 preview 更短（1200 vs 16000），不致实际敏感泄漏；但字段语义混淆是代码异味，未来若 preview 增加 audit-only 调试字段会成泄漏路径。建议空值时用显式占位符而非回退 preview。
- **[P3] budget 超限后循环不立即 break**：run:1067-1070 仅置 `context_budget_exceeded=True` 与 stop_reason，不 break；下一轮对所有新 record（remaining=0）重发 summary，直到 provider 返回 final message 或撞 `max_rounds`。有 `max_rounds` 兜底，非正确性问题；但"发一次 summary 后收尾"vs"每轮重发"的行为选择未在 plan/residual risk 记录。

### 第四轮：修复验证（2026-06-20，codex evidence-hardening 续）

上述 3 个代码级偏差 + 第二轮 P2 `offered_tool_count` 私有 `_snapshot` **全部正确修复**，测试无回归：

- ✅ **structured_content 一等公民化（原 P2）**：`ToolResultRecord` 新增 `structured_content`/`structured_metadata` 字段（formatter:71）+ `_extract_structured_content()` 兼容 `structured_content`/`structuredContent` 双命名（formatter:149）+ `_structured_json_safe()` 递归边界化 + `_extract_structured_metadata()` 带 `_STRUCTURED_METADATA_DENY_KEY_PARTS` 黑名单；流转到 `chat_mcp_integration` 诊断经 `_bounded_structured_projection`（4000 char 上限 + truncated 标记）；`audit.py` `_record_to_dict` 显式 `pop("structured_content")`/`pop("structured_metadata")` 不持久化。**字段定义/流转/剥离三处一致**，完全符合 codex L1/L5"preserve structured content before provider rendering"。`raw_content` 仍 in-memory（L5 envelope-in-adapter-down 保留）。
- ✅ **`or preview` 边界消除（原 P3）**：`format_for_claude/openai/xml` 改用 `_provider_payload_text(record)`（formatter:381-393），`llm_payload` 空时返回显式 `_json_text(...)` 结构化占位符而非 audit-only preview；docstring 明确"without using audit preview ... preview can omit, reorder, or summarize content in ways that are not a provider tool-result contract"。
- ✅ **budget one-time break（原 P3）**：runner:1049-1067 新增 `if context_budget_exceeded:` 块——provider 在 summary 后仍请求 tool 则立即 break + `CONTEXT_BUDGET_EXCEEDED` event（message："provider requested more tools after the one-time context budget summary was sent"），且在 `_apply_context_budget_to_records` 之前 break（budget 耗尽不再执行新 tool calls）。不再每轮重发。
- ✅ **offered_tool_count 封装修复（第二轮 P2）**：`chat_router:1177` 改用公开 `getattr(runner, "offered_tool_count", 0)`，经 `local_literature_tool_bridge:690` property → `tool_use_runner:704` property → runner 内 `offered_tool_count` 字段（runner:196/629），不再 getattr 私有 `_snapshot`。
- **测试**：`test_mcp_phase2_tool_loop` + `test_api_chat_local_literature_tool_use` = **69 passed**，无回归（`-p no:cacheprovider`，跑后 `git status` 零 tracked 变化）。

第四轮结论：plan 对抗审查发现的所有代码级问题（第一轮真实性、第二轮忠实度、第三轮 reference 偏差）均已闭环。后续 Codex residual-closure slice 继续收敛结构性/验证性缺口：核心 `docs/plans` 记录、`tools/longrun` prompt、关键后端/前端测试与 `workspace_tests` fixtures 已路径级 allowlist；`provider-capabilities.json` 假 provider 残留已清为空 records；full backend suite 与 full frontend suite 已实跑通过。**当前剩余缺口**收敛为：desktop pywebview smoke 未跑、real provider/API smoke 未跑、仍未 stage/commit，且 `workspace_artifacts/` 作为 runtime state 仍按策略 ignored。

## 发现的真实问题（按严重度）

### P0 — 验证证据不可审查（结构性）

`.gitignore` 规则（第二轮逐文件 diff 对账追加确认）：

- `:76 /docs/*` → **整个 `docs/` 不在版本控制**：含 plan 本身、goal-state JSON、所有 audit 文档（`git ls-files docs/plans/...` 返回空确认 untracked）
- `:190 /tools/` → 整个 `tools/` 不在版本控制（含 `longrun-prompt.md`）
- `:208 /tests/*` → 所有 `tests/test_*.py` 被忽略
- `:144 /frontend/**/*.test.tsx` → 所有前端组件测试被忽略
- `:199 /workspace_artifacts/` → harness/smoke 脚本被忽略

23 个改动文件里**只有 3 个测试 tracked**：`test_source_tools.py`、`test_wiki_export.py`、`test_wiki_permissions.py`。含义：Phase 1/2/3/5/6/7/9 的全部"已验证"声明，对 CI、协作者、未来会话**完全不可见**。更严重的是：**执行方案、goal-state、审查文档本身也都不在 git**——"执行-验证-记录"三元组全在本地私有文件，repo 里只能看到产品代码 diff。一旦 worktree 重置、`.venv-1` 变动、或本地文件被误删，整个 plan + 证据链消失。这是可信度地基问题，不是单点 bug。`git status --ignored` 显示 568 个 ignored 条目。

> **residual-closure slice 后状态（2026-06-20）**：`.gitignore` 已改为路径级 allowlist，不开放整目录。当前已可见：三份核心执行记录（plan / audit / goal-state）、`docs/plans/runbooks/longrun-local-supervisor.md`、`tools/longrun/longrun-prompt.md`、核心后端 characterization tests、source-safe live smoke harness、关键 `workspace_tests` manifests/fixtures，以及 4 个前端 gate tests（`MessageRenderer.test.tsx`、`DimensionGraphViewer.test.tsx`、`AgentWorkspace.test.tsx`、`Jobs.test.tsx`）。`workspace_artifacts/` 仍整体 ignored，符合 `SOURCE_RELEASE_POLICY.md` 的 runtime-state denylist；provider runtime JSON 的本地清理只作为本机状态记录，不作为 Git 证据。

### P1 — "完成"定义自我拔高

`longrun-goal-state-2026-06-19.json` 的 `completion_claim.full_product_code_goal = "complete_with_recorded_residual_verification_risks"`，而残留风险包含：

- full backend suite 未跑
- full frontend suite 未跑
- desktop pywebview smoke 未跑
- **real provider smoke 未跑**

即零端到端、零真实 provider，全部是 fake-provider / fake-probe 的隔离单元测试。同时 plan 的 Non-Goals 明写"Do not claim product-code implementation is complete"——**措辞自相冲突**。建议改为 `implementation_slices_complete_verification_gated`。

> **residual-closure slice 后状态（2026-06-20）**：`longrun-goal-state-2026-06-19.json` 的 `completion_claim.full_product_code_goal` **已降级**为 `implementation_slices_complete_verification_gated`，`reason` 明确不声明 release/public-source/desktop/real-provider complete。full backend suite 已补跑通过（`4175 passed, 52 skipped, 1 xfailed in 338.16s`）；full frontend suite 已补跑通过（`130 passed files / 804 passed tests`）。本 P1 的措辞冲突与 full-suite 证据缺口已解决；真实剩余风险是 desktop pywebview smoke 与 real provider/API smoke 未跑。

### P1 — 运行时状态污染未清理

`workspace_artifacts/runtime_state/provider-capabilities.json` 残留一条：

```
base_url_host: chat.example, model: tool-loop-model, status: tool_call_ok,
forced_tool_choice_ok: true, last_probe_at: 2026-06-19T15:13:57Z
```

Phase 2a 已坦白"created during an early unisolated test run ... was not deleted in this slice"。这条 `tool_call_ok` 记录可能在真实运行时让 dispatch 误判 `chat.example` 具备 tool 能力。建议跑 `scripts/clean_test_data.ps1` 或手动删该文件。

> **residual-closure slice 后状态（2026-06-20）**：未运行破坏性的 `scripts/clean_test_data.ps1`；只对目标 runtime JSON 做最小清理，当前 `workspace_artifacts/runtime_state/provider-capabilities.json` 内容为 `{"records": {}}`。`workspace_artifacts/` 仍 ignored，本清理是本机 runtime-state 修复，不是可提交 source 证据。

### P2 — 无 git 锚点

6 个 phase、~2900 行改动全部在未提交的 dirty worktree，叠加在已是 75 文件巨型 commit 的 `2e1aa8e8`（含 25655 行 openapi 变化）之上。plan 反复声明"No commit/stage/push was performed"（诚实），但含义：rollback 全靠外部 codex checkpoint，git 内无切片锚点，一旦 worktree 出问题无法回溯到具体 slice。

### P2 — plan 内部顺序不一致（轻微）

"Suggested Slice Order"把 writing(7)排在 retrieval(8)前，实际执行是 retrieval(5)→writing(6)。执行顺序更合理（先建检索证据再造写作状态），但文档未同步。

### P2 — chat_router 访问 runner 私有 `_snapshot`（实现脆弱点，plan 未记录）

`chat_router.py` 的 `offered_tool_count` 用 `getattr(getattr(runner, "_provider_runner", runner), "_snapshot", [])` 读取 runner 内部私有属性。runner 重构后该路径会静默归零——不影响 fail-closed 正确性，但会让诊断里的 `offered_tool_count` 失真。plan 未记录此实现细节，属封装边界泄漏。

> **第四轮已修复（2026-06-20）**：`chat_router:1177` 改用公开 `getattr(runner, "offered_tool_count", 0)`，经 `local_literature_tool_bridge:690` → `tool_use_runner:704` 的 property 链暴露，不再 getattr 私有 `_snapshot`。详见第四轮验证章节。

## 诚实度确认（非问题）

每个 slice 都有 `Skipped / not claimed` + `Residual risk` + `Authorized local work remaining` 三段；从未把 fake-provider 测试冒充 real provider 验证；Phase 2a 主动坦白 `provider-capabilities.json` 污染；每个 slice 有 rollback checkpoint。**声明与实际在代码层零偏差**，问题只在"完成边界"措辞与证据可审查性。

## 建议（按 ROI）

1. **已完成**：核心 characterization 测试、关键前端 gate tests、核心执行记录和 `workspace_tests` fixtures 已路径级 allowlist；full backend suite 与 full frontend suite 已补跑。
2. **已完成（本机 runtime）**：`workspace_artifacts/runtime_state/provider-capabilities.json` 假 provider 残留已清为空 records，未运行 `clean_test_data.ps1`。
3. **仍待显式优先级/环境准备**：desktop pywebview smoke。
4. **仍待凭据/网络/成本边界确认**：real provider/API smoke。

## 审查边界

- 本次审查**未修改任何产品代码**。
- 跑测试未先执行 `clean_test_data.ps1`（该脚本会删 `evolution_candidates.sqlite3`/`chat_history.db` 等用户运行时数据，属破坏性操作，未获授权未执行），但用 `-p no:cacheprovider` 且跑后 `git status` 零 tracked 变化。
- 原审查未跑 real provider smoke、desktop pywebview smoke、full suite；后续 residual-closure slice 已补 full backend suite 与 full frontend suite，desktop / real-provider 仍列为 P1 残留。

## Codex Evidence-Hardening Follow-Up, 2026-06-20

Purpose: respond to the P0/P1 credibility findings without adding product
features.

Rollback:

- `20260620-125558-evidence-hardening-audit-response`

Mature / official references rechecked:

- Git `.gitignore` documentation for explicit negation/allowlist behavior.
- pytest usage/discovery documentation, including focused file execution and
  `-p no:cacheprovider` for cache-free reruns.
- Vitest configuration documentation for ordinary `*.test.tsx` discovery.
- Testing Library async query documentation for duplicate UI projections.

P0 evidence visibility action:

- `.gitignore` now path-allowlists reviewed core deterministic tests instead
  of unignoring all `tests/` or `workspace_artifacts/`.
- Newly auditable tests:
  `tests/test_mcp_phase2_tool_loop.py`,
  `tests/test_api_chat_local_literature_tool_use.py`,
  `tests/test_api_probe_semantics.py`,
  `tests/test_evidence_pack_build_contract.py`,
  `tests/test_runtime_router_contract.py`,
  `tests/test_writing_runtime_persistence.py`,
  `tests/test_writing_submission_export.py`,
  `frontend/src/components/chat/MessageRenderer.test.tsx`,
  `frontend/src/pages/AgentWorkspace.test.tsx`.
- Kept local-only:
  `tests/test_live_api_chat_full_writing_chain_smoke_harness.py` and
  `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`,
  because the harness imports a generated runtime artifact that embeds this
  machine's workspace path and resolves provider configuration.

P1 completion-boundary action:

- `docs/plans/longrun-goal-state-2026-06-19.json`
  `completion_claim.full_product_code_goal` is downgraded to
  `implementation_slices_complete_verification_gated`.
- The recorded state now says: Phase 0-9 implementation slices completed with
  local deterministic/fake-provider verification; not full-suite, desktop,
  real-provider, release, or public-source complete.

P1 provider-capability pollution audit:

- Read-only audit confirmed the default `ProviderCapabilityStore()` reads
  `workspace_artifacts/runtime_state/provider-capabilities.json` through
  `runtime_state_path("provider-capabilities.json")`.
- The stale `chat.example` / `tool-loop-model` / `tool_call_ok` record can
  authorize dispatch only for a runtime request/config with the same provider,
  endpoint host, and model. Normal real-provider hosts are not expected to
  match `chat.example`, but matching test or mistaken local runtime config can
  still be polluted.
- No runtime state was deleted, and `scripts/clean_test_data.ps1` was not run.

Residual after follow-up:

- At this point in the audit history, full backend suite, full frontend suite,
  desktop pywebview smoke, and real provider/API smoke were still unrun. Later
  residual-closure evidence below supersedes the full-suite rows.
- The live provider smoke harness remains local-only until rewritten without
  machine-local paths/provider resolution.
- The P2 `chat_router` private `_snapshot` diagnostic fragility remains a
  later product-code cleanup candidate.

Follow-up verification:

- `git check-ignore -v -- <reviewed tests and harness paths>` confirmed the
  nine reviewed tests are allowlisted while the live-smoke harness/runtime
  artifact remain ignored.
- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py
  tests\test_api_chat_local_literature_tool_use.py
  tests\test_api_probe_semantics.py
  tests\test_evidence_pack_build_contract.py
  tests\test_runtime_router_contract.py
  tests\test_writing_runtime_persistence.py
  tests\test_writing_submission_export.py -q` passed: 113 tests.
- `npm run test -- --run src/components/chat/MessageRenderer.test.tsx
  src/pages/AgentWorkspace.test.tsx` passed: 2 files / 6 tests.
- `npm run build` passed.
- `git diff --check -- .gitignore <visible product files>` passed, and
  ignored plan docs were covered separately with `git diff --no-index --check`.
- Untracked reviewed-test whitespace check passed; Git reported CRLF-to-LF
  normalization warnings for `tests/test_runtime_router_contract.py` and
  `tests/test_writing_runtime_persistence.py`, with no whitespace errors.
- Ignored-doc whitespace check passed; Git reported a CRLF-to-LF normalization
  warning for `docs/plans/longrun-goal-state-2026-06-19.json`, with no
  whitespace errors.

## Codex Delegated P2/P3 Audit-Follow-Up Merge, 2026-06-20

Purpose: merge the two completed worktree follow-up slices back into the main
Scholar AI worktree without taking the full worktree diffs wholesale.

Rollback:

- Main-worktree merge checkpoint:
  `20260620-134242-merge-delegated-p2-p3-tool-result-slices`
- Delegated source worktrees:
  `C:\Users\xiao\.codex\worktrees\2cc4\Modular-Pipeline-Script`
  for P2 `structured_content`, and
  `C:\Users\xiao\.codex\worktrees\8040\Modular-Pipeline-Script`
  for P3 provider payload / budget behavior.

Mature / official references rechecked:

- MCP `CallToolResult` schema: tool result envelopes separate `content`,
  `structuredContent`, `isError`, and metadata.
- OpenAI function/tool calling docs: tool responses are provider-visible
  protocol messages paired to calls, not audit/UI summaries.
- Anthropic tool-use docs: `tool_result` blocks carry tool execution output
  back to the model.
- LangChain MCP adapters: preserve MCP `structuredContent` as an application
  artifact while rendering model-visible content separately.

Merged fixes:

- P2 `structured_content` is now a first-class `ToolResultRecord` field:
  `structured_content` and `structured_metadata` are extracted from
  `structuredContent` / `structured_content` and `_meta` / `meta`, made
  JSON-safe, bounded, and redacted.
- Persistent MCP audit still remains preview-only: `raw_content`,
  `llm_payload`, `structured_content`, and `structured_metadata` are omitted
  from `_record_to_dict()`.
- `mcp_run.tool_calls[]` diagnostics now expose bounded structured projections
  without exposing `raw_content` or `llm_payload`.
- P3 provider renderers no longer fall back from empty `llm_payload` to
  audit-only `preview`; they emit an explicit `provider_payload_empty`
  provider-facing placeholder.
- P3 context-budget behavior now sends one summary and then stops with
  `context_budget_exceeded` if the provider asks for more tools, instead of
  repeating summaries until `max_rounds`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py -q` passed: 59 tests.
- `$env:LITASSIST_API_CAPABILITY_AUTH='0'; .\.venv-1\Scripts\python.exe -m
  pytest -p no:cacheprovider tests\test_api_chat_local_literature_tool_use.py
  -q` passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q
  literature_assistant\core\mcp_runtime
  literature_assistant\core\routers\chat_mcp_integration.py
  tests\test_mcp_phase2_tool_loop.py` passed.
- `git diff --check --` over the delegated merge touched files passed.
- `docs/plans/longrun-goal-state-2026-06-19.json` validated with
  `json.loads` before record update.

Residual after merge:

- This is deterministic/fake-provider focused verification, not full backend
  suite, full frontend suite, desktop pywebview smoke, or real-provider/API
  smoke at this merge point. Later residual-closure evidence below supersedes
  the full-suite and provider-capability cleanup rows.

## Codex Offered-Tool-Count Accessor Cleanup, 2026-06-20

Purpose: close the remaining Claude P2 diagnostic fragility where
`chat_router.py` read runner private `_snapshot` state to compute
`offered_tool_count`.

Rollback:

- `20260620-135327-chat-router-offered-tool-count-accessor`

Mature / official reference rechecked:

- Python PEP 8 public/internal interface guidance: callers should use public
  interfaces rather than underscore-private implementation attributes.

Changed behavior:

- `McpToolUseRunner` now exposes public `offered_tool_count`.
- `LocalLiteratureToolUseRunner` forwards that public count for built-in
  Scholar AI local tools.
- `chat_router.py` now reads `runner.offered_tool_count`; it no longer reaches
  through `_provider_runner` or `_snapshot`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py -q` passed: 60 tests.
- `$env:LITASSIST_API_CAPABILITY_AUTH='0'; .\.venv-1\Scripts\python.exe -m
  pytest -p no:cacheprovider tests\test_api_chat_local_literature_tool_use.py
  -q` passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q
  literature_assistant\core\mcp_runtime\tool_use_runner.py
  literature_assistant\core\routers\local_literature_tool_bridge.py
  literature_assistant\core\routers\chat_router.py
  tests\test_mcp_phase2_tool_loop.py` passed.

Residual:

- This closes the known private `_snapshot` diagnostic finding only. It does
  not itself run full backend/frontend suites, desktop pywebview smoke, or real
  provider/API smoke. Later residual-closure evidence below supersedes the
  full-suite rows.

## Codex Residual-Closure Verification, 2026-06-20

Purpose: close the remaining structural/full-suite/runtime-state audit gaps
that are safe to resolve locally, without claiming desktop or real-provider
completion.

Rollback:

- `20260620-141652-audit-structural-verification-fixes`
- `20260620-143050-full-suite-failure-triage-fixes`
- `20260620-144220-audit-residual-fullsuite-fix-continuation`
- `20260620-145246-fullsuite-eight-failure-targeted-fix`
- `20260620-151541-record-fullsuite-audit-residual-fixes`
- `20260620-151808-frontend-fullsuite-dimensiongraph-fix`

Mature / official references rechecked:

- Git `.gitignore` documentation for parent-directory re-inclusion and
  path-explicit negation allowlists.
- pytest usage and monkeypatch documentation for focused reruns,
  `-p no:cacheprovider`, env isolation, and temp-path state isolation.
- Vitest command/configuration documentation for focused and full frontend
  suite runs.
- Testing Library ByRole/accessibility guidance for validating visible
  controls by accessible names.
- OWASP SSRF guidance for DNS/IP validation before credential-bearing endpoint
  probes.

Structural evidence visibility:

- `.gitignore` now path-allowlists the three core execution records:
  `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`,
  `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`,
  and `docs/plans/longrun-goal-state-2026-06-19.json`.
- `tools/longrun/longrun-prompt.md`, selected `workspace_tests`
  manifests/fixtures, the source-safe live writing-chain harness, and the
  selected frontend/backend tests are also path-allowlisted.
- `workspace_artifacts/` remains ignored by policy; runtime state is not
  promoted into Git.

Runtime-state cleanup:

- `workspace_artifacts/runtime_state/provider-capabilities.json` was changed
  from the stale `chat.example/tool-loop-model/tool_call_ok` record to
  `{"records": {}}`.
- `scripts/clean_test_data.ps1` was not run because it deletes user runtime
  data such as evolution/chat history.

Additional product/test fixes uncovered by full suites:

- Backend full-suite failures were resolved through test isolation and narrow
  product-contract fixes: abstract extraction fallback, SmartFilterEngine
  wrapper, chat telemetry isolation, rerank/env runtime override isolation,
  credential endpoint DNS validation, discussion task-store temp persistence,
  feature-flag/credential-store test isolation, linter assertion correction,
  PyInstaller hiddenimport, and eval/runtime fixture compatibility.
- Frontend full-suite failures were resolved by restoring the
  `DimensionGraphViewer` edge-interaction contract (evidence-weight toggle,
  route-category filters, node/edge hover visibility projection) and widening
  `Jobs.test.tsx` to assert the linter endpoint path rather than a single base
  URL shape.

Verification:

- Provider capability runtime JSON check: `{"records": {}}`.
- `git check-ignore -v` confirmed selected docs/plans records, longrun prompt,
  tests, source-safe harness, and workspace_tests fixtures are allowlisted while
  `workspace_artifacts/runtime_state/provider-capabilities.json` remains
  ignored.
- Backend collect-only: `4228 tests collected`.
- Full backend suite:
  `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider tests -q`
  passed: `4175 passed, 52 skipped, 1 xfailed in 338.16s`.
- Focused frontend repairs:
  `npm run test -- --run src/components/graph/DimensionGraphViewer.test.tsx`
  passed: 11 tests; `npm run test -- --run src/pages/Jobs.test.tsx` passed:
  4 tests.
- Full frontend suite:
  `npm run test -- --run` passed: 130 files / 804 tests.
- Frontend build: `npm run build` passed after the frontend fixes.

Residual after residual-closure:

- Desktop pywebview smoke via `start_desktop.py` was later run in a delegated
  acceptance thread and reached `blocked_clean_exit`: native `文献助手` startup
  and visibility passed, but close emitted a pythonnet/.NET exception and exit
  code `-532462766`. The parent main worktree then reran the same source
  desktop smoke four times; all four reruns exited `0` with empty stderr and no
  same-title window left behind, so the current desktop gate is
  `passed_after_main_rerun` with one recorded intermittent close-path flake.
- Real provider/API smoke was later run as a low-budget provider capability
  probe and passed for configured provider/model `hhl` / `gpt-5.5` on host
  `free.hanhanapi.top` with masked key `sk-k...VoL6`; full natural-prompt
  Scholar AI writing-chain/tool-content backflow remains unrun.
- No staging, commit, push, tag, release, destructive cleanup, restore,
  credential change, production access, or paid external access was performed.
- The worktree remains broad and dirty; rollback evidence exists through Codex
  checkpoints, not Git commits.

## 第五轮：Residual-Closure 独立复核（Claude, 2026-06-20）

对 codex「Residual-Closure Verification」章节的声明做独立验证（不只信记录）：

- ✅ **测试规模**：`pytest tests --collect-only -q` = **4228 collected**，与 codex 声称一致；full suite `4175 passed/52 skipped/1 xfailed` 的规模基础成立。
- ✅ **live harness source-safe**：`tests/live_api_chat_full_writing_chain_smoke.py` + `test_live_api_chat_full_writing_chain_smoke_harness.py` grep `C:\Users|xiao|/Users/|workspace_artifacts/<sub>` **零匹配**——机器路径依赖已去除，解 ignore 安全（闭合此前"live smoke local-only"遗憾）。
- ✅ **full-suite 修复非 stub**：`abstract_extractor.py`(7 def/class)、`smart_filter_engine.py`(22)、`reranker_client.py`(57) 均有实质实现。
- ✅ **P0 根治**：`.gitignore` 精确 allowlist 放行 `docs/plans/`(5 核心文档) + `tools/longrun/longrun-prompt.md` + `workspace_tests/` fixtures/manifests + 9 测试 + source-safe harness；`workspace_artifacts/` 保持 ignored（runtime state 不进 git）。parent-reinclude + 精确文件模式正确。
- ✅ **P1 残留清空**：`provider-capabilities.json` = `{"records": {}}`。
- ✅ **full-suite 驱动的额外修复诚实记录**：8 类 plan 外改动（abstract fallback / SmartFilter wrapper / chat telemetry isolation / rerank isolation / credential DNS validation / discussion temp persistence / PyInstaller hiddenimport / DimensionGraphViewer contract / Jobs.test）均为 full-suite 暴露的真实 bug，有 6 个 rollback checkpoint + 逐项记录，**非 scope creep**。

第五轮结论：**对抗审查彻底闭环**。代码层（声明真实 / 实施忠实 / reference 忠实 / 修复验证）+ 验证层（full suite 已跑）+ 结构层（执行记录进版本控制）全部解决。后续委派线程已运行 desktop pywebview smoke，首跑不是 fully passed，而是 `blocked_clean_exit`：本机 GUI 启动、native `文献助手` 窗口、非浏览器验证和端口/窗口清理均通过，但关闭路径出现 pythonnet/.NET 异常与非零退出码。父线程随后在主工作树 4 次复跑同一源码入口，均 exit 0、stderr 空、无同名窗口残留，因此 desktop gate 当前为 `passed_after_main_rerun`，保留一次性 close-path flake 风险。后续 real provider/API smoke 已通过 OpenAI-compatible provider tool-capability probe；仍未声明 full natural-prompt writing-chain/tool-content backflow。

## 第六轮：Delegated Desktop / Source-Boundary Follow-Up（Codex worktrees, 2026-06-20）

两条 worktree 委派均按 rollback + 成熟参考 + dirty-worktree 审计纪律执行，未修改产品代码，未 stage/commit/push/tag/release/restore，未运行 real provider/API smoke。

新增记录：

- `docs/plans/scholar-ai-desktop-pywebview-smoke-2026-06-20.md`
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`

Rollback:

- Main merge checkpoint:
  `20260620-191720-merge-delegated-desktop-source-readiness-records`
- Desktop delegated checkpoint:
  `20260620-191022-desktop-pywebview-smoke-20260620`
- Source-boundary delegated checkpoint:
  `20260620-191234-source-boundary-staging-readiness-20260620`

Mature / official references:

- pywebview usage/API docs for `create_window()`, `webview.start()`, and
  `window.destroy()`.
- Microsoft Win32 `EnumWindows`, `GetWindowTextW`, `IsWindowVisible`.
- Git `gitignore` / `git add` docs, GitHub release/source-archive docs,
  OWASP Secrets Management, and GitHub secret scanning docs.

Desktop smoke evidence:

- Source launcher ran from
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script` because the delegated
  worktree lacked `.venv-1`.
- Native top-level window titled `文献助手` appeared and was visible; evidence
  came from Win32 enumeration, not Chrome/Edge/Vite.
- `WM_CLOSE` posted successfully; selected launcher process exited; no
  same-title window remained; selected port `127.0.0.1:11952` had no listener
  after close.
- Delegated first-run blocking evidence: stderr contained a pythonnet/.NET
  exception during/after close and process exit code was `-532462766`.
- Parent main-worktree rerun evidence: one direct rerun plus three consecutive
  loop reruns all opened native `文献助手`, closed with `WM_CLOSE`, exited with
  code `0`, left no same-title window, and produced empty stderr.
- Gate status: `passed_after_main_rerun`; the first-run close exception remains
  an intermittent flake risk.

Source-boundary evidence:

- `.gitignore` allowlist remains path-explicit; `workspace_artifacts/` and
  `.env` remain ignored.
- Public-source candidates are product code, generated API contracts,
  PyInstaller spec, selected deterministic backend/frontend tests,
  source-safe live smoke harness, and selected `workspace_tests` fixtures.
- `docs/plans/*`, longrun runbook/prompt, and internal evidence remain
  local-only by policy unless scrubbed or explicitly approved for publication.
- Forbidden staging remains `workspace_artifacts/`, `.env*`, credential/runtime
  stores, DB/log/profile/cache output, root agent instruction files, `github/`,
  `workspace_references/`, and `frontend/dist/`.

Updated residuals:

- Desktop gate passed on main-worktree reruns; a first-run clean-exit flake is
  retained as residual risk.
- Real provider tool-capability probe is passed; full natural-prompt writing
  chain remains unverified.
- Source-boundary readiness is audited, but no staging decision was executed.

## 第七轮：Real Provider / Pre-Stage Dry-Run Follow-Up（Codex worktrees, 2026-06-20）

两条 worktree 委派均按 rollback + 成熟参考 + dirty-worktree 审计纪律执行。未修改产品代码，未 stage/commit/push/tag/release/restore，未运行 destructive cleanup。

新增记录：

- `docs/plans/scholar-ai-real-provider-api-smoke-2026-06-20.md`
- `docs/plans/scholar-ai-pre-stage-dry-run-2026-06-20.md`

Rollback:

- Main merge checkpoint:
  `20260620-194911-merge-provider-prestage-records-20260620`
- Real-provider delegated checkpoint:
  `20260620-193948-real-provider-api-smoke-20260620`
- Pre-stage delegated checkpoint:
  `20260620-193944-pre-stage-dry-run-20260620`

Mature / official references:

- OpenAI function/tool calling docs and OpenAI authentication docs.
- Project `.github/skills/env-test-discipline/SKILL.md`.
- Git `gitignore` / `git add`, GitHub release/source-archive docs, GitHub
  secret scanning docs, and OWASP Secrets Management Cheat Sheet.
- Vitest CLI docs and Vite production build docs for source-root frontend
  verification after the delegated worktree lacked `frontend/node_modules`.

Real provider/API smoke evidence:

- Actual execution used the source project root because the delegated worktree
  lacked `.venv-1`.
- Existing runtime config resolved provider/model/host:
  `hhl` / `gpt-5.5` / `free.hanhanapi.top`, masked key `sk-k...VoL6`.
- External API calls: 3.
- Existing OpenAI-compatible capability probe verified `/models`, ordinary
  chat, and forced `tool_choice` native tool call.
- Verdict: `passed_provider_tool_capability_probe`; `tool_call_ok=true`,
  HTTP 200, duration `7490ms`.
- Runtime output was written under
  `workspace_artifacts/generated/output/real_provider_api_smoke/` and remains
  ignored.

Pre-stage dry-run evidence:

- 53 explicit candidate paths existed.
- Candidate `git diff --check` passed.
- `git ls-files -ci --exclude-standard` returned empty output.
- JSON/JSONL fixtures parsed successfully.
- High-risk secret scan found no real secret; hits were fake fixtures,
  redaction tests, field names, or safety code paths.
- Forbidden paths remain ignored, including `.env`,
  `workspace_artifacts/runtime_state/provider-capabilities.json`, `AGENTS.md`,
  and `AI_WORKSPACE_GUIDE.md`.
- Backend focused deterministic suite passed:
  `134 passed, 15 warnings`.
- Frontend focused tests could not run in the dry-run worktree because the
  worktree lacked `frontend/node_modules`; parent should rerun frontend
  tests/build in a dependency-complete environment before commit.

Parent source-root frontend closure:

- `npm run test -- --run` from `frontend/` passed:
  `130 passed` test files and `804 passed` tests.
- `npm run build` from `frontend/` passed TypeScript and Vite production build.
- Known non-fatal jsdom `AggregateError` stderr appeared in
  `PdfReaderShell.test.tsx`; Vitest exited 0 and all tests passed.
- `frontend/dist/` remains ignored build output.

Updated residuals:

- The configured real provider supports the minimal OpenAI-compatible native
  tool-call path, but this does not prove full natural-prompt Scholar AI
  writing-chain behavior.
- Explicit path staging is dry-run approved for candidate source/test/fixture
  paths, but staging itself has not been executed.
- `docs/plans/*`, longrun runbooks/prompts, runtime artifacts, `.env*`,
  credential stores, `github/`, `workspace_references/`, and `frontend/dist/`
  remain excluded from public staging by default.

## 第八轮：Seventh-Review Gate Closure（Codex, 2026-06-20）

触发：第七轮独立对抗复核指出 desktop gate 名称过宽、真实
writing-chain 未验证、以及 `63b2` detached worktree staging 一致性未证明。

Rollback:

- `20260620-205506-seventh-review-gate-closure-20260620`

Mature / official references:

- pywebview API documentation for `webview.start(func=..., args=...)`,
  window events, and native window lifecycle.
- Local pywebview 6.2.1 source: ordinary `Event` callbacks are asynchronous
  unless `should_lock=True`; WinForms backend fires `before_show` synchronously
  in the create-window path.
- Python import system documentation: direct-script execution places the script
  directory on `sys.path`, so `tests/wiki` can shadow product `wiki`.
- Git worktree documentation for detached/missing worktree boundaries.
- Project `.github/skills/env-test-discipline/SKILL.md` for same-runtime,
  masked, low-budget provider probes.

Desktop close-path result:

- `start_desktop.py` changed:
  - Windows DWM titlebar color handling moved from async `window.events.shown`
    to synchronous `window.events.before_show`.
  - Reload hotkey installation moved to `webview.start(func=...)` and waits
    for `window.events.loaded` before `evaluate_js`.
- Verification:
  - `.\.venv-1\Scripts\python.exe -m compileall -q start_desktop.py
    tests\live_api_chat_full_writing_chain_smoke.py` passed.
  - 8 native close-path stress runs all found `文献助手`, posted `WM_CLOSE`,
    exited `0`, produced empty stderr, left no same-title window, and left no
    selected-port listener.
- Updated desktop gate:
  `passed_closepath_mitigated_stress_verified`.
- Residual risk:
  this is a mitigation + local stress proof, not a release-wide guarantee; rerun
  before release/public handoff.

Writing-chain live-smoke result:

- Fixed a provider-before-call import blocker:
  `literature_assistant/core/evolution/secret_scan.py` now imports
  `literature_assistant.core.wiki.evaluation` instead of shadowable
  `wiki.evaluation`.
- Added harness coverage:
  - direct-script `tests/` path shadowing no longer breaks
    `evolution.secret_scan`;
  - `--probe-tool-capability` uses the product
    `/api/chat/tool-capability/test` route with local capability auth inside the
    same isolated runtime before attempting writing-chain dispatch.
- Focused verification:
  `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_live_api_chat_full_writing_chain_smoke_harness.py
  tests\test_api_probe_semantics.py
  tests\test_api_chat_local_literature_tool_use.py -q`
  passed: `26 passed`.
- Live run without same-runtime preflight reached `/api/chat` but returned
  `verdict=no_tool_calls`, `stoppedReason=provider_tool_probe_failed` because
  the isolated runtime capability store had no `tool_call_ok` record.
- Live run with `--probe-tool-capability` failed before sending the
  writing-chain request:
  `verdict=tool_capability_probe_failed`, `stage=models`, `error=timeout`
  against `free.hanhanapi.top`.
- A separate product capability probe in the source runtime still passed for
  `hhl` / `gpt-5.5` / `free.hanhanapi.top` with masked key `sk-k...VoL6`, but
  that is still only provider capability evidence, not natural-prompt
  writing-chain/tool-content backflow.
- Updated writing-chain gate:
  `attempted_blocked_by_same_runtime_tool_capability_probe_timeout`.

Staging consistency result:

- `C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script` no longer
  exists, so the original detached-worktree equality check cannot be performed.
- Current source-root fallback check extracted the exact 53 explicit candidate
  paths from the source-boundary record; all 53 exist and were SHA-256 hashed.
- Runtime summary:
  `workspace_artifacts/generated/output/staging_candidate_current_root_consistency_summary.json`
  remains ignored.
- Updated staging gate:
  `blocked_old_63b2_missing_current_root_candidates_hashed`.
- No staging was executed. Future staging must use the current source root,
  explicit pathspecs, and a final scrub/diff pass, not the deleted `63b2`
  worktree.
