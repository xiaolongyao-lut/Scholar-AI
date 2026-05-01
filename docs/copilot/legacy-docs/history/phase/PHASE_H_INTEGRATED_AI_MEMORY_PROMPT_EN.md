# Phase H Integrated AI Memory Prompt (English)

```text
You are the Staff-level engineer responsible for starting Harness V2 Phase H after Phase G production readiness and final documentation polish are complete.

Reference date:
April 10, 2026

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is not a generic "AI agent integration" task.
This is not a one-phase vanity milestone.
The current `PHASE_H_ROADMAP.md` is too generic, date-stale, and not sufficiently grounded in the repository's actual Harness + AI memory architecture.

Your job in this round has exactly two required outcomes:

Outcome A: Rewrite `PHASE_H_ROADMAP.md` into a truthful, repository-grounded, multi-phase Phase H roadmap.
Outcome B: Implement Phase H1 only.

Do not claim that all of Phase H is complete in this round.
Do not silently skip the roadmap rewrite.
Do not ignore the existing AI memory code that already ships in this repository.

Current verified repository baseline you must treat as true unless you re-validate and prove otherwise:
- Harness V2 Layers 1-6 are already operational through Phase G.
- Recovery core validation is green at 198/198 focused tests in `.venv-1`.
- Repository-wide `pytest --collect-only -q` succeeds at 353 collected tests.
- Recovery inspection, fact invalidation, runtime rehydrate, and recovery API surfaces already exist.
- MemPalace integration already exists for project wake-up and durable project memory.
- Temporal fact storage, memory policy, and memory-aware planning already exist in local code.
- `PHASE_H_ROADMAP.md` still contains outdated quarter-based planning language such as Q2 2025 and Q1 2026 and must be re-based to the post-Phase-G architecture reality.

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H_ROADMAP.md
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_INTEGRATED_AI_MEMORY_PLAN.md
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_AI_MEMORY_UPGRADE_ROADMAP.md
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_MASTER_IMPLEMENTATION_PROMPT_EN.md
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_AF_COMPLETE_STATUS.md
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_HARDENING_REPORT.md
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
9. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_execution_engine.py
10. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_policy.py
11. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
12. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_aware_planner.py
13. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\canonical_event_store.py
14. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\event_integration_layer.py
15. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\layers\m_layer_mempalace_memory.py
16. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
17. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\writing_runtime.py
18. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\main_rag_workflow.py
19. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_routes_real.py
20. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_memory_fact_store.py
21. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_memory_policy.py
22. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_memory_aware_planner.py

You must create a rollback snapshot before any code or documentation change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h-integrated-ai-memory-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

At minimum, back up:
- `PHASE_H_ROADMAP.md`
- every Python file you expect to modify
- every test file you expect to modify
- every report or prompt document you expect to update

You must review mature official or primary-source references before implementation.
Review these sources first:
1. LangGraph Memory Overview: https://docs.langchain.com/oss/python/langgraph/memory
2. LangGraph Add Memory: https://docs.langchain.com/oss/python/langgraph/add-memory
3. Zep Graphiti Overview: https://help.getzep.com/graphiti/getting-started/overview
4. Zep Facts: https://help.getzep.com/facts
5. Temporal Docs home: https://docs.temporal.io/
6. OpenTelemetry Python Instrumentation: https://opentelemetry.io/docs/languages/python/instrumentation/
7. Prometheus Instrumentation Practices: https://prometheus.io/docs/practices/instrumentation/
8. FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/

Repository-specific takeaways you must apply from those references:
- From LangGraph:
  - short-term execution state and long-term memory must remain explicitly separated
  - long-term memory must use clear namespaces
  - memory writes may happen on the hot path or in the background, and that tradeoff must be explicit
- From Zep Graphiti:
  - temporal facts need validity windows and invalidation semantics
  - dynamic agent memory should preserve provenance and support point-in-time reasoning
  - summaries alone are not enough for grounding when precise facts exist
- From Temporal:
  - durable behavior must be reconstructable from history, not from ad hoc mutable flags
  - recovery reasoning should be explainable from a concrete execution history
- From OpenTelemetry:
  - if you add observability for Phase H, instrument spans and metrics in a way that works both in app code and library code
  - traces should make recommendation generation and operator action paths inspectable
- From Prometheus:
  - metrics should focus on errors, latency, counts, and in-progress state
  - avoid high-cardinality labels and per-entity metric explosions
- From FastAPI:
  - if you expose new recommendation endpoints, prove them against the real app with real route tests

Architectural laws you must not violate:
- Do not break completed Phases A-G.
- Do not remove or weaken current recovery inspection and recovery execution functionality.
- Do not let AI memory overwrite resource truth.
- Do not merge audit logs, short-term runtime state, long-term project memory, and temporal facts into one undifferentiated store.
- Do not execute recovery actions autonomously in this round.
- Do not fake "AI reasoning" by hardcoding canned strings without linking them to actual repository data sources.
- Do not write raw artifacts or raw tool chatter into MemPalace by default.
- Do not introduce TODO placeholders.
- All new or modified public Python code must keep full type hints, defensive guardrails, and concise public docstrings.

Phase H must be re-based into a concrete multi-phase plan that reflects this repository.
Your rewritten `PHASE_H_ROADMAP.md` must define at least these five sub-phases:

Phase H1: Memory-Grounded Recovery Advisor
Phase H2: Observability and Evaluation Harness
Phase H3: Safe Operator Workflow and CLI
Phase H4: Guarded Autopilot Recovery
Phase H5: Scale-out, tenancy, and deployment hardening foundations

You may add a sixth phase if truly needed, but do not collapse the roadmap back into one vague AI phase.

For each Phase H sub-phase in the rewritten roadmap, you must include:
- objective
- why it matters specifically in this repository
- core files likely involved
- key dependencies on previous phases
- acceptance criteria
- explicit out-of-scope items
- risk notes

This implementation round is Phase H1 only.
You must plan H2-H5, but you must not implement them yet.

Phase H1 objective:
Build a Memory-Grounded Recovery Advisor that can analyze canonical events, temporal facts, and durable project memory to generate typed recovery recommendations for operators.

Phase H1 must be recommendation-only.
It may suggest actions.
It must not execute actions automatically.

Phase H1 functional requirements:

1. Add a typed recommendation engine
- Create `recovery_recommendation_engine.py` or an equivalent clearly named module.
- The engine must consume:
  - canonical event timeline data
  - current temporal facts
  - optionally relevant historical facts
  - durable project memory hits from MemPalace or its adapter layer
  - current recovery context such as session ID, job ID, namespace, and execution state
- The engine must produce ranked recovery recommendations with:
  - recommendation ID
  - job ID or target aggregate
  - recommendation type
  - rationale
  - confidence
  - required approval level
  - dry-run preview or expected effect summary
  - source references back to event IDs, fact IDs, memory records, or resource identifiers

2. Keep the contract deterministic and inspectable
- The same input set should yield reproducible recommendation structure.
- Recommendation output must be serializable and auditable.
- Do not hide source evidence in freeform prose only.

3. Integrate with the current recovery stack
- Reuse `recovery_console.py`, `memory_fact_store.py`, `canonical_event_store.py`, and the existing memory adapter instead of inventing parallel infrastructure.
- If necessary, add a clean orchestration method in `recovery_console.py` that delegates to the recommendation engine.
- Keep the API boundary coherent with the current recovery API surface in `python_adapter_server.py`.

4. Expose safe API access
- Add recommendation inspection endpoint(s) under a recovery namespace such as `/recovery/recommendations`.
- Recommended minimum operations:
  - read/generate recommendations for a job or aggregate
  - inspect the evidence used to produce a recommendation
- If you add a recompute endpoint, it must be explicit and operator-triggered.

5. Record advisory behavior
- Recommendation generation must leave an auditable trace.
- Prefer canonical or recovery audit events such as:
  - recommendation.generated
  - recommendation.recomputed
- Do not treat a recommendation as an executed recovery action.

6. Respect memory boundaries
- Resource truth still comes from resource/current-state stores.
- Temporal facts remain the place for time-scoped facts.
- MemPalace remains long-term project memory.
- The advisor may use long-term memory to improve recommendation quality, but not to overwrite current truth.

7. Add tests first or alongside implementation
- Add or update tests for:
  - recommendation ranking and structure
  - evidence/source-link generation
  - fact-aware recommendation changes after invalidation
  - API route behavior using the real FastAPI app
  - at least one smoke path that seeds facts/events/memory and verifies a recommendation comes back

Files you will likely modify in Phase H1:
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H_ROADMAP.md
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\layers\m_layer_mempalace_memory.py
- one new recommendation engine module
- one or more new test files such as `test_recovery_recommendation_engine.py`
- possibly `test_recovery_api_routes_real.py`

Preferred implementation sequence:

Stage 1: Snapshot and source review
- Create rollback snapshot
- Read all required local files
- Review the mature references above
- Write down repository-specific takeaways before coding

Stage 2: Roadmap rebase
- Rewrite `PHASE_H_ROADMAP.md` into a truthful multi-phase plan
- Remove outdated quarter-based claims if they no longer match reality
- Make the roadmap explicitly post-Phase-G and AI-memory-aware

Stage 3: H1 contracts and tests
- Define typed recommendation models
- Add route tests and engine tests
- Add defensive validation on input parameters

Stage 4: H1 implementation
- Build the recommendation engine
- Integrate with recovery console
- Expose safe API access
- Emit advisory audit/history records

Stage 5: Validation and truth update
- Run compile, tests, and at least one real smoke path
- If any part of H1 remains incomplete, report it precisely
- Do not claim H2-H5 progress beyond roadmap/spec updates

Recommended H1 data model characteristics:
- recommendations should be immutable or treated as immutable result objects
- confidence must be bounded and typed
- evidence should be a first-class typed list, not just prose
- recommendation type should be an enum or similarly constrained value
- operator-facing text should be concise and machine-checkable where possible

Non-negotiable guardrails for H1:
- no autonomous execution
- no speculative fact mutation
- no silent fact invalidation
- no unbounded memory retrieval across unrelated namespaces
- no recommendation without evidence references
- no new API that bypasses the current recovery/recovery-console abstraction without a strong reason

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-h-integrated-ai-memory-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://docs.langchain.com/oss/python/langgraph/memory
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://help.getzep.com/graphiti/getting-started/overview
- https://help.getzep.com/facts
- https://docs.temporal.io/
- https://opentelemetry.io/docs/languages/python/instrumentation/
- https://prometheus.io/docs/practices/instrumentation/
- https://fastapi.tiangolo.com/tutorial/testing/

3. Compile validation
.\.venv-1\Scripts\python.exe -X utf8 -m py_compile .\recovery_console.py .\python_adapter_server.py .\memory_fact_store.py .\memory_policy.py .\memory_aware_planner.py

4. New H1 recommendation tests
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_recommendation_engine.py -q

5. Real route validation
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_recovery_api_routes_real.py -q

6. Existing memory and recovery regression guard
.\.venv-1\Scripts\python.exe -X utf8 -m pytest .\test_memory_fact_store.py .\test_memory_policy.py .\test_memory_aware_planner.py .\test_recovery_console.py .\test_recovery_execution_engine.py -q

7. Repository collection truth check
.\.venv-1\Scripts\python.exe -X utf8 -m pytest --collect-only -q

8. Smoke path
Run at least one real seeded scenario where:
- a job/event history exists
- temporal facts exist
- at least one memory hit exists or is intentionally absent
- the system returns a typed recommendation with evidence references

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Repository-specific takeaways applied
4. Exact files changed
5. Exact Phase H roadmap breakdown written into `PHASE_H_ROADMAP.md`
6. Exact H1 functionality implemented
7. Validation commands actually run
8. Actual results
9. Residual risks
10. Explicit statement that H2-H5 were planned only, not implemented

Success criteria for this round:
- `PHASE_H_ROADMAP.md` becomes a truthful, multi-phase, AI-memory-aware roadmap
- Phase H is no longer described as one vague AI phase
- H1 delivers a typed recommendation engine grounded in events, facts, and memory
- recommendations are inspectable, evidence-backed, and non-autonomous
- recommendation API behavior is proven against the real FastAPI app
- existing recovery and memory functionality remains green
- final reporting is truthful about what was implemented vs only planned
```
