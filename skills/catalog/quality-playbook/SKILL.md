---
name: quality-playbook
description: "Use when asked to run all quality checks, do a pre-commit quality pass, check code health, run the full linting and type-checking pipeline, verify code is ready to merge, or do a comprehensive code quality audit on this Python project."
---

# Quality Playbook Skill

## When This Skill Applies

- "Run all quality checks"
- "Is this code ready to merge?"
- "Run the full lint + type check + test pipeline"
- "Check code health before committing"
- "Something failed in CI, help me fix it"

---

## The Full Quality Pipeline (Ordered)

Run these steps **in order** — each gate must pass before the next.

```
1. black   → formatting (auto-fixable)
2. isort   → import order (auto-fixable)
3. flake8  → style/logic lint (partially fixable)
4. mypy    → type safety (manual fixes)
5. pytest  → test suite + coverage (manual fixes)
```

---

## Step 1: Formatting — black

```powershell
# Check mode (no writes, just report)
python -m black --check --diff .

# Fix mode (apply all formatting)
python -m black .
```

**Pass condition**: exits 0, no "would reformat" messages.

---

## Step 2: Import Order — isort

```powershell
# Check mode
python -m isort --profile black --check-only --diff .

# Fix mode
python -m isort --profile black .
```

**Pass condition**: exits 0, no diff output.

---

## Step 3: Lint — flake8

```powershell
# Full check (respects line-length=100 from black)
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .

# Scope to source modules only (skip tests for quick check)
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 modules/
```

**Pass condition**: exits 0, zero error lines printed.

**Common codes to fix**:
| Code | Meaning |
|------|---------|
| `F401` | Unused import — delete it |
| `E711/E712` | Use `is None` / `if x:` instead of `== None/True` |
| `F811` | Duplicate name — remove the shadowed definition |

---

## Step 4: Type Checking — mypy

```powershell
# Check modules/ (configured scope in pyproject.toml)
python -m mypy modules/

# Strict check on a single file
python -m mypy modules/scoring_engine.py --ignore-missing-imports
```

**Pass condition**: exits 0, "Success: no issues found" message.

**Common errors and fixes**:
| Error | Fix |
|-------|-----|
| `error: Incompatible return value` | Correct return type or annotation |
| `error: Item "None" of "Optional[X]" has no attribute` | Add `if x is not None:` guard |
| `error: Missing return statement` | Add missing `return` in all branches |
| `error: Argument 1 has incompatible type` | Fix call site or update type annotation |

---

## Step 5: Tests + Coverage — pytest

```powershell
# Full suite with coverage (uses pyproject.toml config)
python -m pytest

# Quick check (skip slow tests)
python -m pytest -m "not slow" -q

# With explicit coverage threshold
python -m pytest --cov-fail-under=80
```

**Pass condition**: all tests green, coverage ≥ threshold, no warnings about missing markers.

---

## One-Shot Quality Script

```powershell
# Run full pipeline, stop on first failure
$ErrorActionPreference = "Stop"
Write-Host "=== 1/5 black ===" -ForegroundColor Cyan
python -m black --check .

Write-Host "=== 2/5 isort ===" -ForegroundColor Cyan
python -m isort --profile black --check-only .

Write-Host "=== 3/5 flake8 ===" -ForegroundColor Cyan
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .

Write-Host "=== 4/5 mypy ===" -ForegroundColor Cyan
python -m mypy modules/

Write-Host "=== 5/5 pytest ===" -ForegroundColor Cyan
python -m pytest -q --cov-fail-under=80

Write-Host "All checks passed!" -ForegroundColor Green
```

Save as `.github/scripts/quality-check.ps1` for reuse.

---

## Fix-All Then Check (Fast Path)

When you want to fix formatting first, then check the rest:

```powershell
# Auto-fix everything fixable
python -m black .
python -m isort --profile black .

# Then check what still needs manual attention
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .
python -m mypy modules/
python -m pytest -q
```

---

## Quality Gate Thresholds

| Check | Required Status |
|-------|----------------|
| black | No files would be reformatted |
| isort | No import order changes needed |
| flake8 | Zero errors (warnings acceptable) |
| mypy | Zero errors on `modules/` |
| pytest | All tests pass |
| coverage | ≥ 80% on `modules/` |

---

## Triage by Exit Code

| Tool | Exit Code | Meaning |
|------|-----------|---------|
| black --check | 1 | Files need reformatting (run `black .` to fix) |
| isort --check | 1 | Imports need reordering (run `isort .` to fix) |
| flake8 | 1 | Lint errors found (manual fix required) |
| mypy | 1 | Type errors found (manual fix required) |
| pytest | 1 | Tests failed OR coverage below threshold |
| pytest | 2 | Interrupted / config error |
| pytest | 5 | No tests collected (check `testpaths` in pyproject.toml) |
