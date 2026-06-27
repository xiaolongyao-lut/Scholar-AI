# Scholar AI Desktop Pywebview Smoke

Date: 2026-06-20

Scope: desktop pywebview acceptance smoke only. No product-code change, no
real provider/API call, no staging/commit/push/tag/release/restore.

## Worktree

- Actual Codex worktree root:
  `C:\Users\xiao\.codex\worktrees\4ff1\Modular-Pipeline-Script`
- Source project root named by delegation:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`
- `pwd`:
  `C:\Users\xiao\.codex\worktrees\4ff1\Modular-Pipeline-Script`
- `git rev-parse --show-toplevel`:
  `C:/Users/xiao/.codex/worktrees/4ff1/Modular-Pipeline-Script`
- Initial `git status --short --branch`: detached `HEAD`; broad dirty
  worktree with the existing residual-closure files, tests, docs/plans, tools,
  and workspace_tests entries visible.

Important environment note:

- The current Codex worktree does not contain
  `.\.venv-1\Scripts\python.exe`.
- The source project root does contain
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe`.
- `AI_WORKSPACE_GUIDE.md` and `AGENTS.md` are absent in the Codex worktree root
  but present in the source project root; both were read from the source
  project root before the smoke.

## Required Records Read

- `AI_WORKSPACE_GUIDE.md` from source project root.
- `AGENTS.md` from source project root.
- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.
- `SOURCE_RELEASE_POLICY.md`.

## Rollback

- Checkpoint id:
  `20260620-191022-desktop-pywebview-smoke-20260620`
- Checkpoint path:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-ec5ce0c336fd2c52\20260620-191022-desktop-pywebview-smoke-20260620`
- Create command:
  `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\.codex\worktrees\4ff1\Modular-Pipeline-Script" --label "desktop-pywebview-smoke-20260620"`
- Restore policy: restore only after explicit user rollback intent.

## Dirty Worktree Audit

- In scope for this thread:
  `docs/plans/scholar-ai-desktop-pywebview-smoke-2026-06-20.md`.
- Existing implementation/audit residuals, not edited by this thread:
  modified backend/frontend/product/test files and untracked allowlisted tests
  already recorded by the residual-closure audit.
- Generated smoke artifacts from this thread:
  `workspace_artifacts/generated/desktop_smoke/start_desktop.stdout.log`,
  `workspace_artifacts/generated/desktop_smoke/start_desktop.stderr.log`.
- Unknown ownership: none edited. Existing broad dirty state was preserved.

## Mature / Official References

- pywebview usage documentation:
  https://pywebview.flowrl.com/guide/usage
  - `create_window` creates a window object and `webview.start()` starts the
    GUI loop; windows are not displayed until the GUI loop starts.
  - `window.destroy()` closes the window.
- pywebview API documentation:
  https://pywebview.flowrl.com/api/
  - `window.destroy()` destroys the window.
- Microsoft Win32 `EnumWindows`:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows
  - Enumerates top-level windows.
- Microsoft Win32 `GetWindowTextW`:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowtextw
  - Reads a window title bar string.
- Microsoft Win32 `IsWindowVisible`:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindowvisible
  - Confirms whether the window has the visible style.

## Smoke Command

Requested source command:

```powershell
& .\.venv-1\Scripts\python.exe .\start_desktop.py
```

Actual execution root:

```text
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
```

Reason: the delegated source project root has `.venv-1`; the Codex worktree
does not. The source project `git status --short --branch` showed the same
broad dirty residual-closure state as the Codex worktree, on
`main...origin/main [ahead 1]`.

Actual Python:

```text
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe
```

Smoke method:

- Started `start_desktop.py` with stdout/stderr redirected to separate files.
- Used Win32 top-level-window enumeration, title text, visibility, and process
  id to find a native desktop window titled `文献助手`.
- Posted `WM_CLOSE` to the discovered native window.
- Waited for the launcher process to exit.
- Checked no same-title top-level window remained and the smoke-selected
  backend port was closed.

## Result

Startup and window visibility:

- Process started: pid `44368`.
- No pre-existing top-level `文献助手` window was present before launch.
- Native top-level window found:
  - hwnd: `113903898`
  - owning pid: `63328`
  - title: `文献助手`
  - visible: `true`
- This evidence is a native Windows top-level window check, not a
  Chrome/Edge/Vite browser tab check.

Backend / launcher stdout tail:

```text
[启动器] 后端启动中 (127.0.0.1:11952)...
[route-audit] 355 unique (method, path) routes; no duplicates
[启动器] 后端就绪: http://127.0.0.1:11952
[启动器] LITERATURE_ASSISTANT_BASE_URL=http://127.0.0.1:11952
[启动器] 如果智能体找不到文献助手端口，请把上一行完整贴给智能体
[启动器] 桌面窗口已打开，关闭窗口将退出程序
[启动器] 窗口已关闭，退出
```

Shutdown / cleanup:

- `WM_CLOSE` posted: `true`.
- Launcher process exited within 30 seconds: `true`.
- Process alive after close: `false`.
- Top-level windows titled `文献助手` after close: none.
- TCP listener on `127.0.0.1:11952` after close: none.
- Other uvicorn processes on ports `9` and `8000` already existed before/after
  and were not touched because ownership was outside this thread.

Exception / exit status:

- Launcher exit code: `-532462766`.
- stderr tail contained a pythonnet/.NET exception during/after close:

```text
Python.Runtime.InternalPythonnetException: Failed to create Python type for System.ComponentModel.InvalidAsynchronousStateException
System.NullReferenceException
Python.Runtime.TypeManager.AllocateTypeObject
Python.Runtime.ReflectedClrType.GetOrCreate
Python.Runtime.Converter.ToPython
Python.Runtime.Exceptions.SetError
```

## Computer Use Attempt

The user allowed computer-control verification after the first smoke. The
Computer Use skill was read and the Windows helper bootstrap was attempted.
It failed before app control with:

```text
Package subpath './dist/project/cua/sky_js/src/targets/windows/internal/computer_use_client_base.js' is not defined by "exports" in ...\@oai\sky\package.json
```

No Windows app input was sent through Computer Use. The native-window evidence
above therefore comes from Win32 enumeration and close signaling.

## Verification Commands

- `git status --short --branch` before checkpoint: completed.
- Checkpoint create command: completed.
- `Test-Path .\.venv-1\Scripts\python.exe` in Codex worktree: `False`.
- `Test-Path .\.venv-1\Scripts\python.exe` in source root: `True`.
- `git status --short --branch` after smoke: unchanged except this new plan
  record and generated smoke logs under ignored runtime artifacts.
- `git diff --check -- docs/plans/scholar-ai-desktop-pywebview-smoke-2026-06-20.md`:
  must pass after this file is written.

## Gate Judgment

Recommend parent thread mark desktop gate as `blocked_clean_exit`, not fully
`passed`.

Evidence passed:

- Source desktop launcher started.
- Native desktop window titled `文献助手` appeared and was visible.
- The window was not a browser tab.
- The selected launcher process exited after the window close.
- No same-title desktop window or selected-port listener remained.

Blocking evidence:

- Close path emitted a pythonnet/.NET exception to stderr.
- Launcher process returned non-zero exit code `-532462766`.

Residual risk:

- This thread did not diagnose or fix the close-path exception because the
  assigned objective was smoke acceptance only, not product-code repair.
- Real provider/API smoke remains out of scope for this thread.

## Parent Main-Worktree Clean-Exit Rerun, 2026-06-20

After this delegated record was copied back into the main worktree, the parent
thread created checkpoint
`20260620-192653-desktop-clean-exit-diagnosis-20260620` and reran the same
source desktop entry from:

```text
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
```

The diagnostic loop first checked the local desktop runtime:

- `pywebview` 6.2.1
- `pythonnet` 3.0.5

Minimal pywebview control:

- A standalone `文献助手-minimal` pywebview window opened and exited with code
  `0` after `WM_CLOSE`.
- Its stderr included a WebView2 initialization warning, proving that WebView2
  stderr alone is not sufficient to mark the gate failed when the process exits
  cleanly.

Main `start_desktop.py` reruns:

- One direct rerun opened native `文献助手`, posted `WM_CLOSE`, exited with code
  `0`, left no same-title window, and produced empty stderr.
- Three additional consecutive reruns all opened native `文献助手`, posted
  `WM_CLOSE`, exited with code `0`, left no same-title window, and produced
  empty stderr.

Rerun log paths:

```text
workspace_artifacts/generated/desktop_smoke/start_desktop_repro.stdout.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro.stderr.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_1.stdout.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_1.stderr.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_2.stdout.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_2.stderr.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_3.stdout.log
workspace_artifacts/generated/desktop_smoke/start_desktop_repro_loop_3.stderr.log
```

Updated gate judgment:

- Desktop pywebview startup/native-window/close smoke is
  `passed_after_main_rerun`.
- The delegated first-run pythonnet/.NET exception and exit code `-532462766`
  remain a recorded intermittent close-path flake risk, not a currently
  reproducible blocker.
- No product code was changed for this rerun.

## Close-Path Mitigation And Stress Rerun, 2026-06-20

Seventh-round adversarial review reclassified the delegated first-run
pythonnet/.NET close-path exception as a real release gate risk rather than a
mere flake. The parent thread therefore created rollback checkpoint
`20260620-205506-seventh-review-gate-closure-20260620` and changed the source
desktop launcher.

Root-cause evidence:

- Local desktop runtime: `pywebview` 6.2.1 and `pythonnet` 3.0.5.
- Local pywebview source shows ordinary window events such as `shown` are
  asynchronous `Event` callbacks that start a Python thread, while
  `before_show` is a locking/synchronous event in the WinForms window creation
  path.
- The original failure involved pythonnet type creation during close:
  `Failed to create Python type` and `TypeManager.AllocateTypeObject`.

Code mitigation:

- `start_desktop.py` now applies Windows titlebar DWM color handling from
  `window.events.before_show` instead of `window.events.shown`.
- Reload hotkey JavaScript installation moved out of `shown` and into
  `webview.start(func=_install_reload_hotkeys, args=(window,))`, waiting for
  `window.events.loaded` before calling `evaluate_js`.

Verification:

- `.\.venv-1\Scripts\python.exe -m compileall -q start_desktop.py` passed.
- Helper import smoke confirmed `_install_reload_hotkeys` and
  `_apply_windows_titlebar_colors` are callable.
- 8-run native close-path stress loop passed:
  - each run found a native top-level `文献助手` window,
  - `WM_CLOSE` was posted,
  - process exit code was `0`,
  - stderr length was `0`,
  - no pythonnet or WebView2 E_ABORT marker appeared,
  - no same-title window remained,
  - selected backend port was closed after exit.
- Runtime summary:
  `workspace_artifacts/generated/desktop_smoke/closepath_fix_20260620_loaded_wait/summary.json`
  remains ignored under `workspace_artifacts/`.

Updated gate judgment:

- Desktop close-path gate is now
  `passed_closepath_mitigated_stress_verified`.
- This is stronger than `passed_after_main_rerun` because a code mitigation was
  applied and stress-verified.
- It is still not a release-wide desktop green light by itself; rerun desktop
  smoke before any release/public handoff because the original pythonnet close
  exception was real and machine/runtime-sensitive.
