# Start Here

This is the mandatory onboarding entry point for every squad member before substantive work.

## Read Order

1. Canonical owner profile from `.claude_squad/config.json` or another explicit config reference (read it for operational boundaries; do not copy private profile text)
2. `.squad/identity/owner-profile-v4.md` (Squad adapter, not a duplicate source)
3. `.squad/INDEX.md` if it exists
4. `.squad/team.md`
5. `.squad/routing.md`
6. `.squad/identity/project-brief.md`
7. `.squad/identity/phase-plan.md`
8. `.squad/identity/data-sources.md`
9. `.squad/identity/interface-glossary.md`
10. `.squad/identity/night-shift-policy.md`
11. `.squad/identity/requirement-scoring.md`
12. `.squad/identity/requirement-pool.md`
13. `.squad/identity/frontend-state-spec.md`
14. `.squad/identity/test-scenarios.md`
15. `.squad/identity/algorithm-reliability.md`
16. `.squad/identity/refactor-policy.md`
17. `.squad/identity/now.md`
18. `.squad/identity/wisdom.md`
19. `.squad/memory/SESSION_SNAPSHOT.md`
20. `.squad/memory/OPEN_THREADS.md`
21. `.squad/memory/TEAM_MEMORY.md`
22. `.squad/decisions.md`
23. `.github/copilot-instructions.md` if it exists
24. task-relevant files under `.github/instructions/`
25. relevant files under `.squad/skills/`
26. `.squad/identity/long-run-prompt.md` when the request is `/squad` plus long-run, self-decision, unattended, or resume work

## Why This Exists

The project evolves across multiple conversations. Agents should not start from zero every time.

## What This Prevents

- forgetting the current product phase
- ignoring earlier design decisions
- proposing work outside the current milestone
- unapproved style drift or refactors
- losing track of real data sources and user workflow constraints
- reverting to the superseded user-profile v3 behavior
- forgetting overnight operating rules and escalation boundaries
- inconsistent naming for the same workflow concepts
- silent drift in algorithm reliability or frontend state expression

## Minimum Understanding Before Work

Each agent should know:

- what the product is trying to achieve now
- what the owner profile v4 requires before dispatching or declaring done
- what is explicitly out of scope for the current phase
- where real data comes from
- how overnight requirement discovery should be queued and scored
- which interface terms the team should use consistently
- what frontend states and test scenarios matter for the core path
- what rules protect algorithm reliability
- which rules govern refactors and style stability
- what team decisions already exist
- what unresolved threads and memory snapshots should be continued first
