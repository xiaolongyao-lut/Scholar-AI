# tools/squad/squad.ps1 - RETIRED 2026-04-27

## Status: DEPRECATED

Per Squad 0.9.3-modular decision D7=B, the local PowerShell wrapper for long-running Squad work is retired. All long-running work (>10 minutes, paid eval, batch processing) is now handed off to Copilot CLI Sessions instead.

## Replacement

- **Short tasks (<10 min)**: Run inline in chat with the Squad agent.
- **Long tasks (>10 min)**: The Squad coordinator emits a Facts/Decisions/Open/Next handoff packet and routes you to Copilot CLI Sessions.

## Why the file is kept (renamed to .deprecated)

Kept for archaeology / git history continuity. Do NOT execute. To restore, see git log of this file.

## References

- .github/agents/squad.agent.md (LONG-RUN HANDOFF RULE block)
- .squad/routing.md (D7=B section)
- .kilo/plans/2026-04-27-squad-official-capability-reuse.md

