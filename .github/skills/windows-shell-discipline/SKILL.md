---
name: windows-shell-discipline
description: Use when running terminal commands on Windows in this repo, especially Python venv invocations, multi-command chains, Claude/Copilot CLI sessions, or any time `bash: command not found` / `&&` errors appear.
---

# Windows Shell Discipline

## Why this exists

This repository is developed on Windows with a project-local venv at `.venv-1\`. Several past long-running Claude / Copilot sessions broke because the agent used a Bash heredoc or `&&`-chained command, which Windows PowerShell or `cmd.exe` cannot parse, producing errors like:

```
bash: .\.venv-1\Scripts\python.exe: command not found
The token '&&' is not a valid statement separator in this version.
```

These look like LLM failures but are pure shell mismatches. The fix is to be explicit about the shell.

## The four rules

1. **Default shell on Windows is PowerShell.** Configured in `.vscode/settings.json` via `terminal.integrated.defaultProfile.windows`. Do not assume Bash is available.
2. **Chain commands with `;`, never `&&`.** PowerShell 5.1 (the default on Windows 10/11) does not support `&&`. Use `;` or separate `run_in_terminal` calls.
3. **Always use the project venv with the full Windows path:** `.\.venv-1\Scripts\python.exe`. Never `python` (may resolve to system Python) and never `./venv/bin/python` (Linux path).
4. **Quote paths that contain spaces or backslashes.** E.g. `"C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"`.

## Path templates (copy-paste safe)

```powershell
# Run a script with the project venv
.\.venv-1\Scripts\python.exe path\to\script.py

# Run pytest
.\.venv-1\Scripts\python.exe -m pytest -q

# Install a package
.\.venv-1\Scripts\python.exe -m pip install <pkg>

# Multi-step (PowerShell)
.\.venv-1\Scripts\python.exe -m pip install -e . ; .\.venv-1\Scripts\python.exe -m pytest -q
```

## Anti-patterns

- ❌ `bash -c "source .venv-1/bin/activate && python ..."` — wrong shell, wrong path layout.
- ❌ `python script.py` — picks up whichever `python.exe` is first on PATH.
- ❌ `cmd1 && cmd2` in PowerShell sessions — silently breaks chain.
- ❌ Activating the venv inside an agent session (`activate.ps1`) — agents lose state between calls; use the explicit interpreter path instead.
- ❌ Using `mv`/`cp`/`rm` without checking shell — PowerShell aliases differ from POSIX.

## When you see a "command not found" or `&&` error

1. Check which shell the terminal is actually running (look for `PS C:\>` prompt = PowerShell, `C:\>` = cmd, `$` = bash).
2. Re-issue the command using the rules above.
3. Do NOT diagnose the underlying script as broken until the shell call itself succeeds.

## Related skills

- `third-party-llm-resilience` — shell errors often masquerade as LLM failures during long agent runs.
- `systematic-debugging` — Phase 1 (read errors carefully) catches shell-mismatch issues fast.
