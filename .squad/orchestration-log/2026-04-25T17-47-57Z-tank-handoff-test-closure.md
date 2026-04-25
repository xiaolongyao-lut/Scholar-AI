# Orchestration Log — Tank Handoff Test Closure (2026-04-25T17:47:57Z)

**Agent:** Tank (QA Engineer)  
**Role:** Handoff test contract closure  
**Timestamp:** 2026-04-25T17:47:57Z  
**Requester:** 小龙 姚

## Scope

Test contract closures for R1 (all-probes-fail semantics), E1 (no-key return contract), and E2 (batch size parameter contract).

## Outcomes

### R1: All-Probes-Fail Uses Static Provider Key Semantics

**Closure:** ✅ COMPLETED  
**Evidence:** `.squad/decisions/inbox/tank-probe-failure-regression.md`

- **Fact:** `resolve_rerank_config()` at probe all-fail selects provider static key, not probe-order first key
- **Test Added:** `tests/test_reranker.py::test_all_probes_fail_uses_static_provider_key_semantics`
- **Regression:** Uses dual-key scenario (`SILICONFLOW_API_KEY + RERANK_API_KEY`) to verify fallback selects siliconflow static key
- **Status:** Locked, no business logic change

### E1: No-Key Contract — Returns None, Not Raises

**Closure:** ✅ COMPLETED  
**Evidence:** `.squad/decisions/inbox/tank-embedding-no-key-contract.md`

- **Fact:** `resolve_embedding_config()` returns `(None, base_url, model)` when no embedding key exists; logs error but does not raise
- **Test Renamed:** `test_no_key_raises_clear_error` → `test_no_key_returns_none_api_key_contract`
- **File:** `tests/test_embedding_provider_resolution.py`
- **Status:** Behavior locked, contract verified

### E2: Batch Size Parameter Contract

**Closure:** ✅ COMPLETED  
**Evidence:** `.squad/decisions/inbox/tank-embedding-batch-contract.md`

- **Fact:** `_batch_embed(batch_size=...)` argument is configurable; `EMBEDDING_BATCH_SIZE` env var is NOT wired
- **Test Renamed:** `test_embedding_batch_size_config` → `test_provider_limit_is_configurable_via_batch_size_arg`
- **Gap Test Added:** `test_embedding_batch_size_env_override_gap` with `xfail(strict=True)` — reason: env var not wired
- **File:** `tests/test_embedding_batch_chunking.py`
- **Plan Update:** `.copilot-tracking/plans/2026-04-25-embedding-rerank-test-handoff.md` (marked E2 partial)
- **Status:** Parameter contract locked; env contract gap tracked

## Decision Inbox Files

Three closure records merged from inbox to `decisions.md`:
- `tank-probe-failure-regression.md`
- `tank-embedding-no-key-contract.md`
- `tank-embedding-batch-contract.md`

## Next Steps (Coordinator)

1. Mark R1/E1/E2 todo slices complete
2. Launch Morpheus for fresh plan resweep after closures
3. Update handoff plan summary

---

**Orchestration Log Signature:** Scribe (2026-04-25T17:47:57Z)
