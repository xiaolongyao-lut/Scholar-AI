---
description: Start Claude Squad coordinator mode
argument-hint: [optional context or role]
---

Use the Claude Squad coordinator skill in `.claude/skills/squad/SKILL.md` as the authoritative workflow.

User input: $ARGUMENTS

Enter `/squad` mode using the skill's startup packet, coordinator identity, round execution protocol, loop contract, and health-check rules.
If `$ARGUMENTS` is present, treat it as extra context for the first coordination step rather than redefining the workflow.
