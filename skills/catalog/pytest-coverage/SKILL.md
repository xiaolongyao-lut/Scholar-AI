---
name: pytest-coverage
description: "Use when asked to run tests with coverage, find untested code, improve test coverage, analyze coverage gaps, set coverage thresholds, or generate coverage reports for this Python project."
---

# Pytest Coverage Skill

## When This Skill Applies

- "Run tests and show coverage"
- "What code paths are untested?"
- "Improve coverage for module X"
- "Set a coverage threshold"
- "Why is coverage dropping?"

---

## Project Coverage Configuration

This project is pre-configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-v --strict-markers --tb=short --cov=modules --cov-report=html --cov-report=term-missing"
```

- **Source measured**: `modules/` directory
- **HTML report**: `htmlcov/index.html` (open in browser for line-by-line view)
- **Term report**: shows missing lines directly in terminal

---

## Step-by-Step Workflow

### 1. Run Full Coverage

```powershell
# Run all tests with coverage (uses pyproject.toml config automatically)
python -m pytest

# Run with explicit fail threshold (blocks CI if below)
python -m pytest --cov-fail-under=80

# Run faster with parallel workers
python -m pytest -n auto
```

### 2. Target a Specific Module

```powershell
# Coverage for one module only
python -m pytest tests/ --cov=modules/scoring_engine --cov-report=term-missing

# Coverage for multiple specific modules
python -m pytest --cov=modules --cov=pipeline_core --cov-report=term-missing
```

### 3. Read the Report

**Terminal output columns**:
| Column | Meaning |
|--------|---------|
| `Stmts` | Total executable statements |
| `Miss` | Statements not covered |
| `Cover` | Coverage % |
| `Missing` | Line numbers with no test coverage |

**Key signals to act on**:
- Lines in `Missing` column → write tests targeting those paths
- 0% coverage on a module → that module has NO tests at all
- Coverage drops after a commit → new code was added without tests

### 4. Open HTML Report

```powershell
# Windows: open the report in default browser
Start-Process htmlcov\index.html
```

Click any file name → see red-highlighted lines = untested, green = covered.

### 5. Find Coverage Gaps and Fix

When you see a missing line range (e.g., `45-67`):

1. Open the file, read lines 45-67
2. Identify what condition or branch is untested
3. Write a test that exercises that path:
   ```python
   # Example: untested error branch
   def test_scoring_engine_handles_empty_input():
       engine = ScoringEngine()
       result = engine.score([])
       assert result == []
   ```
4. Re-run pytest to confirm the line is now green

---

## Coverage Targets (Recommended)

| Module Type | Minimum Target |
|-------------|---------------|
| Core business logic (`scoring_engine`, `pipeline_core`) | 85% |
| Utility modules (`datetime_utils`, `db`) | 75% |
| Recovery/failover modules | 70% |
| CLI entry points (`start.py`, `main_*`) | 50% |

---

## Common Issues

**"No data was collected"**
- Make sure you're running from the repo root, not inside `modules/`
- Check that `--cov=modules` points to an existing directory

**Coverage drops on CI but passes locally**
- CI may skip slow/integration tests (`-m "not slow"`) — check markers
- Run: `python -m pytest -m "not slow" --cov=modules --cov-fail-under=80`

**Coverage is high but tests are weak**
- High coverage ≠ good tests. Use `--cov-branch` to measure branch coverage too:
  ```powershell
  python -m pytest --cov=modules --cov-branch --cov-report=term-missing
  ```

---

## Integration with CI

Add to `pytest.ini_options` or CI script to enforce thresholds:

```toml
# pyproject.toml — enforce 80% minimum
addopts = "... --cov-fail-under=80"
```

Or in a PowerShell CI step:

```powershell
python -m pytest --cov=modules --cov-fail-under=80
if ($LASTEXITCODE -ne 0) { exit 1 }
```
