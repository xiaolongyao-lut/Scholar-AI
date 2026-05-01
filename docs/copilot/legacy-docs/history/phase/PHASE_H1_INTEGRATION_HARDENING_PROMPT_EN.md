# Phase H1 Integration Hardening Prompt (English)

```text
You are the Staff-level engineer responsible for hardening Harness V2 Phase H1 so that the Memory-Grounded Recovery Advisor is truthfully integrated, not just structurally present.

Reference date:
April 10, 2026

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is not a new H2 task.
This is not a roadmap-writing round.
This is a precision hardening round for Phase H1.

Do not broaden scope.
Do not jump to H2 observability work.
Do not rewrite the architecture.
Do not claim H1 is fully complete until the recommendation path is wired to real repository data sources and produces evidence-backed results in a real seeded path.

Current verified repository reality:
- `recovery_recommendation_engine.py` exists.
- `test_recovery_recommendation_engine.py` exists and targeted H1 tests pass.
- `PHASE_H_ROADMAP.md` has been rewritten into H1-H5 phases.
- repository-wide `pytest --collect-only -q` succeeds at 372 collected tests.
- targeted H1 validation currently passes at 31 tests.

But the current H1 completion claim is overstated because of these verified integration gaps:

Gap 1: the FastAPI recommendation route is disconnected from real recovery data
- `python_adapter_server.py` currently creates `CanonicalEventStore(":memory:")` and `MemoryFactStore(":memory:")` inside `/recovery/recommendations`
- this means the route is not reading the real persisted event timeline or real fact state
- a live request currently returns `200` with:
  - `primary_recommendation: null`
  - `alternatives: []`
  - `total_evidence_considered: 0`

Gap 2: the recommendation engine calls methods that the real stores do not expose
- `_load_events()` calls `query_by_job_id`
- the real canonical event store exposes `get_job_timeline(...)`
- `_load_facts()` calls `query_by_subject`
- the real memory fact store exposes `get_current_facts(namespace, subject=...)` and `get_fact_timeline(...)`

Gap 3: AI memory is declared but not actually used
- `memory_adapter` is accepted by the engine constructor but not used to retrieve evidence
- `policy_engine` is accepted by the engine constructor but not used to shape or constrain recommendations
- no real MemPalace-backed evidence path is currently proven

Gap 4: recommendation generation is not audited through the existing recovery/canonical surfaces
- the implementation report claims `recommendation.generated` auditability
- but the current implementation does not yet prove that recommendation generation emits a durable event or recovery audit record

Gap 5: real route validation is too weak
- the route test currently allows `200` or `503`
- the success path mostly validates schema presence, not real evidence-backed recommendation behavior

Your job in this round:
Turn the current H1 implementation from "typed skeleton with endpoint" into a truthfully integrated recovery advisor that uses real event/fact/memory data and proves that integration through real tests.

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_recommendation_engine.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\canonical_event_store.py
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_policy.py
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\layers\m_layer_mempalace_memory.py
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_recommendation_engine.py
9. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_routes_real.py
10. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H1_IMPLEMENTATION_REPORT.md
11. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H_ROADMAP.md

You must create a rollback snapshot before any code or documentation change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h1-integration-hardening-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

At minimum, back up:
- `recovery_recommendation_engine.py`
- `python_adapter_server.py`
- `recovery_console.py`
- `canonical_event_store.py`
- `memory_fact_store.py`
- test files you will modify
- `PHASE_H1_IMPLEMENTATION_REPORT.md`

You must review mature official or primary-source references before implementation.
Review these sources first:
1. LangGraph Memory Overview: https://docs.langchain.com/oss/python/langgraph/memory
2. LangGraph Add Memory: https://docs.langchain.com/oss/python/langgraph/add-memory
3. Zep Facts: https://help.getzep.com/facts
4. Temporal Docs: https://docs.temporal.io/
5. FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
6. Prometheus Instrumentation Practices: https://prometheus.io/docs/practices/instrumentation/

Repository-specific takeaways you must apply:
- recommendations must be grounded in actual persisted state, not fresh empty in-memory stores
- short-term execution state, temporal facts, and long-term memory must remain separate but interoperable
- fact queries must respect current validity, provenance, and namespace boundaries
- route tests must prove real app behavior against real seeded stores
- recommendation generation must be inspectable and traceable

Architectural laws you must not violate:
- do not break Phases A-G
- do not let MemPalace overwrite resource truth
- do not execute recovery actions automatically
- do not bypass the recovery console abstraction without a strong reason
- do not fabricate evidence or synthetic "memory hits" when no real memory retrieval happened
- do not keep overstated H1 completion language if integration remains partial

Required implementation outcomes:

Outcome 1: wire the engine to real store contracts
- change event loading to use the real canonical event store API
- change fact loading to use the real memory fact store API
- if needed, add small adapter methods on the stores, but prefer using existing public methods
- remove reliance on nonexistent `query_by_job_id` and `query_by_subject`

Outcome 2: use real recovery integration points
- the FastAPI route must not instantiate fresh `:memory:` stores for normal operation
- use the repository's actual recovery console/store wiring or a clean factory/helper that returns the real configured instances
- if a special in-memory mode is only for tests, keep it explicitly test-only

Outcome 3: make memory evidence real
- if MemPalace integration is available, retrieve scoped memory hits through the existing memory adapter layer
- if MemPalace integration is unavailable, degrade truthfully and report zero memory evidence without pretending otherwise
- only populate `memory_hit_ids` when actual memory records were consulted

Outcome 4: make recommendation generation auditable
- emit a durable recovery or canonical audit record when recommendations are generated or recomputed
- recommended event names:
  - `recommendation.generated`
  - `recommendation.recomputed`
- the audit record must include enough metadata to understand:
  - target job/session
  - rule(s) applied
  - evidence counts
  - primary recommendation type

Outcome 5: strengthen route tests into real seeded integration tests
- add at least one test that seeds canonical job events and temporal facts into real stores and then calls `/recovery/recommendations`
- assert a non-empty recommendation response with:
  - non-null `primary_recommendation`
  - non-zero `total_evidence_considered`
  - at least one source event or source fact ID
- if memory is seeded and available, assert non-empty memory evidence too
- remove the weak success definition that treats an empty `200` response as sufficient proof of completion

Outcome 6: correct documentation truthfulness
- if the route is still partial after this round, downgrade the implementation report accordingly
- if the route becomes truly integrated, update `PHASE_H1_IMPLEMENTATION_REPORT.md` to reflect what is now actually proven
- do not claim "all evidence traced back to source event/fact/memory IDs" unless a real route test proves it

Preferred implementation sequence:

Stage 1: local audit and contract mapping
- map the current recommendation engine methods to the actual event/fact store APIs
- identify the cleanest existing recovery integration point

Stage 2: engine/store contract repair
- replace nonexistent store queries with real ones
- add defensive guards around empty or missing namespaces

Stage 3: route integration repair
- replace `:memory:` route-local store creation with real store wiring
- keep optional dependency handling where truly needed

Stage 4: memory and audit integration
- add real memory retrieval if available
- add auditable recommendation generation record

Stage 5: real seeded tests and documentation cleanup
- prove one or more evidence-backed recommendation scenarios through the actual FastAPI app
- update H1 documentation to match verified reality

Non-negotiable test expectations:
- at least one real seeded recommendation scenario must return a non-empty recommendation
- at least one scenario must show fact-aware behavior change after fact invalidation or state difference
- route tests must fail if recommendation integration regresses back to empty fake-store behavior

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h1-integration-hardening-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://docs.langchain.com/oss/python/langgraph/memory
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://help.getzep.com/facts
- https://docs.temporal.io/
- https://fastapi.tiangolo.com/tutorial/testing/
- https://prometheus.io/docs/practices/instrumentation/

3. Compile validation
.\.venv-1\Scripts\python.exe -X utf8 -m py_compile .\recovery_recommendation_engine.py .\python_adapter_server.py .\recovery_console.py

4. H1 unit and integration validation
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_recommendation_engine.py .\test_recovery_api_routes_real.py -q

5. Recovery regression guard
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_console.py .\test_recovery_console_hardening.py .\test_recovery_execution_engine.py .\test_memory_fact_store.py .\test_memory_policy.py -q

6. Repository collection truth check
.\.venv-1\Scripts\python.exe -X utf8 -m pytest --collect-only -q

7. Real smoke path
Run a real seeded scenario through the FastAPI app where:
- canonical events are persisted
- temporal facts are persisted
- the recommendation endpoint returns a non-empty evidence-backed recommendation
- the response contains actual source IDs and non-zero evidence count

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Exact integration gaps fixed
4. Exact files changed
5. Real seeded route scenario used for proof
6. Validation commands actually run
7. Actual results
8. Whether MemPalace evidence was truly integrated or truthfully deferred
9. Updated H1 status wording

Success criteria for this round:
- `/recovery/recommendations` uses real repository data sources, not fresh empty stores
- the engine uses real store APIs
- at least one real route test proves non-empty evidence-backed recommendations
- recommendation generation is auditable
- H1 documentation becomes fully defensible
- only after those are true may H1 be called complete
```
