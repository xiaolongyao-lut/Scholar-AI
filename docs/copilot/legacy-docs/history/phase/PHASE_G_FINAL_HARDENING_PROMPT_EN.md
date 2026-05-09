# Phase G Final Hardening Prompt (English)

```text
You are the Staff-level engineer responsible for closing the final credibility and reproducibility gaps in Harness V2 Phase G.

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

This is not a feature-expansion task.
This is the final hardening pass that must turn "production-close" into "reproducible, defensible, and accurately documented".

You must preserve the current Harness V2 architecture.
You must preserve the current recovery core implementation.
You must not overclaim readiness.
You must not rewrite unrelated parts of the repository.

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\python_adapter_server.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\requirements-ci.txt
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_adapter_import.py
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_recovery_api_routes_real.py
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\verify_production_readiness.py
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_PRODUCTION_READINESS_REPORT.md
8. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PRODUCTION_READINESS_VALIDATION_REPORT.md

You must create a rollback snapshot before any code change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-final-hardening-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

You must review mature official references before implementation:
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
- FastAPI Bigger Applications / APIRouter: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- pytest docs for import behavior and collection hygiene: https://docs.pytest.org/en/stable/
- Python Packaging guidance for reproducible environments: https://packaging.python.org/

Repository-specific takeaways from those references:
- FastAPI route correctness must be proven with the real `TestClient` against the real app.
- pytest-discovered test modules must not terminate the interpreter during import; test helper scripts must not call `sys.exit()` at import time.
- environment readiness claims are only credible if the documented or default project environment can reproduce them.
- dependency declarations must match the environment required to run the supported application surface.

Current verified repository reality:
- In `.venv-1`, adapter import succeeds and the real recovery route tests pass.
- The focused recovery suite can pass at 198 tests in `.venv-1`.
- In `.venv`, `python_adapter_server` still fails because `fastapi` is missing.
- Full repository-wide `pytest --collect-only -q` still fails, including because `test_adapter_import.py` exits during collection.
- `PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md` still contains stale or inaccurate statements.

Critical gaps that must be closed:

Gap 1: Environment reproducibility mismatch
- The validation success currently depends on `.venv-1`
- The project also contains `.venv`, where adapter import still fails
- You must choose and implement one coherent strategy:
  1. preferred: make the primary project environment reproducible by declaring and installing the required dependencies consistently
  2. fallback: explicitly document `.venv-1` as the supported verification environment and explain why
- Do not leave the repository in a state where production-readiness depends on an undocumented alternate virtual environment

Gap 2: Dependency declaration drift
- requirements-ci.txt currently does not clearly declare the FastAPI runtime stack required by the adapter
- Align dependency declarations with the supported verification environment
- Include whatever is required for:
  - `fastapi`
  - `uvicorn`
  - `pydantic`
  - `httpx` or equivalent if needed for `TestClient`

Gap 3: pytest collection hygiene
- `test_adapter_import.py` currently calls `sys.exit()` at module import time
- This causes repository-wide collection to blow up under pytest
- Convert it into a proper test module or helper that does not exit during import
- Follow pytest-compatible structure:
  - test functions should assert outcomes
  - command-line behavior should be guarded under `if __name__ == "__main__":`

Gap 4: Documentation truthfulness
- `PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md` still reports stale date and stale scope
- It still references files that are not the actual deployed integration points
- It still reports outdated test counts
- Update it so that it matches the current codebase, current environment story, and current validation scope

Gap 5: Production-readiness wording
- Do not claim "READY FOR PRODUCTION DEPLOYMENT" unless the supported environment, adapter import, route tests, and declared dependencies are all aligned
- If full-repo collection is still not green, say so clearly and explain the supported production scope

Implementation requirements:

1. Environment alignment
- Decide which environment is the supported one
- Make the dependency declaration reflect it
- Ensure the validation scripts use the supported environment intentionally, not accidentally

2. Adapter import reproducibility
- Ensure `python_adapter_server` can import in the supported environment
- Keep optional dependency handling for non-recovery subsystems where appropriate
- Keep the recovery API bootable without requiring unrelated subsystems to be fully present

3. Test hygiene repair
- Refactor `test_adapter_import.py` into pytest-safe structure
- Keep the adapter import verification, but remove import-time `sys.exit()`
- Ensure `pytest --collect-only -q` no longer fails because of this file

4. Documentation repair
- Update all production-readiness docs with:
  - exact current date
  - exact test scope
  - exact supported environment
  - accurate file references
  - accurate production-readiness statement

5. Validation script repair
- Ensure `verify_production_readiness.py` does not silently depend on an undocumented environment choice
- If it prefers `.venv-1`, document it explicitly
- If the repository standard should be `.venv`, then make it use `.venv`

Files you will likely modify:
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\requirements-ci.txt
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_adapter_import.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\verify_production_readiness.py
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
- possibly one or more additional production-readiness report files

Non-negotiable engineering constraints:
- Keep complete type hints on modified public Python code
- Add concise public docstrings where appropriate
- Do not remove the recovery functionality that already works
- Do not hide failures by narrowing test scope silently
- If you intentionally scope validation, document the scope explicitly

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-final-hardening-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://fastapi.tiangolo.com/tutorial/testing/
- https://fastapi.tiangolo.com/tutorial/bigger-applications/
- https://docs.pytest.org/en/stable/
- https://packaging.python.org/

3. Dependency verification in the supported environment
python -m pip show fastapi uvicorn pydantic

4. Compile validation
python -X utf8 -m py_compile .\python_adapter_server.py .\test_adapter_import.py .\verify_production_readiness.py

5. Adapter import validation
python -X utf8 -c "import python_adapter_server; print('adapter import ok')"

6. Real route validation
python -X utf8 -m pytest .\test_recovery_api_routes_real.py -q

7. Focused recovery validation
python -X utf8 -m pytest .\test_canonical_event_store.py .\test_canonical_events.py .\test_event_integration_layer.py .\test_harness_phase1.py .\test_harness_store.py .\test_memory_fact_store.py .\test_memory_policy.py .\test_recovery_api_endpoints.py .\test_recovery_console_hardening.py .\test_recovery_console.py .\test_recovery_execution_engine.py .\test_recovery_api_routes_real.py -q

8. Repository collection truth check
python -X utf8 -m pytest --collect-only -q

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Supported environment chosen and why
4. Dependency declaration changes
5. Files changed
6. Validation commands actually run
7. Actual outcomes, including remaining failures if any
8. Final status split into:
   - recovery core status
   - adapter startup status
   - route-test status
   - supported-environment status
   - full-repository status

Success criteria for this round:
- The supported environment is explicit and reproducible
- Dependency declarations match the supported environment
- `test_adapter_import.py` is pytest-safe
- recovery adapter import works in the supported environment
- real route tests remain green
- Phase G documentation no longer overstates or misstates the repository state
```
