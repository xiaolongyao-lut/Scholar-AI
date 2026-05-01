# Phase H1 Memory Evidence Prompt (English)

```text
You are the Staff-level engineer responsible for the next precision step after Phase H1 integration hardening.

Reference date:
April 10, 2026

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is not Phase H2.
This is not observability work.
This is not a broad redesign.

This round is Phase H1.1: turn the existing optional MemPalace integration path into real recommendation evidence.

Current verified repository reality:
- `/recovery/recommendations` now uses real canonical events and real temporal facts.
- real seeded route tests prove non-empty, evidence-backed recommendations on the event/fact path.
- recommendation generation emits `recommendation.generated` audit events.
- `memory_adapter` and `policy_engine` are now wired into the route and engine constructor.
- but the engine still does not yet prove a real MemPalace-backed evidence path in recommendation output.

Your job in this round:
Make recovery recommendations truly AI-memory-aware by consulting the existing `MempalaceMemoryAdapter.search(...)` path, converting returned hits into typed evidence, and proving that behavior through real tests.

Do not broaden scope beyond memory evidence integration.
Do not start H2 metrics, dashboards, or tracing in this round.
Do not let memory evidence override current event/fact truth.

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_recommendation_engine.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_policy.py
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\layers\m_layer_mempalace_memory.py
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\main_rag_workflow.py
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_recommendation_engine.py
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_routes_real.py
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H1_IMPLEMENTATION_REPORT.md
9. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H1_INTEGRATION_HARDENING_COMPLETION.md

You must create a rollback snapshot before any code or documentation change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h1-memory-evidence-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

At minimum, back up:
- `recovery_recommendation_engine.py`
- `python_adapter_server.py`
- `layers/m_layer_mempalace_memory.py`
- test files you will modify
- H1 report files you will update

You must review mature official or primary-source references before implementation.
Review these sources first:
1. LangGraph Memory Overview: https://docs.langchain.com/oss/python/langgraph/memory
2. LangGraph Add Memory: https://docs.langchain.com/oss/python/langgraph/add-memory
3. Zep Facts: https://help.getzep.com/facts
4. FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
5. Temporal Docs: https://docs.temporal.io/

Repository-specific takeaways you must apply:
- from LangGraph: long-term memory should be explicitly scoped and retrieved deliberately, not sprayed into every path
- from Zep: facts remain the source for time-sensitive state; memory evidence should enrich recommendations, not replace fact truth
- from Temporal: recommendation reasoning must remain reconstructable from real execution history
- from FastAPI: route behavior must be proven with real app tests, not only model-level tests

Architectural laws you must not violate:
- do not let MemPalace overwrite current fact truth
- do not populate `memory_hit_ids` unless actual memory hits were consulted
- do not fabricate memory evidence when MemPalace is unavailable
- do not execute recovery actions automatically
- do not break the current event/fact-grounded recommendation path

Required implementation outcomes:

Outcome 1: use the real MemPalace adapter
- call `MempalaceMemoryAdapter.search(...)` from the recommendation engine when memory lookup is appropriate
- reuse the existing adapter and typed response models:
  - `MemorySearchResponse`
  - `MemorySearchHit`
- keep graceful degradation if MemPalace is disabled or unavailable

Outcome 2: add scoped memory-query construction
- derive a bounded memory query from the current recovery context:
  - failed event types
  - error payload details
  - job ID / session ID
  - relevant fact predicates or values
- do not perform unbounded memory search across unrelated scopes
- if the repository already has a project wing/default wing, use it intentionally

Outcome 3: convert memory hits into first-class evidence
- map `MemorySearchHit` records into `EvidenceReference(source_type="memory", ...)`
- populate `memory_hit_ids` with stable identifiers derived from the real hit data
- include enough detail for operator traceability, such as:
  - source file
  - wing
  - room
  - similarity
- do not duplicate memory text blindly into rationale if it is not needed

Outcome 4: make policy usage real
- use the policy engine, if available, to gate whether memory lookup should happen for a given request or failure shape
- if policy engine is unavailable, degrade truthfully without breaking the recommendation path
- document the exact gating rule implemented

Outcome 5: prove memory evidence through tests
- add at least one unit test where a fake or stub memory adapter returns real `MemorySearchHit` data and the engine includes:
  - `source_type="memory"` evidence
  - non-empty `memory_hit_ids`
- add at least one route/integration test that patches `get_memory_adapter()` to return a deterministic adapter result and proves:
  - the response still succeeds
  - a recommendation contains memory evidence or memory-backed alternative evidence
- keep the existing event/fact seeded test green

Outcome 6: update H1 documentation truthfully
- if memory evidence is now truly proven, say so explicitly and narrowly
- if only the engine path is proven but not full live MemPalace environment behavior, state that exact scope
- do not leave the report saying merely "optional memory integration" if you have now proven actual memory evidence

Preferred implementation sequence:

Stage 1: inspect current memory adapter surfaces
- inspect `MempalaceMemoryAdapter.search(...)`
- inspect `MemorySearchHit` and `MemorySearchResponse`
- inspect how `main_rag_workflow.py` currently uses memory hits

Stage 2: integrate memory retrieval into recommendation generation
- decide when to call memory search
- derive a bounded query
- merge memory evidence with event/fact evidence without collapsing them

Stage 3: add tests
- unit tests for engine-level memory evidence
- real route tests for API-level memory evidence

Stage 4: documentation and validation
- update H1 report wording
- report exact scope of memory-evidence proof

Non-negotiable validation expectations:
- at least one recommendation path must contain `source_type="memory"` evidence from a real adapter result or deterministic adapter stub
- `memory_hit_ids` must remain empty when memory was not consulted
- event/fact-only recommendations must still work exactly as before

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h1-memory-evidence-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://docs.langchain.com/oss/python/langgraph/memory
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://help.getzep.com/facts
- https://fastapi.tiangolo.com/tutorial/testing/
- https://docs.temporal.io/

3. Compile validation
.\.venv-1\Scripts\python.exe -X utf8 -m py_compile .\recovery_recommendation_engine.py .\python_adapter_server.py .\layers\m_layer_mempalace_memory.py

4. H1 recommendation validation
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_recommendation_engine.py .\test_recovery_api_routes_real.py -q

5. Regression guard
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_console.py .\test_recovery_console_hardening.py .\test_recovery_execution_engine.py .\test_memory_fact_store.py .\test_memory_policy.py -q

6. Repository collection truth check
.\.venv-1\Scripts\python.exe -X utf8 -m pytest --collect-only -q

7. Real memory-evidence smoke path
Run at least one scenario where:
- event/fact data exists
- the memory adapter returns deterministic hits
- the recommendation response contains memory evidence and non-empty `memory_hit_ids`

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Exact memory-evidence query strategy implemented
4. Exact files changed
5. Validation commands actually run
6. Actual results
7. Whether full MemPalace live-environment proof or deterministic-adapter proof was achieved
8. Updated H1 status wording

Success criteria for this round:
- recommendations can include real memory evidence from `MempalaceMemoryAdapter.search(...)`
- `memory_hit_ids` and `EvidenceReference(source_type="memory")` are populated truthfully
- route tests prove memory evidence behavior
- H1 documentation accurately reflects the new proof level
```
