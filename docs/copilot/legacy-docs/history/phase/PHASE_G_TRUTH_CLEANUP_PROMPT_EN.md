# Phase G Truth Cleanup Prompt (English)

```text
You are the Staff-level engineer responsible for the final truth-cleanup pass for Harness V2 Phase G.

Repository root:
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

Do not broaden scope.
Do not redesign the system.
Do not touch already-working recovery core logic unless a change is required for validation truthfulness.
This round is only about removing the last two credibility gaps:
1. repository-wide pytest collection still has one remaining collection error
2. the final Phase G deployment summary still contains stale or inaccurate file references and deployment instructions

You must read these files before editing:
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_skill_flow_adapter.py
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\skills
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_HARDENING_REPORT.md
5. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PRODUCTION_READINESS_VALIDATION_REPORT.md
6. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\verify_production_readiness.py
7. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_adapter_import.py

You must create a rollback snapshot before any code change.
Use this command pattern:

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-truth-cleanup-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

You must review mature official references before implementation:
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
- pytest documentation: https://docs.pytest.org/en/stable/
- pytest import skipping guidance: https://docs.pytest.org/en/stable/how-to/skipping.html

Repository-specific takeaways from those references:
- real FastAPI route behavior must be proven with the real TestClient against the real app
- pytest collection must not fail because of avoidable import-time module errors in test files
- if a test depends on an optional module or unfinished subsystem, that dependency must be handled explicitly and truthfully

Current verified repository reality:
- The focused recovery/core suite passes at 198 tests in `.venv-1`
- `test_adapter_import.py` is now pytest-safe
- full repository-wide `pytest --collect-only -q` still fails because `test_skill_flow_adapter.py` imports `skills.skill_flow_adapter`, which does not exist
- `PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md` still references nonexistent files such as `recovery_console_hardening.py` and `recovery_api_endpoints.py`
- the same summary still contains stale deployment snippets like copying nonexistent files and outdated expected test counts

Your objectives in this round:

Objective 1: Eliminate the remaining pytest collection error
- Investigate `test_skill_flow_adapter.py`
- Determine whether:
  1. `skills.skill_flow_adapter` should actually exist and needs to be implemented or restored, or
  2. the test targets a deprecated/nonexistent subsystem and should be rewritten, skipped explicitly, or moved out of the default collection path
- Preferred rule:
  - if the adapter is part of the intended supported surface, implement or restore it properly
  - if it is not part of the supported production scope, mark or structure the test truthfully so collection succeeds without pretending the module exists
- Do not hide the issue silently
- Do not leave import-time failures in the default repository collection

Objective 2: Make Phase G deployment summary fully truthful
- Update `PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md` so every referenced file actually exists
- Remove or replace references to:
  - `recovery_console_hardening.py`
  - `recovery_api_endpoints.py`
  - any copy/deploy command that references nonexistent files
- Update deployment snippets to use real integration points such as:
  - `recovery_console.py`
  - `recovery_execution_engine.py`
  - `python_adapter_server.py`
  - actual test files that exist
- Ensure test counts, scope, and environment wording match the current validated reality

Objective 3: Keep the status wording precise
- If full repository collection becomes clean, say so
- If collection still fails outside the supported scope, say exactly why and where
- If the supported scope remains "recovery framework in .venv-1", say that plainly
- Do not use generic phrases like "fully production-ready" unless the document also makes the scope explicit

Implementation requirements:

1. Resolve `test_skill_flow_adapter.py`
- read the test fully
- inspect the `skills` package to see whether an equivalent module exists under another name
- if implementation is needed, keep it minimal, typed, and aligned with the current skill model
- if explicit skipping is the correct action, use a pytest-native approach and document the rationale

2. Repair deployment summary
- correct file references
- correct deployment commands
- correct test-count references
- keep the environment statement explicit: `.venv-1` is the verified environment unless you intentionally change that

3. Keep reporting honest
- if you fix collection completely, report the exact collected count
- if not, report the exact remaining blockers

Files you will likely modify:
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\test_skill_flow_adapter.py
- possibly one or more files in C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\skills
- C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md
- possibly C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE_G_FINAL_HARDENING_REPORT.md if it repeats stale file names

Non-negotiable constraints:
- No TODO placeholders
- No silent narrowing of scope
- No fake file references in docs
- Keep type hints on new public Python code
- Use pytest-native patterns for skips or optional dependencies

Mandatory validation commands:

1. Rollback
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-g-truth-cleanup-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. Mature-solution review
Open:
- https://fastapi.tiangolo.com/tutorial/testing/
- https://docs.pytest.org/en/stable/
- https://docs.pytest.org/en/stable/how-to/skipping.html

3. Compile validation
python -X utf8 -m py_compile .\test_skill_flow_adapter.py .\test_adapter_import.py

4. Targeted validation for the previous collection failure
python -X utf8 -m pytest .\test_skill_flow_adapter.py -q

5. Recovery regression guard
python -X utf8 -m pytest .\test_recovery_api_routes_real.py .\test_adapter_import.py -q

6. Repository collection truth check
python -X utf8 -m pytest --collect-only -q

Mandatory final report contents:
1. Rollback snapshot path
2. Mature references reviewed
3. Exact fix chosen for `test_skill_flow_adapter.py`
4. Files changed
5. Validation commands run
6. Actual outcomes
7. Exact repository collection status after the fix
8. Exact wording recommendation for Phase G status

Success criteria for this round:
- repository-wide `pytest --collect-only -q` no longer fails because of `test_skill_flow_adapter.py`
- `PHASE_G_FINAL_DEPLOYMENT_SUMMARY.md` contains only real file references and real commands
- the Phase G status statement becomes fully defensible
```
