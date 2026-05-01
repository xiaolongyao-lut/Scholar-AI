# Phase F Recovery Hardening Prompt (English)

```text
You are the Staff-level engineer responsible for hardening Harness V2 Phase F so that the Recovery Console becomes actually integrated and truthfully production-ready.

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is not a greenfield task.
Do not redesign the whole system.
Do not rewrite previous phases.
Do not inflate completion claims.
Your task is to reconcile the current Phase F implementation with the repository's real contracts, real storage behavior, and real validation results.

You must read these files before changing any code:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\canonical_event_store.py
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\harness_canonical_events.py
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_console.py
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_INTEGRATED_AI_MEMORY_PLAN.md
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_REQUIREMENTS_AND_CHECKLIST_EN.md

You must create a rollback snapshot before implementation.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-f-recovery-hardening-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

You must compare the implementation against mature external patterns before editing.
Review these official or primary references first:
- LangGraph Memory: https://docs.langchain.com/oss/python/langgraph/memory
- Zep Temporal Knowledge Graph paper: https://blog.getzep.com/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf
- Temporal Docs: https://docs.temporal.io/

Repository-specific design conclusions from those references:
- From LangGraph: session-scoped execution state and durable long-term memory must remain separate and explicitly scoped.
- From Zep/Graphiti: temporal facts need explicit validity windows, source traceability, and correct invalidation semantics.
- From Temporal: replay and recovery claims must be backed by durable event history and executable recovery paths, not just enums or placeholder records.

Current verified problems that must be fixed:

Problem 1: Memory snapshot is not reading real facts correctly
- recovery_console.py currently calls fact_store.get_current_facts("*")
- memory_fact_store.py currently implements exact namespace matching only
- real smoke validation shows a recorded fact is not returned by inspect_memory_state()
- fix this either by:
  - adding an explicit all-namespaces query to MemoryFactStore, or
  - changing RecoveryConsole to enumerate namespaces safely and aggregate results
- do not use fake wildcard semantics unless the store contract supports them explicitly

Problem 2: Fact invalidation is broken against the real TemporalFact model
- recovery_console.py uses target_fact.object_value
- TemporalFact actually exposes the field as object
- recovery_console.py calls fact_store.invalidate_fact(...)
- memory_fact_store.py currently does not implement invalidate_fact()
- fix the contract mismatch and add a real invalidation method in MemoryFactStore
- invalidation must preserve temporal semantics by closing the active fact window with valid_to

Problem 3: Replay and rehydrate are only declared, not operational
- RecoveryActionType contains REPLAY_JOB and REHYDRATE_RUNTIME
- the code currently only creates RecoveryAction records
- there is no executable replay or rehydrate path
- implement one of these two acceptable outcomes:
  1. preferred: add real replay/rehydrate execution support backed by canonical event history and runtime restore logic
  2. fallback: narrow the claims in docs and API so the system only exposes actions that truly exist
- do not keep production-ready claims that exceed the implementation

Problem 4: Recovery API integration is incomplete
- python_adapter_server.py currently exposes memory endpoints
- recovery inspection, fact invalidation, replay, and rehydrate endpoints are not yet wired
- add stable API endpoints for the implemented recovery features
- preserve backward compatibility

Problem 5: Validation claims must match the actual repository
- do not claim 185/185 or 100 percent passing unless you actually verified the same scope
- current repository-wide pytest collection includes vendor and missing-module failures
- either:
  - make the relevant package imports resolvable, or
  - define an intentional test scope with explicit rationale
- the final report must state the actual command run and the actual count observed

Implementation requirements:

1. Recovery Console hardening
- Fix inspect_memory_state() so it can read current facts across namespaces
- Fix invalidate_fact() so it uses the real TemporalFact shape
- Add defensive guardrails for invalid namespace, missing fact, and invalid context inputs
- Keep frozen dataclasses

2. Temporal fact store completion
- Add invalidate_fact(fact_id: str, invalidated_at: datetime) -> bool or equivalent typed API
- Add all-namespaces query support if RecoveryConsole needs it
- Preserve source_event_id traceability
- Preserve current-fact and historical-fact queries

3. Recovery execution path
- If replay is implemented, it must be based on canonical event history and deterministic reconstruction
- If rehydrate is implemented, it must restore runtime state from persisted history rather than hand-built mutable patches
- If not implemented in this round, remove or narrow unsupported production claims

4. API integration
- Add endpoints only for features that truly work
- Suggested endpoints:
  - GET /recovery/events
  - GET /recovery/memory
  - POST /recovery/facts/invalidate
  - POST /recovery/runtime/rehydrate
  - POST /recovery/jobs/replay
- If replay or rehydrate remains partial, expose inspect-only endpoints first and explicitly defer execution endpoints

5. Test strategy
- Keep the existing unit tests
- Add real integration tests using the actual MemoryFactStore implementation
- Add at least one test that records a real fact and verifies RecoveryConsole.inspect_memory_state() returns it
- Add at least one test that invalidates a real fact and verifies it disappears from current facts while remaining in history
- Add API tests if you expose new endpoints
- Add regression coverage for any previous false-positive mock-only behavior

6. Documentation truthfulness
- Update delivery reports only after code and validation are real
- Any claim about replay, rehydrate, or production readiness must be backed by executed validation
- If the feature is inspect-only plus invalidation in this round, say that explicitly

Files you will likely modify:
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_console.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_memory_fact_store.py
- possibly a new dedicated integration test file for recovery-console real-path validation

Mandatory validation commands:

1. Compile validation
python -X utf8 -m py_compile .\recovery_console.py .\memory_fact_store.py .\python_adapter_server.py

2. Focused unit and integration validation
python -X utf8 -m unittest .\test_recovery_console.py .\test_memory_fact_store.py -v

3. Real smoke validation for the previously broken path
Use a real MemoryFactStore instance, record a fact, call RecoveryConsole.inspect_memory_state(), and confirm fact_count > 0.
Then invalidate that fact and confirm:
- it is absent from current facts
- it is still visible in fact history

4. Repository test-scope validation
If you run pytest collection, report the exact collected count and any collection errors.
Do not round, estimate, or normalize the numbers.

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Exact problems fixed
4. Files changed
5. Validation commands run
6. Actual outcomes
7. Remaining blockers
8. Precise status statement:
   - inspect-only complete
   - inspect plus invalidation complete
   - replay/rehydrate complete
   - not yet production-ready

Success criteria for this round:
- RecoveryConsole works against the real TemporalFact store contract
- memory snapshot returns real facts
- fact invalidation works and preserves history
- API only exposes features that actually exist
- validation claims are accurate
- no false "production-ready" claim remains unsupported
```
