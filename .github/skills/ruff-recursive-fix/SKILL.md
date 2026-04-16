---
name: ruff-recursive-fix
description: "Use when asked to fix lint errors recursively, auto-fix Python code style issues, run flake8 and auto-apply fixes, migrate from flake8 to ruff, clean up code quality warnings across all Python files, or bulk-fix formatting and import order issues."
---

# Ruff Recursive Fix Skill

## When This Skill Applies

- "Fix all lint errors across the project"
- "Auto-fix import order issues"
- "Run flake8 and fix what it finds"
- "Clean up style warnings recursively"
- "Should I switch to ruff?"

---

## This Project's Current Setup

This project uses **flake8 + black + isort** (defined in `pyproject.toml`):

```
flake8  → lint checker (no auto-fix)
black   → auto-formatter
isort   → import sorter
```

**Ruff** is a modern drop-in replacement that is 10-100× faster and can auto-fix many issues. This skill covers both workflows.

---

## Option A: Fix with Current Tools (flake8 + black + isort)

### Step 1 — Auto-format with black

```powershell
# Check what black would change (safe, no writes)
python -m black --check --diff .

# Apply formatting to all Python files
python -m black .

# Apply to a specific file or folder only
python -m black modules/ pipeline_core.py
```

### Step 2 — Fix import order with isort

```powershell
# Check only (no writes)
python -m isort --check-only --diff .

# Apply fixes
python -m isort .

# isort must be compatible with black profile
python -m isort --profile black .
```

### Step 3 — Check remaining lint with flake8

```powershell
# Full lint check
python -m flake8 .

# Ignore specific codes (e.g., line-length already handled by black)
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .

# Check only a specific directory
python -m flake8 modules/
```

### Step 4 — Fix flake8 errors that black can't fix

Common manual fixes:

| flake8 code | Meaning | Fix |
|-------------|---------|-----|
| `F401` | Unused import | Delete the import line |
| `F811` | Redefined unused name | Remove duplicate definition |
| `E711` | `== None` comparison | Change to `is None` |
| `E712` | `== True/False` comparison | Change to `if x:` / `if not x:` |
| `W291` | Trailing whitespace | black handles this |
| `E501` | Line too long | Wrap or shorten (if > 100 chars) |

---

## Option B: Switch to Ruff (Recommended for Speed)

Ruff replaces flake8 + isort + many other plugins in one fast binary.

### Install

```powershell
pip install ruff
```

### Recursive check (all Python files)

```powershell
# Show all issues
ruff check .

# Auto-fix everything fixable
ruff check --fix .

# Fix unsafe fixes too (e.g., unused imports)
ruff check --fix --unsafe-fixes .
```

### Auto-format (replaces black)

```powershell
# Check only
ruff format --check .

# Apply formatting
ruff format .
```

### Recommended `ruff` config for this project

Add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py38"
exclude = [".venv", "__pycache__", ".git"]

[tool.ruff.lint]
select = ["E", "F", "W", "I"]   # pycodestyle + pyflakes + isort
ignore = ["E203", "W503"]

[tool.ruff.lint.isort]
profile = "black"
```

---

## Full Recursive Fix Sequence (One Shot)

```powershell
# Using current tools
python -m black .
python -m isort --profile black .
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .

# OR using ruff (faster equivalent)
ruff check --fix .
ruff format .
```

---

## When to Stop Auto-Fixing

Do NOT auto-fix these — always review manually:

- `F841` — local variable assigned but never used (may hide logic errors)
- `E501` — long lines in string literals or SQL (breaking them changes semantics)
- Any fix in test files that changes assertion logic
- Import removals in `__init__.py` files (may break public API)

---

## Verify After Fixing

```powershell
# Confirm no remaining lint errors
python -m flake8 --max-line-length=100 --extend-ignore=E203,W503 .

# Confirm tests still pass
python -m pytest --tb=short -q
```
