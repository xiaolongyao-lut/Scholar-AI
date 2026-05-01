# Phase G Production Readiness Prompt (English)

```text
You are the Staff-level engineer responsible for taking Harness V2 Phase G from "core recovery tests pass" to "truthful production-readiness".

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is a hardening and integration task, not a greenfield rewrite.
Do not redesign the repository.
Do not replace the Harness V2 architecture.
Do not claim production readiness unless the adapter process starts, the recovery routes execute successfully, and the validation scope is accurately reported.

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_execution_engine.py
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\memory_fact_store.py
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_endpoints.py
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_console.py
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_console_hardening.py
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_execution_engine.py
9. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
10. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_H_ROADMAP.md

You must create a rollback snapshot before any code change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-production-readiness-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

You must review mature official references before implementation.
Review these sources first:
- LangGraph Memory Overview: https://docs.langchain.com/oss/python/langgraph/memory
- LangGraph Add Memory: https://docs.langchain.com/oss/python/langgraph/add-memory
- Temporal Docs: https://docs.temporal.io/
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
- FastAPI Bigger Applications / APIRouter: https://fastapi.tiangolo.com/tutorial/bigger-applications/

Repository-specific takeaways from those references:
- From LangGraph: execution state and durable memory must remain explicitly separated and scoped.
- From Temporal: replay and recovery must be backed by executable history-based flows, not only metadata or enums.
- From FastAPI Testing: route behavior must be validated through a real TestClient against the actual app, not only through local payload-model mirrors.
- From FastAPI APIRouter guidance: recovery endpoints should be organized as a coherent router or integration block with a stable contract.

Current verified repository reality:
- The focused core recovery suite can pass at 186 tests.
- Recovery fact snapshotting and invalidation now work against the real MemoryFactStore.
- But adapter startup and route-level production readiness are still not proven.
- Full repository test collection is not green.

Critical problems that must be fixed or truthfully downgraded:

Problem 1: The adapter process is not currently startable in this environment
- python_adapter_server.py exits immediately if fastapi is missing.
- The current environment is missing fastapi even though uvicorn and pydantic are installed.
- python_adapter_server.py also imports integrated_pipeline, and the repository currently does not contain integrated_pipeline.py.
- You must either:
  1. make the adapter bootable in the supported environment, or
  2. narrow the production-ready claim and document the blocker precisely

Problem 2: Recovery endpoint contract mismatch
- python_adapter_server.py calls console.inspect_events(...)
- recovery_console.py exposes inspect_event_timeline(...)
- python_adapter_server.py expects timeline.start_time / timeline.end_time
- recovery_console.EventTimeline exposes earliest_timestamp / latest_timestamp
- python_adapter_server.py expects snapshot.facts / snapshot.last_updated
- recovery_console.MemorySnapshot exposes current_facts / timestamp
- You must align the server contract with the actual recovery models
- Prefer one clean typed contract, not compatibility hacks piled on top of each other

Problem 3: Recovery API tests are not real route tests yet
- test_recovery_api_endpoints.py currently defines local payload models to avoid importing the real app
- this does not prove that the FastAPI routes actually work
- replace or extend these tests with route-level tests using the real app and TestClient
- if startup dependencies are intentionally optional, structure the app so route tests can still run

Problem 4: Production-readiness reporting is overstated
- PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md currently overstates deployment completeness
- it references files that do not actually exist as deployed standalone modules
- it uses an incorrect date
- update all delivery documents so they describe the real repository and real validation scope

Problem 5: Full repository health is still below production-grade
- pytest --collect-only currently reports collection errors outside the focused core recovery suite
- do not claim "system fully ready for production deployment" unless you either:
  1. fix the collection failures that matter to deployment, or
  2. explicitly define a supported production scope and justify excluded areas

Implementation goals for this round:

1. Make the recovery API contract internally consistent
- Align endpoint handlers in python_adapter_server.py with recovery_console.py return models
- Use actual method names and actual field names
- Keep strict typing and defensive guardrails

2. Make the server app testable and preferably startable
- Install or declare required FastAPI runtime dependencies in the project environment and requirements if appropriate
- Resolve or guard the integrated_pipeline import so the recovery and runtime API can boot in a controlled way
- If integrated_pipeline is intentionally external, add a clear optional dependency boundary and startup behavior

3. Replace fake API tests with real route tests
- Use the real FastAPI application object
- Use TestClient according to the official FastAPI testing approach
- Add endpoint tests for:
  - GET /recovery/events
  - GET /recovery/memory
  - POST /recovery/facts/invalidate
- If replay or rehydrate endpoints are added or exposed, test them too

4. Validate actual startup and route behavior
- Prove that the adapter imports successfully
- Prove that the recovery endpoints respond with the expected schema and status code
- Prove at least one end-to-end route path using real recovery components or well-bounded integration fixtures

5. Make deployment reporting truthful
- Update Phase G docs only after validation succeeds
- Distinguish:
  - core recovery suite green
  - adapter startup green
  - recovery route integration green
  - full repository collection green or not green

Preferred implementation strategy:

Stage A: Snapshot and reference review
- Create rollback snapshot
- Read official references
- Read the listed repository files

Stage B: Contract repair
- Fix endpoint handler method calls and field mappings
- Ensure MemorySnapshot and EventTimeline are serialized correctly

Stage C: Startup boundary repair
- Resolve fastapi dependency handling
- Resolve integrated_pipeline import strategy
- Avoid making unrelated API areas worse

Stage D: Real API testing
- Replace model-only tests with TestClient tests against the real app
- Add route coverage for success and failure cases

Stage E: Truthful deployment report
- Update Phase G deployment summary with exact date, exact scope, exact validation
- If production readiness is still partial, say so clearly

Files you will likely modify:
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\recovery_console.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_endpoints.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\requirements-ci.txt
- possibly a small app-factory helper if needed for testability
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md

Non-negotiable engineering constraints:
- Preserve existing Harness V2 architectural separation
- Do not let AI memory become business truth
- Do not remove the current recovery core implementation
- Do not leave TODO placeholders
- Keep complete Python type hints on new or modified public code
- Add concise public docstrings
- Add defensive input validation on endpoint inputs and recovery actions

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-production-readiness-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://docs.langchain.com/oss/python/langgraph/memory
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://docs.temporal.io/
- https://fastapi.tiangolo.com/tutorial/testing/
- https://fastapi.tiangolo.com/tutorial/bigger-applications/

3. Compile validation
python -X utf8 -m py_compile .\python_adapter_server.py .\recovery_console.py .\recovery_execution_engine.py .\memory_fact_store.py

4. Focused recovery validation
python -X utf8 -m pytest -q .\test_canonical_event_store.py .\test_canonical_events.py .\test_event_integration_layer.py .\test_harness_phase1.py .\test_harness_store.py .\test_memory_fact_store.py .\test_memory_policy.py .\test_recovery_api_endpoints.py .\test_recovery_console_hardening.py .\test_recovery_console.py .\test_recovery_execution_engine.py

5. Real adapter import validation
python -X utf8 -c "import python_adapter_server; print('adapter import ok')"

6. Full collection truth check
python -X utf8 -m pytest --collect-only -q

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Exact repository problems fixed
4. Files changed
5. Validation commands actually run
6. Actual outcomes, including failures
7. Deployment status split into:
   - recovery core status
   - adapter startup status
   - recovery API route status
   - full repository status
8. Remaining blockers

Success criteria for this round:
- python_adapter_server recovery endpoints match the real recovery models
- recovery route tests hit the actual FastAPI app
- adapter startup is either working or the blocker is explicitly and truthfully documented
- deployment summary no longer overclaims
- validation scope is precise and reproducible
```
