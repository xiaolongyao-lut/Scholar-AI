# Contributing

Thank you for improving Scholar AI Workbench.

## Development Setup

Use the repository root as the working directory:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-ci.txt
cd frontend
npm ci
```

## Expected Checks

Backend:

```powershell
.\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
```

Frontend:

```powershell
cd frontend
npm run test -- --run
npm run build
```

## Pull Request Guidelines

- Keep changes scoped to one product surface or one maintenance goal.
- Do not commit credentials, `.env`, generated output, local runtime state, browser profiles, or agent cache files.
- Include tests or a clear verification note for behavioral changes.
- Add rollback notes for nontrivial path, storage, release, or API changes.
- Prefer existing project helpers and current paths under `literature_assistant/core/`.

## Generated Files

Generated runtime output belongs under `workspace_artifacts/` and is ignored by Git. Evaluation fixtures and deterministic manifests belong under `workspace_tests/` when they are required to reproduce tests.
