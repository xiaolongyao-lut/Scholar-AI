# Plans Directory

This is the canonical location for active project plans, specs, and AI execution plans.

## Reference Model

- The Turing Way treats project documentation and roadmaps as shared project context that helps contributors avoid duplicated work and understand priorities.
- Diataxis separates documentation by user need; plans/specs are execution context, so they stay together instead of being hidden in tool-private folders.
- Read the Docs documents Diataxis-style structure as a practical way to keep documentation navigable as projects grow.

## Layout

- `active/`: current master plans that control project progress.
- `kilo/`: plans migrated from `.kilo/plans/`.
- `copilot/`: plans migrated from `.copilot-tracking/plans/`.
- `specs/`: design specs that should be read as project plans.
- `superpowers/`: reserved for future superpower-specific plans.

## Rules For AI Agents

- Create new plan files under `docs/plans/`; do not create new active plans under `.kilo/plans/`, `.copilot-tracking/plans/`, or `docs/superpowers/specs/`.
- When a historical path points to a migrated plan, follow the redirect stub to `docs/plans/`.
- The active master plan is `docs/plans/active/2026-04-27-full-project-build-master-plan.md`.
- If a tool requires a legacy path, keep only a small redirect file there and put the real content here.
