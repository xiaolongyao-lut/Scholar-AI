# /squad-round

> Internal round prompt invoked by `ScheduleWakeup` continuation. It is not a guaranteed user-facing slash command unless the host registers it separately.

Execute one Claude Code Squad decision round using the coordinator prompt template at `.claude_squad/identity/coordinator-prompt.md`.

## Execution Steps

1. Read `.claude_squad/identity/coordinator-prompt.md` for the full decision framework.
2. Read the startup packet from `.claude_squad/`:
   - `.claude_squad/identity/claude-now.md`
   - `.claude_squad/identity/claude-goal-drift.md`
   - `.claude_squad/identity/claude-requirement-pool.md` (tail 100 lines)
   - `.claude_squad/memory/claude-DECISION_TRAIL.md` (tail 50 lines)
   - `.claude_squad/memory/OPEN_THREADS.md`
3. Assess current state against the Decision Framework (Step 0 → Step 5).
4. Execute the chosen action:
   - **Dispatch**: `Agent(subagent_type='general-purpose', run_in_background=true)` with agent-specific prompt
   - **File**: add requirement to pool
   - **Close**: update OPEN_THREADS or mark pool entry resolved
   - **Audit**: verify a prior claim with grep/read evidence
   - **State-update**: record infrastructure delta observation
5. Append one entry to `.claude_squad/memory/claude-DECISION_TRAIL.md` using `checkpoint <UTC>` format.
6. Call `ScheduleWakeup(delaySeconds=240)` for next round unless the user explicitly paused/stopped the loop.
7. On every wake-up, use this health-check prompt: `检查 squad 当前状态：是否仍在运行、是否有新 artifact delta、是否命中 HR4/硬阻塞；若异常则先停 squad 修复，再恢复 /squad-round 循环。`

## Hard Rules (from CLAUDE.md §Long-run hard rules)

- **HR1**: Pool write via pool_append.py only; non-zero exit = hard stop
- **HR2**: Dedup against last 50 pool entries before filing
- **HR3**: Pre-flight check before any dispatch
- **HR4**: 2 rounds no artifact delta → stop with Facts/Stalled/Safe-next
- **HR5**: Use `checkpoint <UTC>`, never self-author `Round N`
- **HR6**: Every exit → Facts/Decisions/Open/Next block

## File Boundaries

- **Write domain**: `.claude_squad/` only
- **Read-only reference**: `.squad/` (Copilot Squad's files)
- **Never touch**: `.copilot/`, `.github/agents/`
