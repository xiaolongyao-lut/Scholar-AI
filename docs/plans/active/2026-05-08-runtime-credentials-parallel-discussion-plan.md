---
goal: Runtime credentials, parallel model dispatch, and RAG-aware multi-agent discussion
version: 2026-05-08.v2
date_created: 2026-05-07
last_updated: 2026-05-08
owner: local literature assistant engineering
status: 'In Progress (v2 — Slice A0+A1+A2+A3+B+C+D+E complete; C+1 parity migration remaining)'
predecessor: docs/plans/active/2026-05-07-runtime-credentials-parallel-discussion-plan.md
review_rounds:
  - 2026-05-07: 4 grill rounds (F1-F10, R1-R3) folded into v2
tags:
  - architecture
  - credentials
  - model-dispatch
  - discussion
  - rag
  - release-gate
  - ssrf
---

# Runtime Credentials + Parallel RAG Discussion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans when implementing this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not implement code until the decision gates in section 3 are resolved or their documented defaults are accepted.

![Status: In Progress](https://img.shields.io/badge/status-In%20Progress-yellow)

**Slice progress (2026-05-08):**
- ✅ A0 release safety, A1 credential registry, A2 endpoint policy, A3 credentials router
- ✅ B EvidencePack interface, C Model Dispatcher, D Discussion Orchestrator + advanced router
- ✅ E Frontend Credentials UI (CredentialsSection in Settings.tsx)
- ⏳ C+1 A2 callsite parity migration (4 generation callsites still on `pool.try_call("generation", ...)`)
- ⏳ F post-MVP hardening (DPAPI, global semaphore, capability matching) — deferred

**Goal:** Enable the frontend to manage multiple runtime API credentials, let the backend merge those credentials with `.env` credentials, support parallel/race/fanout model invocation, and upgrade discussion into a RAG-aware multi-model multi-agent workflow.

**Architecture:** Keep `KeyPool` narrow: credential list, failover, and cooldown only. Add a runtime credential registry as the source layer, add `model_dispatcher.py` for invocation semantics (`failover`, `race`, `fanout`, `parallel_round`), then upgrade `/api/discussion` to call a discussion orchestrator that consumes RAG evidence and dispatches multiple agents in parallel.

**Tech Stack:** FastAPI, Pydantic v2, Python 3.11+, React/Vite/TypeScript, local runtime state under `workspace_artifacts/runtime_state/`, pytest, Vitest, OpenAPI generation.

---

## 1. Current Evidence

| ID | Fact | Evidence |
| --- | --- | --- |
| FACT-001 | Layer 1 failover is complete for generation LLM call sites. | `docs/plans/active/a2-generation-keypool-integration-20260507.md` sections 7-8; full regression recorded as `1857 passed, 4 skipped, 0 failed`. |
| FACT-002 | `KeyPool` currently parses `.env` only and exposes `try_call` / `try_call_async`; `get_pool(path='.env')` is singleton by resolved path. | `literature_assistant/core/key_pool.py:305-540`. |
| FACT-003 | `model_call_gateway.py` already has `with_generation_pool_failover()` and `_resolve_generation_pool()` guards for `RUNTIME_ENV_DISABLE_DOTENV=1` and `LITERATURE_DISABLE_KEY_POOL=1`. | `literature_assistant/core/model_call_gateway.py:457-560`. |
| FACT-004 | Frontend settings currently store one `llm` and one `embedding` config in browser `localStorage`, including `apiKey`. | `frontend/src/services/settingsStore.ts:1-83`. |
| FACT-005 | A settings page exists and can host a new credentials section. | `frontend/src/pages/Settings.tsx`. |
| FACT-006 | `/api/discussion` already exists but each turn runs roles serially and creates `LLMConfig()` defaults instead of agent-specific model configs. | `literature_assistant/core/routers/discussion_router.py:56-131`. |
| FACT-007 | `discussion_bus.py` already defines in-memory sessions, turns, messages, roles, and synthesis. | `literature_assistant/core/discussion_bus.py:1-158`. |
| FACT-008 | Runtime/generated state must live under `workspace_artifacts/`; code should use `project_paths.runtime_state_path()`. | `AI_WORKSPACE_GUIDE.md`; `literature_assistant/core/project_paths.py:109-112`. |

---

## 2. Requirements & Constraints

### Product Requirements

- **REQ-001**: The frontend must allow the user to create, edit, enable/disable, delete, and test multiple credentials for `generation`, `embedding`, and `rerank` categories.
- **REQ-002**: The backend must merge `.env` credentials and runtime credentials into one candidate set without editing `.env`.
- **REQ-003**: Runtime credentials must support multiple providers, multiple models, and multiple protocols without a hard count limit.
- **REQ-004**: Runtime credentials must be usable by current failover paths without breaking `.env`-only workflows.
- **REQ-005**: Model invocation must support three semantics: sequential failover, fastest-success race, and collect-all fanout/broadcast.
- **REQ-006**: Multi-agent discussion must be RAG-aware by default: `query -> evidence pack -> parallel agent round -> synthesis`.
- **REQ-007**: Each discussion agent must be able to bind to a different model/credential strategy.
- **REQ-008**: Discussion traces must include per-agent model metadata, latency, status, and error summaries.
- **REQ-009**: Existing `/api/discussion` route compatibility should be preserved where practical; new request fields must be optional when old fields are enough.

### Security Requirements

- **SEC-001**: API keys must not be persisted only in browser `localStorage` for the multi-credential feature.
- **SEC-002**: Credential list/read endpoints must return masked API keys by default. Full secrets may be accepted on create/update but must not be returned in normal responses.
- **SEC-003**: Credential tests and dispatcher traces must not log full API keys, Authorization headers, or request bodies containing secrets.
- **SEC-004**: Runtime credential files must be placed under `runtime_state_path(...)`, not committed source directories.
- **SEC-005**: Runtime credential writes must be atomic (`tempfile` + `os.replace`) to avoid corrupting credentials during app shutdown or concurrent writes.
- **SEC-006**: Any plaintext-local MVP must be explicitly marked local-only and non-git; encryption/Windows DPAPI hardening must remain a follow-up gate.

### Architecture Constraints

- **CON-001**: Do not put `race()` / `broadcast()` / agent discussion behavior into `KeyPool`.
- **CON-002**: `KeyPool` remains responsible only for credential candidate storage, listing, cooldown, and failover iteration.
- **CON-003**: The model dispatcher owns invocation semantics and concurrency.
- **CON-004**: The discussion orchestrator owns roles, rounds, evidence, and synthesis.
- **CON-005**: Do not modify external reference repositories under `github/`.
- **CON-006**: Use Windows-compatible commands and `.venv-1\Scripts\python.exe` for verification.
- **CON-007**: Preserve `RUNTIME_ENV_DISABLE_DOTENV=1` and `LITERATURE_DISABLE_KEY_POOL=1` as test isolation / opt-out switches.
- **CON-008**: Keep generated/runtime files out of source directories.

### Compatibility Requirements

- **COMP-001**: Existing `.env` parsing behavior in `parse_env_pools()` must remain backward compatible.
- **COMP-002**: Existing `Credential(category, provider, api_key, base_url, model, line_no=0)` constructor usage must remain valid.
- **COMP-003**: Existing A2 tests must continue to pass unchanged unless the test itself is updated to assert the new source behavior.
- **COMP-004**: Existing single-model `Settings` behavior must not regress during the transition.
- **COMP-005**: Existing `/api/discussion/create`, `/status`, `/history`, and `/run` endpoints must remain routable.

---

## 3. Decision Gates

These are the only decisions that should block implementation. If the user does not answer, use the documented default for the first MVP.

| Decision | Question | Recommended Default | Blocks |
| --- | --- | --- | --- |
| DEC-001 | MVP credential secret storage: local plaintext runtime JSON with masked reads, or Windows DPAPI/encryption before first implementation? | Use local plaintext JSON for MVP, under `workspace_artifacts/runtime_state/credentials/runtime_credentials.json`, with masked read responses and no secret logging. Add DPAPI/encryption as Phase 8 hardening. | Phase 1 implementation |
| DEC-002 | First UI scope: all three categories (`generation`, `embedding`, `rerank`) or generation-only first? | Implement all three categories in the backend schema; frontend MVP can expose generation first and mark embedding/rerank as advanced sections if time is tight. | Frontend task sizing |
| DEC-003 | Discussion default shape: how many agents and rounds? | 3 agents (`proponent`, `opponent`, `reviewer`) + optional `moderator`; `max_turns=3` default; hard cap 4 agents and 5 turns for MVP. | Discussion UX and cost guard |
| DEC-004 | Parallel dispatch cost guard: max concurrent generation calls? | Default `MODEL_DISPATCHER_MAX_CONCURRENCY=3`; per-discussion hard cap 4 simultaneous agent calls. | Dispatcher implementation |
| DEC-005 | Evidence scope for discussion: only current RAG query evidence or allow user-selected manual evidence? | Start with RAG query evidence via `project_id + query`; allow optional `evidence_chunk_ids` override in request. | Discussion request contract |
| DEC-006 | Existing single API key in browser settings: auto-migrate or require explicit import? | Do not auto-migrate secrets silently. Show an explicit “Import current chat key into backend credentials” action if `settings.llm.apiKey` exists. | Frontend migration |

### 3.1 Decision Status — 2026-05-07

The user was not available for an interactive decision pass and instructed the agent to work autonomously and make good decisions. Treat the recommended defaults above as accepted for MVP implementation unless the user later overrides them.

| Decision | MVP Execution Status |
| --- | --- |
| DEC-001 | Accepted default: local plaintext runtime JSON under `workspace_artifacts/runtime_state/credentials/`, masked reads, no secret logging, DPAPI/encryption in Phase 8. |
| DEC-002 | Accepted default: backend supports all three categories; frontend first-class flow focuses on generation, with embedding/rerank available as advanced categories. |
| DEC-003 | Accepted default: 3 agents and 3 turns by default; hard cap 4 agents and 5 turns. |
| DEC-004 | Accepted default: max model dispatcher concurrency is 3 unless env overrides lower it. |
| DEC-005 | Accepted default: discussion uses `project_id + query` RAG evidence and accepts optional `evidence_chunk_ids`. |
| DEC-006 | Accepted default: no silent localStorage secret migration; provide explicit import action only. |

### 3.2 Decisions from Grill Rounds (2026-05-07)

Four grill rounds expanded the original 6 decisions to 18. Defaults below are accepted.

#### 3.2.1 Storage / Release Safety (Critical-1)

| Decision | Choice |
|---|---|
| **DEC-001a** Plaintext credential scope | Plaintext runtime JSON allowed only under user-data root. Never in source dirs, PyInstaller datas, onedir, installer, logs, OpenAPI responses, or frontend bundles. |
| **DEC-001b** Frozen storage root | Frozen build writes to `%APPDATA%\LiteratureAssistant\workspace_artifacts\runtime_state\credentials\runtime_credentials.json` (set by `runtime_hook.py`). First launch must show empty credentials directory. |
| **DEC-001c** DPAPI encryption timing | Plaintext acceptable for MVP only if release scan / forbidden-path scan / first-launch empty check are all in place. DPAPI / Windows Credential Manager is Phase 8 hardening, not MVP. |

#### 3.2.2 Endpoint Trust / SSRF (Critical-3)

| Decision | Choice |
|---|---|
| **DEC-002a** Provider Endpoint Policy scope | Shared `provider_endpoint_policy.py` module used by both credential-test endpoint and model dispatcher. Single source of trust enforcement. |
| **DEC-002b** Custom URL test default | `skipped_network=true` for non-allowlisted custom gateways. No Authorization header sent to unverified URLs. |
| **DEC-002c** Source-tiered trust (F1) | Four trust sources — `official_provider` / `env_configured_gateway` / `runtime_user_confirmed` / `runtime_untrusted_custom`. `.env` gateways bypass official-provider host allowlist but never bypass SSRF base validation. |

#### 3.2.3 Discussion Architecture (Critical-2)

| Decision | Choice |
|---|---|
| **DEC-003a** Evidence-pack-first ordering | Slice B (EvidencePack Interface) must ship before Slice D (Discussion Orchestrator). Discussion only consumes EvidencePack; never builds retrieval itself. |
| **DEC-003b** Manual evidence override | `evidence_chunk_ids` / `context` accepted only as replay/debug/manual-override path. Default discussion path is `(project_id, query) -> EvidencePack -> orchestrator`. |
| **DEC-003c** Agent-credential binding (T3-2) | Agents bind to capability/model policy, not directly to `credential_id`. `credential_id` is an explicit pin override. MVP does NOT enforce `required_capabilities` (deferred until cred metadata exists); only `preferred_models` / `preferred_providers` / pinned `credential_id` work. |

#### 3.2.4 Dispatcher Migration (F2)

| Decision | Choice |
|---|---|
| **DEC-004a** Slice C scope | Dispatcher serves discussion + new callers only. A2 four pool-aware callsites (`AIAdapter._invoke_chat`, `query_expander._call_ark_async`, `contextual_chunker._call_summary_once`, `main_rag_workflow._invoke_generation_with_cred`) remain unchanged in Slice C. |
| **DEC-004b** Slice C+1 parity migration | A2 callsites migrated to dispatcher in dedicated parity slice. Must preserve `cache_key_parts` logical model, cred override semantics, cooldown identity (via `credential_fingerprint`), and sync/async paths. |
| **DEC-004c** KeyPool internal reduction (T3-4) | Post-C+1 KeyPool downgrades to internal compatibility primitive. `parse_env_pools` / cooldown / env loading retained; not deleted. New code forbidden from calling `pool.try_call("generation", ...)` directly (enforced via pytest guard). |

#### 3.2.5 Race Cost & Priority (F3)

| Decision | Choice |
|---|---|
| **DEC-005a** Race priority filter | Race launches only top N eligible candidates after priority sort. N = `min(strategy.max_concurrency, MODEL_DISPATCHER_MAX_CONCURRENCY=3, eligible_count)`. Non-selected candidates traced as `skipped_by_priority_filter` with no request sent. |
| **DEC-005b** Race-then-failover | First wave race; on full failure, remaining candidates run sequential failover. Must be explicit strategy name, not race default. |
| **DEC-005c** Discussion two-layer concurrency cap (F10) | Discussion Orchestrator owns `agent_concurrency` (default 2). Total upper bound ~ `agent_concurrency × MODEL_DISPATCHER_MAX_CONCURRENCY`. Global semaphore deferred. |

#### 3.2.6 Release Gate Hardening (R1 / R2 / R3)

| Decision | Choice |
|---|---|
| **DEC-006a** Secret scan baseline ban (R1) | Release secret scan runs bare — no `.secrets.baseline`, no suppression. `.secrets.baseline` itself appearing in release roots is a forbidden-path failure. |
| **DEC-006b** Release scan root isolation (R2) | Scan roots are explicit payload paths (e.g. `workspace_artifacts/releases/<version>/onedir/LiteratureAssistant/`). The audit metadata directory `workspace_artifacts/releases/_rejected/` is outside scan roots. `_rejected/` appearing inside payload root is a failure. |
| **DEC-006c** PyInstaller Analysis manifest gate (R3) | Preflight runs PyInstaller to Analysis stage and dumps actual collected datas/binaries/source mappings. Forbidden-path scan operates on this manifest, not on spec AST/text. |
| **DEC-006d** No quarantine of contents | Failed gates write redacted JSON only. Never copy/move offending files to `_rejected/`. |
| **DEC-006e** runtime_state hard isolation | Any occurrence of `workspace_artifacts/runtime_state/**` in Analysis manifest or final onedir = release blocker. |

#### 3.2.7 Identity / Test Isolation (M1, F8, F9)

| Decision | Choice |
|---|---|
| **DEC-007a** Credential ID vs fingerprint separation | `credential_id` (UUID) = UI/CRUD/selection identity. `credential_fingerprint` = `sha256("v1" + provider + normalized_base_url + model + sha256(api_key))[:16]` = cooldown/health identity. |
| **DEC-007b** Fingerprint version reset | Fingerprint version prefix bumps intentionally reset all cooldown/health state. Documented as expected migration behavior. |
| **DEC-007c** Three orthogonal disable flags | `LITERATURE_DISABLE_RUNTIME_CREDENTIALS=1` (registry only), `RUNTIME_ENV_DISABLE_DOTENV=1` (.env only), `LITERATURE_DISABLE_KEY_POOL=1` (entire pool / failover) — orthogonal. Tests can isolate each source. |

#### 3.2.8 Trust UX & Migration (M5, T3-3)

| Decision | Choice |
|---|---|
| **DEC-008a** Two-button trust UX | "Import and Trust" / "Cancel" only. No saved-untrusted purgatory state. |
| **DEC-008b** No silent localStorage migration | Existing `settings.llm.apiKey` requires explicit "Import current chat key into backend credentials" CTA. Frontend never auto-uploads localStorage secrets. |


---

## 4. Target Architecture

### 4.1 Layer Responsibilities

| Layer | Module(s) | Responsibility | Not Responsible For |
| --- | --- | --- | --- |
| Layer 1 | `key_pool.py` | Candidate list, source merge, failover iteration, cooldown | Parallelism, debate, synthesis, UI persistence |
| Layer 2 | `credential_sources.py`, `credential_registry.py`, `credentials_router.py` | Runtime credential CRUD, `.env + runtime` merge, masked public API, credential testing | Model invocation strategies |
| Layer 3 | `model_dispatcher.py` | `failover`, `race`, `fanout`, `parallel_round`, timeout, partial result metadata | Credential editing or discussion roles |
| Layer 4 | `discussion_orchestrator.py`, `discussion_store.py` | RAG-aware discussion sessions, role prompts, per-agent model config, synthesis | Raw credential storage |
| Frontend | `Settings.tsx`, `credentialsApi.ts`, `Discussion.tsx` | Credential management UI, discussion setup UI, result display | Secret persistence logic |

### 4.2 Runtime Data Flow

1. User opens Settings and creates credentials.
2. Frontend sends full `api_key` only to `POST/PUT /api/credentials`.
3. Backend validates and atomically writes runtime credentials under `runtime_state_path("credentials", "runtime_credentials.json")`.
4. `credential_registry` merges runtime credentials with `.env` credentials.
5. `key_pool.get_pool(refresh=True)` can build a `KeyPool` from merged sources.
6. `model_dispatcher` receives candidate filters (`category`, `protocol`, tags, ids) and invokes model calls using the selected semantic mode.
7. `discussion_orchestrator` builds an evidence pack, then calls `model_dispatcher.run_parallel_round(...)` for each discussion turn.
8. `discussion_store` persists session state and traces under runtime state.

### 4.3 Credential Schema

Runtime file path:

`workspace_artifacts/runtime_state/credentials/runtime_credentials.json`

Schema version: `1`

```json
{
  "schema_version": 1,
  "updated_at": "2026-05-07T00:00:00Z",
  "credentials": [
    {
      "id": "cred_generation_anyrouter_opus",
      "category": "generation",
      "provider": "AnyRouter",
      "model": "claude-opus-4-7",
      "base_url": "https://anyrouter.top",
      "api_key": "REDACTED_IN_DOCS",
      "protocol": "anthropic_messages",
      "enabled": true,
      "priority": 100,
      "tags": ["discussion", "quality"],
      "strategy_hint": "quality",
      "created_at": "2026-05-07T00:00:00Z",
      "updated_at": "2026-05-07T00:00:00Z"
    }
  ]
}
```

Public API response must replace `api_key` with:

```json
{
  "api_key_masked": "sk-...abcd",
  "has_api_key": true
}
```

Allowed enums:

| Field | Values |
| --- | --- |
| `category` | `generation`, `embedding`, `rerank` |
| `protocol` | `openai_chat_completions`, `openai_responses`, `anthropic_messages`, `embeddings`, `rerank` |
| `strategy_hint` | `default`, `cheap`, `fast`, `quality`, `discussion`, `embedding`, `rerank` |

### 4.4 Endpoint Trust Model (DEC-002c)

A four-tier trust hierarchy. Every credential carries a `trust_source` field; dispatch and test endpoints branch on it.

| Trust source | Origin | Dispatch allowed | Network test allowed | Bypasses official-host allowlist | Bypasses SSRF base validation |
|---|---|---|---|---|---|
| `official_provider` | Built-in preset (OpenAI / Anthropic / DeepSeek / Doubao-Ark / Gemini / OpenRouter / SiliconFlow / DashScope / Groq / Mistral) | yes | yes | yes (it IS the allowlist) | no |
| `env_configured_gateway` | `.env` `[CRED:*]` blocks parsed by `key_pool.parse_env_pools` | yes | yes (with `env-gateway` trace tag) | yes | no |
| `runtime_user_confirmed` | Saved via `POST /api/credentials` AND user clicked "Import and Trust" in UI | yes | yes | yes | no |
| `runtime_untrusted_custom` | Saved via API but custom host not yet user-confirmed | no (default) | `skipped_network=true` | no (denied unless allowlist match) | no |

**SSRF base validation (always enforced)**:
1. URL parse + reject malformed
2. Reject userinfo (no `user:pass@host`)
3. scheme lowercase; remote requires HTTPS
4. host normalize (lowercase, no trailing dot)
5. DNS resolve A/AAAA
6. Reject loopback / private / link-local / multicast / reserved IPs
7. `follow_redirects=False` on test
8. Authorization header constructed AFTER all validation passes
9. Response size cap; short timeout (3-5s)
10. No raw secret in logs / responses

**Local gateway exception** (deferred, not MVP): `local_gateway_enabled` mode allows loopback with explicit user toggle, port allowlist, and "no cloud key forwarding" guarantee. Not in Slice A0-E.

### 4.5 Two-Layer Concurrency Cap (DEC-005c, F10)

Two independent concurrency gates to prevent multiplicative cost blowup:

```
Discussion request
  └─ DiscussionOrchestrator.run_round
        owns: agent_concurrency = 2  (env: DISCUSSION_AGENT_MAX_CONCURRENCY)
        ↓
        For each agent_slot (≤ agent_concurrency in flight):
          └─ ModelDispatcher.dispatch (race / fanout / failover)
                owns: per-call max = 3  (env: MODEL_DISPATCHER_MAX_CONCURRENCY)
```

Total upper bound per discussion round ≈ `agent_concurrency × MODEL_DISPATCHER_MAX_CONCURRENCY` = 6.

Process-wide global semaphore deferred to Slice C+1 / release hardening.


---

## 5. Implementation Steps

### Phase 0 — Preflight and Rollback

- **GOAL-000**: Ensure implementation starts from a known state and has a rollback path.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-000 | Create rollback snapshot for files touched by Phase 1-3 before editing. | `.rollback_snapshots/manual-<timestamp>/...` | Snapshot directory exists and includes target files before edits. | | |
| TASK-001 | Confirm dirty working tree and identify unrelated changes. Do not revert unrelated files. | Git working tree | `git status --short` captured in plan execution notes. | | |
| TASK-002 | Run baseline focused tests before changes. | Existing tests | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_key_pool.py tests/test_ai_adapter_keypool.py -q` passes. | | |

### Phase 1 — Runtime Credential Models and Store

- **GOAL-001**: Add a backend-only runtime credential persistence layer with masked public views and atomic writes.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-101 | Add credential Pydantic models and enum values. Include `RuntimeCredential`, `RuntimeCredentialPublic`, `RuntimeCredentialCreate`, `RuntimeCredentialUpdate`, `CredentialCategory`, `CredentialProtocol`, and `CredentialStrategyHint`. | Create `literature_assistant/core/models/credentials.py` | `\.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant/core/models/credentials.py` passes. | | |
| TASK-102 | Add store tests first. Cover empty file, create, update, delete, masked public output, atomic write, invalid schema rejection, and no full secret in public dump. | Create `tests/test_runtime_credentials_store.py` | Tests fail before implementation because store is missing. | | |
| TASK-103 | Implement `RuntimeCredentialStore`. Use `runtime_state_path("credentials", "runtime_credentials.json")`, same-directory temp file, `os.replace`, and UTF-8 JSON. | Create `literature_assistant/core/credential_store.py` | `tests/test_runtime_credentials_store.py` passes. | | |
| TASK-104 | Add `mask_api_key(value: str) -> str` helper. Return empty string for no key; preserve only a short prefix/suffix for real values. | `literature_assistant/core/credential_store.py` or `models/credentials.py` | Unit test asserts full key never appears in public model JSON. | | |
| TASK-105 | Add migration guard for future schema versions. Version `1` is accepted; unknown higher version raises a clear `ValueError`. | `literature_assistant/core/credential_store.py` | Unit test for unsupported schema passes. | | |

### Phase 2 — Credential Sources and KeyPool Integration

- **GOAL-002**: Let `KeyPool` consume merged `.env` and runtime credentials without becoming a UI or dispatcher layer.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-201 | Add source abstraction: `CredentialSource` protocol, `EnvCredentialSource`, `RuntimeCredentialSource`, `MergedCredentialSource`. | Create `literature_assistant/core/credential_sources.py` | New unit tests can instantiate each source independently. | | |
| TASK-202 | Add source tests. Verify env-only, runtime-only, merged priority order, disabled runtime credentials skipped, protocol metadata preserved, and duplicate ids de-duplicated deterministically. | Create `tests/test_credential_sources.py` | Tests fail before implementation, pass after. | | |
| TASK-203 | Extend `key_pool.Credential` with trailing optional fields: `id`, `source`, `enabled`, `priority`, `protocol`, `tags`, `strategy_hint`. Keep current constructor calls valid by giving defaults. | Modify `literature_assistant/core/key_pool.py` | Existing `tests/test_key_pool.py` still passes without edits. | | |
| TASK-204 | Add `build_pool_from_sources(sources: list[CredentialSource]) -> KeyPool` or equivalent helper. Keep `parse_env_pools()` unchanged for compatibility. | Modify `literature_assistant/core/key_pool.py` | `tests/test_credential_sources.py` passes. | | |
| TASK-205 | Add optional `source` / `sources` parameter to `get_pool(...)` without breaking `get_pool(path='.env', refresh=False)`. Runtime source should only be used when explicitly requested by registry/gateway code. | Modify `literature_assistant/core/key_pool.py` | Existing A2 tests and new source tests pass. | | |
| TASK-206 | Update `model_call_gateway._resolve_generation_pool()` to use merged credential registry when runtime credentials are enabled. Preserve `RUNTIME_ENV_DISABLE_DOTENV=1` and `LITERATURE_DISABLE_KEY_POOL=1`. | Modify `literature_assistant/core/model_call_gateway.py` | Existing A2 tests pass; new test confirms runtime credential can be selected. | | |

### Phase 3 — Credentials API

- **GOAL-003**: Expose secure local CRUD and test endpoints for runtime credentials.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-301 | Add API tests first for list, create, update, delete, masked response, and validation errors. | Create `tests/test_credentials_router.py` | Tests fail before router exists. | | |
| TASK-302 | Implement `credentials_router.py` with `GET /api/credentials`, `POST /api/credentials`, `PUT /api/credentials/{credential_id}`, `DELETE /api/credentials/{credential_id}`. | Create `literature_assistant/core/routers/credentials_router.py` | Router tests pass; response never contains raw `api_key`. | | |
| TASK-303 | Implement `POST /api/credentials/{credential_id}/test`. For MVP, perform provider/protocol-specific lightweight request only when safe; otherwise validate presence and return `skipped_network=true`. | `literature_assistant/core/routers/credentials_router.py` | Tests cover success, failure, and skipped-network cases with mocked clients. | | |
| TASK-304 | Register router in ASGI app and OpenAPI tags. | Modify `literature_assistant/core/python_adapter_server.py`; update OpenAPI tag list if present | `/openapi.json` includes `/api/credentials`. | | |
| TASK-305 | Regenerate frontend OpenAPI aliases if this repo's workflow requires it. | `frontend/openapi/modular-pipeline-openapi.json`; `frontend/src/generated/openapi.ts` | OpenAPI generation command passes. | | |

### Phase 4 — Frontend Credential Management UI

- **GOAL-004**: Move multi-API management into backend-backed credentials UI while preserving existing settings preferences.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-401 | Add typed frontend API client for credentials. | Create `frontend/src/services/credentialsApi.ts` | TypeScript build passes. | | |
| TASK-402 | Add unit tests for credentials client request/response mapping, especially masked key fields. | Create `frontend/src/services/credentialsApi.test.ts` or equivalent existing test pattern | Vitest passes. | | |
| TASK-403 | Extend `Settings.tsx` section ids with `credentials`. Add navigation item and lazy-free local component for credential cards. | Modify `frontend/src/pages/Settings.tsx` | Frontend build passes; settings page renders credentials section. | | |
| TASK-404 | Add credential form fields: category, provider, model, base URL, protocol, API key, enabled, priority, tags, strategy hint. Use password field with show/hide toggle. | `frontend/src/pages/Settings.tsx` or extracted `frontend/src/components/settings/CredentialsSection.tsx` | UI test or smoke confirms add/edit form state. | | |
| TASK-405 | Do not store credential secrets in `settingsStore.ts`. Keep `settingsStore.ts` for non-secret LLM defaults, retrieval topK, and workspace preferences. | Modify `frontend/src/services/settingsStore.ts` only if needed | Existing `settingsStore` tests still pass. | | |
| TASK-406 | If an old `settings.llm.apiKey` exists, show explicit import CTA. On click, POST it to backend credentials and then clear/keep according to user confirmation; no silent migration. | `frontend/src/pages/Settings.tsx`; `credentialsApi.ts` | Test/manual smoke confirms no auto-secret migration. | | |

### Phase 5 — Model Dispatcher

- **GOAL-005**: Add reusable invocation semantics for failover, race, fanout, and parallel agent rounds.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-501 | Add dispatcher tests first. Cover failover order, race fastest-success, fanout partial failures, timeout, max concurrency, and metadata redaction. | Create `tests/test_model_dispatcher.py` | Tests fail before dispatcher exists. | | |
| TASK-502 | Implement data models: `DispatchMode`, `DispatchCandidate`, `DispatchResult`, `DispatchBatchResult`, `DispatchErrorSummary`. | Create `literature_assistant/core/model_dispatcher.py` | Compile passes. | | |
| TASK-503 | Implement `invoke_failover(candidates, invoke_candidate, timeout_seconds)`. It should be a wrapper around sequential candidate attempts and preserve cooldown behavior when a candidate is backed by `KeyPool`. | `literature_assistant/core/model_dispatcher.py` | Failover test passes. | | |
| TASK-504 | Implement `invoke_race(candidates, invoke_candidate, timeout_seconds, max_concurrency)`. Return first successful result and cancel/ignore slower tasks safely. | `literature_assistant/core/model_dispatcher.py` | Race test passes deterministically with fake async delays. | | |
| TASK-505 | Implement `invoke_fanout(candidates, invoke_candidate, timeout_seconds, max_concurrency)`. Return all successes and structured errors without raising unless all fail and caller requests strict mode. | `literature_assistant/core/model_dispatcher.py` | Fanout partial-failure test passes. | | |
| TASK-506 | Implement `run_parallel_round(agent_slots, invoke_agent, max_concurrency)`. Each result must include `agent_id`, `role`, `credential_id`, `provider`, `model`, `latency_ms`, `success`, and `error_summary`. | `literature_assistant/core/model_dispatcher.py` | Parallel-round test passes. | | |
| TASK-507 | Add env-driven cost/concurrency guards: `MODEL_DISPATCHER_MAX_CONCURRENCY`, `MODEL_DISPATCHER_DEFAULT_TIMEOUT_SECONDS`, `MODEL_DISPATCHER_ALLOW_RACE`. | `literature_assistant/core/model_dispatcher.py` | Unit tests cover default and env override. | | |

### Phase 6 — RAG-aware Discussion Orchestrator

- **GOAL-006**: Upgrade existing discussion from serial single-model prototype to RAG-aware multi-model agent discussion.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-601 | Add discussion model tests first. Cover request parsing with `project_id`, `query`, `agent_configs`, `max_turns`, and optional `evidence_chunk_ids`. | Create or extend `tests/test_discussion_router.py` | Tests fail before models/router update. | | |
| TASK-602 | Add/extend Pydantic models for `DiscussionAgentConfig`, `DiscussionEvidencePack`, `DiscussionRunConfig`, `DiscussionTrace`, and `DiscussionSynthesis`. | Create `literature_assistant/core/models/discussion.py` or extend existing discussion module | Compile and model tests pass. | | |
| TASK-603 | Implement `discussion_store.py` to persist sessions and traces under `runtime_state_path("discussion", ...)`. Use atomic writes. | Create `literature_assistant/core/discussion_store.py` | Store tests pass. | | |
| TASK-604 | Implement `discussion_orchestrator.py`. It should build prompts per role, attach evidence snippets, call `model_dispatcher.run_parallel_round`, and produce synthesis with a moderator/synthesizer config. | Create `literature_assistant/core/discussion_orchestrator.py` | Orchestrator tests pass with mocked dispatcher. | | |
| TASK-605 | Update `discussion_router.py` to delegate to orchestrator. Preserve existing endpoints; extend request/response schemas rather than removing fields. | Modify `literature_assistant/core/routers/discussion_router.py` | Existing and new discussion router tests pass. | | |
| TASK-606 | Add evidence-pack adapter. MVP input should accept `project_id + query`; if direct RAG adapter is too large, allow caller-provided `context` / `evidence_chunk_ids` as a first vertical slice. | `discussion_orchestrator.py`; possibly existing retrieval/chat modules | Unit test confirms evidence included in each agent prompt. | | |
| TASK-607 | Add synthesis strategies: `synthesize` default; `vote` and `debate` may be modelled but can be disabled until implemented. | `discussion_orchestrator.py`; models | Test confirms unsupported strategy returns 400 or validation error, not silent fallback. | | |

### Phase 7 — Discussion Frontend Upgrade

- **GOAL-007**: Let users configure multi-model agent discussions from the frontend.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-701 | Extend discussion API types to include agent configs, evidence options, trace metadata, and synthesis output. | Modify `frontend/src/services/discussionApi.ts` | TypeScript build passes. | | |
| TASK-702 | Update discussion page to select credentials/models per role. Reuse credentials API list endpoint; display only masked credential labels. | Modify `frontend/src/pages/Discussion.tsx` | Manual smoke: user can select different models per role. | | |
| TASK-703 | Add controls for discussion mode: failover, race, fanout/parallel round; default to parallel round with failover inside each agent slot. | `frontend/src/pages/Discussion.tsx` | UI state maps to API request. | | |
| TASK-704 | Show per-agent trace cards with provider/model/latency/status/error summary and final synthesis. | `frontend/src/pages/Discussion.tsx` | Manual smoke confirms trace visibility without secrets. | | |
| TASK-705 | Add frontend tests for request construction and masked credential display if current test setup supports it. | `frontend/src/pages/Discussion.test.tsx` or service tests | Vitest passes. | | |

### Phase 8 — Hardening and Release Gates

- **GOAL-008**: Verify security, compatibility, OpenAPI, and regression gates before release or packaging.

| Task | Description | Files | Validation | Completed | Date |
| --- | --- | --- | --- | --- | --- |
| TASK-801 | Add secret scanning checks for new runtime credential fixtures and docs. Ensure docs use `REDACTED_IN_DOCS`, not real-looking keys. | Docs/tests | Grep for raw key patterns in changed files. | | |
| TASK-802 | Add OpenAPI generation and frontend generated types update. | OpenAPI artifacts | OpenAPI route count change is expected and documented. | | |
| TASK-803 | Run focused backend tests. | Tests | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_key_pool.py tests/test_runtime_credentials_store.py tests/test_credential_sources.py tests/test_credentials_router.py tests/test_model_dispatcher.py tests/test_discussion_router.py -q` passes. | | |
| TASK-804 | Run focused frontend tests/build. | Frontend | From `frontend/`, `npm run build` and relevant tests pass. | | |
| TASK-805 | Run broader backend regression excluding known unrelated provider flake if still documented. | Tests | `\.\.venv-1\Scripts\python.exe -m pytest tests --ignore=tests/test_llm_provider_routing.py -q` passes or failures are triaged. | | |
| TASK-806 | Document runtime credential behavior and local security caveat in user docs. | README or runbook | User docs explain where credentials are stored and how to remove them. | | |
| TASK-807 | Optional hardening: add Windows DPAPI encryption for runtime JSON values if DEC-001 chooses encryption before MVP or after MVP. | New/modified credential store module | Encryption/decryption tests pass; plaintext API keys are not visible in runtime JSON. | | |

---

## 6. File Impact Map

### Backend Create

- **FILE-001**: `literature_assistant/core/models/credentials.py` — credential request/response/domain models.
- **FILE-002**: `literature_assistant/core/credential_store.py` — runtime JSON persistence and masking.
- **FILE-003**: `literature_assistant/core/credential_sources.py` — `.env` and runtime credential source abstraction.
- **FILE-004**: `literature_assistant/core/routers/credentials_router.py` — local credential CRUD/test API.
- **FILE-005**: `literature_assistant/core/model_dispatcher.py` — failover/race/fanout/parallel round semantics.
- **FILE-006**: `literature_assistant/core/models/discussion.py` — discussion request/trace/synthesis models if not kept in router.
- **FILE-007**: `literature_assistant/core/discussion_store.py` — persistent discussion sessions/traces.
- **FILE-008**: `literature_assistant/core/discussion_orchestrator.py` — RAG-aware multi-agent orchestration.

### Backend Modify

- **FILE-101**: `literature_assistant/core/key_pool.py` — optional metadata on `Credential`; source-aware pool construction while preserving env parser.
- **FILE-102**: `literature_assistant/core/model_call_gateway.py` — resolve generation pool from merged registry; preserve A2 guards.
- **FILE-103**: `literature_assistant/core/routers/discussion_router.py` — delegate to orchestrator and extend schemas.
- **FILE-104**: `literature_assistant/core/python_adapter_server.py` — register credentials router and OpenAPI tag.

### Frontend Create

- **FILE-201**: `frontend/src/services/credentialsApi.ts` — typed credentials API client.
- **FILE-202**: `frontend/src/components/settings/CredentialsSection.tsx` — optional extracted UI component if `Settings.tsx` becomes too large.

### Frontend Modify

- **FILE-301**: `frontend/src/pages/Settings.tsx` — add credential management section.
- **FILE-302**: `frontend/src/services/settingsStore.ts` — remove/avoid new secret persistence responsibilities; keep non-secret preferences.
- **FILE-303**: `frontend/src/services/discussionApi.ts` — extended discussion contracts.
- **FILE-304**: `frontend/src/pages/Discussion.tsx` — multi-model agent selection and trace display.
- **FILE-305**: `frontend/src/generated/openapi.ts` and `frontend/openapi/modular-pipeline-openapi.json` — update generated API types when router changes.

### Tests Create/Modify

- **FILE-401**: `tests/test_runtime_credentials_store.py`.
- **FILE-402**: `tests/test_credential_sources.py`.
- **FILE-403**: `tests/test_credentials_router.py`.
- **FILE-404**: `tests/test_model_dispatcher.py`.
- **FILE-405**: `tests/test_discussion_router.py` or extend existing discussion tests.
- **FILE-406**: `frontend/src/services/credentialsApi.test.ts` or equivalent test file.
- **FILE-407**: `frontend/src/pages/Discussion.test.tsx` if current frontend test stack supports component tests.

---

## 7. Testing Strategy

| Test ID | Scope | Command | Expected Result |
| --- | --- | --- | --- |
| TEST-001 | Credential store unit | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_runtime_credentials_store.py -q` | Pass; no full API key in public model JSON. |
| TEST-002 | Credential sources + KeyPool compatibility | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_key_pool.py tests/test_credential_sources.py -q` | Pass; old constructor calls still valid. |
| TEST-003 | Credentials API | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_credentials_router.py -q` | Pass; raw secrets never returned. |
| TEST-004 | Model dispatcher | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_model_dispatcher.py -q` | Pass; deterministic fake async race/fanout behavior. |
| TEST-005 | Discussion orchestrator/router | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_discussion_router.py -q` | Pass; agent configs and evidence pack included. |
| TEST-006 | A2 regression | `\.\.venv-1\Scripts\python.exe -m pytest tests/test_ai_adapter_keypool.py tests/test_key_pool.py -q` | Pass. |
| TEST-007 | Frontend build | `npm run build` from `frontend/` | Pass. |
| TEST-008 | Full backend regression | `\.\.venv-1\Scripts\python.exe -m pytest tests --ignore=tests/test_llm_provider_routing.py -q` | Pass or document unrelated known flake. |

---

## 8. Rollback Plan

| Rollback ID | Trigger | Action |
| --- | --- | --- |
| RB-001 | Credential router breaks OpenAPI or app startup | Remove `credentials_router` registration from `python_adapter_server.py`; keep store/source files unused. |
| RB-002 | Runtime credentials break `.env` failover | Set `LITERATURE_DISABLE_KEY_POOL=1` for immediate runtime fallback; revert `model_call_gateway.py` and `key_pool.py` source-aware changes. |
| RB-003 | Frontend credentials UI blocks settings page | Remove `credentials` section from `SECTION_IDS`; keep backend API intact. |
| RB-004 | Dispatcher causes cost/concurrency spike | Set `MODEL_DISPATCHER_MAX_CONCURRENCY=1` and disable race/fanout flags; discussion falls back to sequential. |
| RB-005 | Discussion orchestrator regresses existing endpoints | Restore router's old `chat_ask` path behind a compatibility flag while keeping new orchestrator disabled. |

---

## 9. Risks & Mitigations

- **RISK-001**: Plaintext runtime credential JSON is convenient but less secure. **Mitigation:** local-only runtime path, masked reads, no git, no logging, DPAPI Phase 8 hardening.
- **RISK-002**: KeyPool singleton may serve stale runtime credentials. **Mitigation:** registry-triggered `refresh=True` or explicit source version cache key.
- **RISK-003**: Mixed protocols in one candidate pool can cause predictable 4xx failures. **Mitigation:** make `protocol` required for runtime credentials and filter by protocol before dispatch.
- **RISK-004**: Race/fanout increases cost. **Mitigation:** max concurrency env, UI warnings, manual user action, per-discussion caps.
- **RISK-005**: Discussion evidence integration can sprawl into a full RAG refactor. **Mitigation:** MVP accepts `project_id + query` and optional `evidence_chunk_ids`; defer deep retrieval pipeline changes.
- **RISK-006**: `Settings.tsx` may become too large. **Mitigation:** extract `CredentialsSection.tsx` if credential UI exceeds a small focused block.

---

## 10. Alternatives Considered

- **ALT-001: Put runtime credentials and parallel primitives into `KeyPool`.** Rejected because it would turn a small failover abstraction into a multi-agent framework.
- **ALT-002: Do discussion orchestrator first.** Rejected because discussion needs frontend-managed model credentials; otherwise it remains hardcoded/default model only.
- **ALT-003: Build a full encrypted credential vault first.** Deferred because it delays MVP; use DEC-001 if user requires encryption before any local persistence.
- **ALT-004: Keep browser `localStorage` for multiple API keys.** Rejected because secrets would remain frontend-only and cannot reliably feed backend RAG/discussion flows.
- **ALT-005: Replace existing `/api/discussion`.** Rejected; extend it to preserve route compatibility and existing frontend links.

---

## 11. Execution Recommendation

Recommended vertical slices:

1. **Slice A: Runtime Credential Registry** — Phases 1-4. Delivers frontend API management and backend merged credentials.
2. **Slice B: Model Dispatcher** — Phase 5. Delivers reusable parallel/race/fanout semantics.
3. **Slice C: RAG-aware Discussion** — Phases 6-7. Delivers multi-model agent discussion using dispatcher.
4. **Slice D: Hardening** — Phase 8. Security, docs, release checks, optional DPAPI.

Do not start Slice B before Slice A has at least backend credential registry tests passing. Do not start Slice C before Slice B has deterministic mocked dispatcher tests passing.

---

## 12. Context Snapshot

Facts:

- A2.2 Layer 1 failover is complete for 4 LLM call sites; regression recorded as `1857 passed, 4 skipped, 0 failed` in `a2-generation-keypool-integration-20260507.md`.
- Existing discussion stack is present but serial/default-model: `discussion_router.py` + `discussion_bus.py`.
- Existing settings stack stores a single API key in `localStorage`: `settingsStore.ts`.

Decisions:

- Proceed with a plan instead of open-ended grilling; product intent is clear enough.
- Keep `KeyPool` narrow and add `model_dispatcher.py` for parallel semantics.
- Treat agent discussion as RAG-aware by default.

Open:

- DEC-001 through DEC-006 above need explicit user confirmation or default acceptance before implementation.

Next:

- Get user answer for decision gates, especially DEC-001.
- Implement Slice A first with tests before touching dispatcher or discussion orchestration.

---

## 13. Slice Order and Hard Constraints (v2 Authoritative)

### 13.1 Slice Order

| # | Slice | Goal | Blocked by | Deliverable |
|---|---|---|---|---|
| 1 | **A0** Release Safety | Forbidden-path scan + secret scan + PyInstaller manifest gate + frozen first-launch storage check | (none — start here) | Release gate scripts + tests |
| 2 | **A1** Credential Registry | RuntimeCredential models, store with masking + atomic write, credential_id ↔ fingerprint separation | A0 | Backend store + tests |
| 3 | **A2** Provider Endpoint Policy | `provider_endpoint_policy.py` (4-tier trust + SSRF guard) | A1 | Shared policy module + SSRF tests |
| 4 | **A3** Credential Test Endpoint | `POST /api/credentials/{id}/test` using A2 policy; custom default = `skipped_network=true` | A1, A2 | API + tests |
| 5 | **E (early)** Frontend Credentials UI | Multi-credential CRUD + masked display + two-button trust + import-from-localStorage CTA | A3 | Frontend section |
| 6 | **B** EvidencePack Interface | `build_evidence_pack(project_id, query, ...)` returning versioned `EvidencePack` artifact (no LLM call, no persistent reuse cache) | (parallel to A0-A3) | Module + tests + artifact dumps |
| 7 | **C** Model Dispatcher | `failover` / `race` / `fanout` / `broadcast` / `parallel_round`; consumes credential resolver + endpoint policy; serves discussion + new callers | A2, B | Dispatcher + tests |
| 8 | **C+1** A2 Parity Migration | Migrate `AIAdapter` / `query_expander` / `contextual_chunker` / `main_rag_workflow` from `pool.try_call("generation", ...)` to dispatcher; preserve cache / cred override / cooldown | C | Migrated callsites + parity tests |
| 9 | **D** Discussion Orchestrator | RAG-aware multi-agent rounds consuming EvidencePack via dispatcher; capability-based agent binding | B, C | Orchestrator + tests + frontend wiring |
| 10 | **F** (post-MVP hardening) | DPAPI / Windows Credential Manager / global concurrency semaphore / capability matching | All above | Deferred |

### 13.2 Hard Constraints (non-negotiable)

These must hold throughout v2 implementation. Violation = revert.

1. **Env gateway compatibility** — Provider Endpoint Policy must not break existing `.env`-sourced generation pool credentials. Hosts discovered from `.env` are treated as `env_configured_gateway` and bypass official-provider host allowlist, but never bypass SSRF base validation.
2. **Dispatcher migration** — Slice C introduces dispatcher for new discussion flows only. Existing A2 pool-aware generation callsites remain unchanged until Slice C+1 parity migration proves cache key / credential override / cooldown / sync/async behavior equivalence.
3. **Race cost** — Race dispatch launches only the top N eligible candidates after priority sorting, where N is bounded by `MODEL_DISPATCHER_MAX_CONCURRENCY`. Non-selected candidates are not called and are traced as `skipped_by_priority_filter`.
4. **Release secret scan baseline ban** — Release scans must not use `.secrets.baseline` or any baseline suppression. Any secret finding in release payload roots is a release blocker.
5. **Release scan root isolation** — Scan roots are explicit payload roots (e.g. `workspace_artifacts/releases/<version>/onedir/LiteratureAssistant/`). `workspace_artifacts/releases/_rejected/` is an audit metadata directory and is outside scan roots.
6. **PyInstaller Analysis manifest gate** — Preflight runs PyInstaller to Analysis stage and dumps actual `datas`/`binaries`/source mappings. Forbidden-path scan operates on this manifest. Spec AST/text grep is informational only.
7. **No copied quarantine contents** — Failed gates write redacted JSON reports under `workspace_artifacts/releases/_rejected/<timestamp>.json`. Must not copy or move offending files into `_rejected/`.
8. **Onedir final fact gate** — Final onedir scan remains mandatory even if Analysis manifest preflight passes (PyInstaller hooks / post-build copies / Inno Source declarations may add files).
9. **Runtime-state packaging hard isolation** — Any occurrence of `workspace_artifacts/runtime_state/**` in Analysis manifest or final onedir = release blocker.
10. **Fingerprint version reset** — Changing credential fingerprint version intentionally resets cooldown/health history.
11. **Dotenv / runtime / pool source isolation** — `LITERATURE_DISABLE_RUNTIME_CREDENTIALS=1` ⊥ `RUNTIME_ENV_DISABLE_DOTENV=1` ⊥ `LITERATURE_DISABLE_KEY_POOL=1`. Tests can isolate each source independently.
12. **Discussion concurrency cap** — Discussion Orchestrator owns agent-level concurrency (`DISCUSSION_AGENT_MAX_CONCURRENCY`, default 2); dispatcher max concurrency is per-call only.
13. **MVP capability matching deferred** — MVP dispatcher/agent selection does not enforce `required_capabilities`; only `preferred_models` / `preferred_providers` / pinned `credential_id` are honored.
14. **Two-button trust UX** — `[Import and Trust]` / `[Cancel]` only. No "saved-untrusted" purgatory state.
15. **No silent localStorage migration** — Frontend must never auto-upload `settings.llm.apiKey` to backend.
16. **EvidencePack no persistent cache MVP** — Slice B emits versioned EvidencePack artifacts only; no reuse cache until corpus/version invalidation logic exists.
17. **Agent capability binding default** — Discussion agents bind to model/capability policy by default; direct `credential_id` binding is an explicit pin override only (`strict_pin=false` allows fallback).
18. **Runtime trust UX** — Runtime custom gateway requires explicit local-user confirmation before network test or dispatch; saving a credential does not imply trust.

### 13.3 OpenAPI Baseline Reset Plan

| Stage | Action |
|---|---|
| Pre-A0 | Current sha256 = `83924b31e3a28b7714a493e9157507b81c2fe43a8fc4103bff7824dd00adc081` (135 routes). |
| During A1-A3 | Sha will change as `/api/credentials/*` (5+) and `/api/credentials/{id}/test` are added. Do not maintain old invariant. |
| End of Slice A3 | `OPENAPI_SHA_AFTER_SLICE_A = 5ef7d4e42e047f2a3eb2102c95468036afc90036fbc3c90c6e448881ba28a26a` (138 routes; +3 paths: GET/POST `/api/credentials`, GET/PUT/DELETE `/api/credentials/{credential_id}`, POST `/api/credentials/{credential_id}/test`). Captured 2026-05-08. |
| End of Slice D | `OPENAPI_SHA_AFTER_SLICE_D = 01fcbc27e80eb24c7510e5ee17b75df5cef75df3458c68cb4f1cc1a2a0cbe9ac` (139 routes; +1 path: POST `/api/discussion/runs`). Captured 2026-05-08. |
| During B-E | Each slice records expected route additions. Maintain post-A baseline. |


---

## 14. Endpoint Trust Model (Detailed)

(see §4.4 for the trust source table; this section enumerates concrete provider hosts and SSRF reject patterns)

### 14.1 Official Provider Allowlist (DEC-002c)

| Provider | Canonical hosts |
|---|---|
| OpenAI | `api.openai.com` |
| Anthropic | `api.anthropic.com` |
| DeepSeek | `api.deepseek.com` |
| Doubao / Ark | `ark.cn-beijing.volces.com` (and other official volcengine subdomains) |
| Gemini | `generativelanguage.googleapis.com` |
| OpenRouter | `openrouter.ai` |
| SiliconFlow | `api.siliconflow.cn` |
| Qwen / DashScope | `dashscope.aliyuncs.com` |
| Groq | `api.groq.com` |
| Mistral | `api.mistral.ai` |

### 14.2 SSRF Reject Patterns (always enforced)

| Pattern | Reject reason |
|---|---|
| `http://*` for non-loopback | scheme not HTTPS |
| `http://127.0.0.1` / `http://localhost` / `http://[::1]` | loopback (unless `local_gateway_enabled` mode, deferred) |
| `http://169.254.*` | link-local / metadata |
| `http://10.*` / `172.16-31.*` / `192.168.*` | private RFC1918 |
| `http://0.0.0.0` | invalid bind |
| URL with userinfo (`user:pass@host`) | reject |
| URL with query / fragment | reject (base_url must be path-only) |
| DNS resolves to private/reserved/loopback IP | reject (DNS rebinding defense) |
| HTTP redirect during test | reject (`follow_redirects=False`) |

### 14.3 Required SSRF Test Cases

(must be present in `tests/test_provider_endpoint_policy.py`)

| Case | Expected |
|---|---|
| `http://127.0.0.1:8000` | reject loopback |
| `http://localhost:11434` | reject loopback |
| `http://[::1]:8000` | reject loopback |
| `http://169.254.169.254/latest/meta-data` | reject link-local |
| `http://10.0.0.1` | reject private |
| `http://172.16.0.1` | reject private |
| `http://192.168.1.1` | reject private |
| `http://0.0.0.0` | reject invalid |
| `http://attacker.example.com` claiming OpenAI | reject host mismatch |
| HTTPS allowlisted host resolving to private IP via mocked DNS | reject (rebinding) |
| Provider response 302 → private URL | reject (`follow_redirects=False`) |
| Valid known provider host | network test allowed; errors masked |
| `https://api.openai.com/v1/?api-version=preview` | reject (query/fragment) |
| `https://user:pass@api.openai.com` | reject (userinfo) |

---

## 15. Release Gate Tooling

### 15.1 Tools

| Tool | Role | Reason |
|---|---|---|
| `detect-secrets` (Yelp) | Primary secret scanner | Mature, pip-installable into `.venv-1`, plugin-based (KeywordDetector, HighEntropyString, AWS/GitHub/Slack/PrivateKey detectors) |
| Custom regex (`scripts/release_secret_scan.py`) | Project-specific token prefix backfill | Covers ARK / OpenAI / Anthropic / DeepSeek / SiliconFlow / Bearer / `*_API_KEY=` patterns the generic detector may miss |
| `trufflehog` / `gitleaks` | Optional CI deep scan | Not A0 mandatory |

### 15.2 Custom Regex Rules (high-confidence, fail on match)

```
(ARK|OPENAI|ANTHROPIC|DEEPSEEK|SILICONFLOW|DASHSCOPE|QWEN|MOONSHOT|GEMINI|GOOGLE|OPENROUTER|GROQ|MISTRAL|PERPLEXITY|MINIMAX|VOLCANO)_API_KEY\s*=\s*["']?[^"'\s]{12,}
Authorization\s*:\s*Bearer\s+[A-Za-z0-9._\-]{16,}
api[_-]?key\s*[:=]\s*["'][A-Za-z0-9._\-]{16,}["']
sk-[A-Za-z0-9._\-]{20,}
sk-ant-[A-Za-z0-9._\-]{20,}
volc-[A-Za-z0-9._\-]{12,}
sf-[A-Za-z0-9._\-]{16,}
AIza[0-9A-Za-z_\-]{20,}
```

### 15.3 Forbidden Path Rules

(applied to PyInstaller Analysis manifest AND final onedir tree)

```
.env
.env.*  (except .env.example)
**/runtime_state/**
**/runtime_credentials.json
**/credentials.json
**/key.txt
**/*.pem
**/*.key
**/id_rsa
**/id_ed25519
**/logs/**
**/chunk_store/**
**/_rejected/**   (forbidden inside payload roots; the metadata _rejected/ directory at workspace_artifacts/releases/_rejected/ is outside scan roots)
.secrets.baseline
```

### 15.4 Build Script Order (`scripts/build_windows_exe.ps1`)

```
1. Frontend build (npm run build)
2. PyInstaller Analysis manifest dump
   -> dump datas/binaries/source list to workspace_artifacts/releases/<version>/build-manifests/pyinstaller-analysis-datas.json
3. Forbidden-path scan on Analysis manifest
   -> fail closed; write redacted report to _rejected/<timestamp>.json; exit non-zero
4. PyInstaller full build (only if step 3 passes)
5. Forbidden-path scan on final onedir
   -> fail closed; write redacted report; exit non-zero
6. Bare secret scan on final onedir
   -> detect-secrets (no baseline) + custom regex
   -> any finding -> fail closed; redacted report; exit non-zero
7. Inno Setup .iss source declaration check
   -> verify all Source: clauses point only to onedir or known-safe roots
8. Inno Setup build installer
9. Frozen first-launch smoke
   -> launch built exe in clean %TEMP% subdir
   -> verify %APPDATA%\LiteratureAssistant\workspace_artifacts\runtime_state\credentials\ is empty
```

### 15.5 Failure Report Format

`workspace_artifacts/releases/_rejected/<timestamp>.json`:

```json
{
  "timestamp": "2026-05-08T...",
  "build_version": "0.1.1",
  "stage": "pyinstaller_analysis | onedir_forbidden_path | onedir_secret_scan | inno_source",
  "scan_root": "workspace_artifacts/releases/0.1.1/onedir/LiteratureAssistant/",
  "findings": [
    {
      "rule_id": "forbidden_path/runtime_state",
      "detector": "forbidden_path",
      "matched_path": "literature_assistant/workspace_artifacts/runtime_state/credentials/runtime_credentials.json",
      "masked_snippet": "<not_extracted>",
      "file_sha256_prefix": "ab12cd34",
      "severity": "blocker"
    }
  ]
}
```

No raw secret. No copied file content.

---

## 16. Slice A0 Implementation Status (2026-05-08)

### 16.1 Deliverables

| Task | File | Status |
|---|---|---|
| A0.1 runtime_state_path contract | tests/test_runtime_state_path_contract.py | done (5/5 tests passing) |
| A0.2 PyInstaller Analysis manifest dump | scripts/dump_pyinstaller_analysis.py | done |
| A0.3 forbidden-path scan (manifest + onedir) | scripts/release_forbidden_path_scan.py | done (smoke clean PASS, poisoned BLOCKED) |
| A0.4 release secret scan (NO baseline) | scripts/release_secret_scan.py | done (custom regex backfill verified) |
| A0.5 build_windows_exe.ps1 integration | scripts/build_windows_exe.ps1 | done (9-step pipeline) |
| A0.6 frozen first-launch storage check | scripts/smoke_frozen_first_launch.py | done |

### 16.2 Verification

- 28 targeted tests passed (contract + keypool + ai_adapter chat helper + ai_adapter pool).
- Smoke test on poisoned manifest BLOCKED with 6 findings (runtime_credentials.json + .env paths).
- Smoke test on poisoned payload BLOCKED with 5 findings (env_var_api_key, authorization_bearer, openai_sk_token, anthropic_sk_ant_token).
- detect-secrets installed in  at version 1.5.0.

### 16.3 Implementation caveats (folded back into Plan)

- A0.2 captures **Analysis input args** (datas/binaries/hiddenimports/pathex/runtime_hooks/Tree roots), not the full  after PyInstaller's hook resolution. Reason: full Analysis exec requires extensive PyInstaller CONF state; running it cleanly is brittle. Hook-injected datas are caught by the **mandatory final onedir scan (constraint #8)** as the actual fact gate.
- A0.6 launches the exe headless and probes 8 seconds; this is a **storage-isolation smoke**, not a full E2E. Inadequate for verifying SPA / WebSocket flows; those belong to a later release-readiness slice.
- Build script  is a full rewrite (preserved original behavior + 4 release gates). Original 87-line script grew to 165 lines, all gates fail-closed.

### 16.4 Open before Slice A1

- detect-secrets needs to be added to dev-requirements / install instructions. Currently installed ad-hoc in .
- The build script assumes  is present; conditional via  for environments without a freshly built exe.
-  directory is created on demand by the gate scripts; first build will populate it.
