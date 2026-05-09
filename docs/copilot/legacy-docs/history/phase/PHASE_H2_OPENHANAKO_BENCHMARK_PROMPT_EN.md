# Phase H2 OpenHanako Benchmark + Harness Productization Prompt

You are continuing work inside:
`C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`

Current repository baseline:
- Harness V2 Layers 1-6 are already operational through Phase G.
- Phase H1 Memory-Grounded Recovery Advisor is complete.
- Phase H1.1 Memory Evidence Integration is complete.
- The next step must consider the existing Harness architecture and the current AI memory work. Do not propose a fresh greenfield system that ignores what is already built.

Your task is to benchmark the newly added OpenHanako 0.91.9 project and derive a new, multi-phase Harness roadmap for this repository that selectively borrows the best ideas from OpenHanako in these areas:
- architecture
- final program packaging and installer strategy
- UI and UX patterns
- API and provider onboarding
- plugin/capability surfaces
- AI memory experience
- operator inspection and recovery workflow

The goal is not to copy OpenHanako. The goal is to extract the most valuable product and engineering patterns, translate them into this repository's Python/FastAPI/Harness stack, and produce a concrete new Harness plan that remains compatible with the current AI memory implementation.

## Non-Negotiable Rules

1. Before any file edits, create a rollback snapshot.
Use PowerShell and write the actual snapshot path into your notes/report.

Example:
```powershell
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path 'C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.rollback_snapshots' ('phase-h2-openhanako-benchmark-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null
Get-ChildItem 'C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script' -File -Filter '*.md' | Copy-Item -Destination $snapshot -Force
Write-Output $snapshot
```

2. Search mature solutions before locking in any recommendation.
Do not rely only on intuition. For each major recommendation, check official docs or widely adopted production references first.

At minimum, consult:
- OpenHanako source and docs
- Electron security checklist: `https://www.electronjs.org/docs/latest/tutorial/security`
- electron-builder configuration docs: `https://www.electron.build/configuration.html`
- FastAPI WebSockets docs: `https://fastapi.tiangolo.com/advanced/websockets/`
- If you recommend Python desktop packaging, also compare official PyInstaller docs: `https://pyinstaller.org/en/stable/`
- If you recommend native-app packaging alternatives, compare official BeeWare/Briefcase docs: `https://beeware.org/docs/`

3. Use OpenHanako 0.91.9 as the versioned comparison target.
Do not silently mix in conclusions from newer `main` branch behavior unless you clearly mark them as newer-than-0.91.9.

4. Do not execute the installer.
You may inspect installer metadata, hash, signature state, packaging scripts, and source code. Do not run `Hanako-0.91.9-Windows-x64.exe`.

5. Do not copy Node/Electron implementation details directly into this Python/FastAPI repo.
Translate principles, boundaries, UX patterns, packaging patterns, and extension points into the current stack.

6. AI memory must remain evidence-backed.
Memory can enrich recovery and operator workflows, but it must not become an unbounded hidden truth source that overrides canonical events, temporal facts, or audited recovery decisions.

7. Be truthful.
Do not overstate production readiness. Do not claim installer behavior, packaging guarantees, security properties, or live runtime behavior unless supported by source or direct non-destructive inspection.

## Required Local Inputs

Primary repo:
- `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`

OpenHanako comparison repo:
- `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\github\openhanako-0.91.9`

Installer artifact:
- `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\github\openhanako-0.91.9\Hanako-0.91.9-Windows-x64.exe`

Known installer facts already verified locally:
- Product version: `0.91.9`
- File version: `0.91.9`
- Product name: `Hanako`
- Company: `liliMozi`
- Digital signature: `NotSigned`
- SHA256: `AB7B71FE98E55F20022443062E9683F08ED80DD79F93D8198E063EC0FD3F2586`

Known OpenHanako source areas already worth examining:
- `package.json`
- `scripts/build-server.mjs`
- `scripts/launch.js`
- `build/installer.nsh`
- `desktop/main.cjs`
- `server/index.js`
- `core/engine.js`
- `core/plugin-manager.js`
- `hub/index.js`
- `server/routes/providers.js`
- `server/routes/plugins.js`
- `desktop/src/react/onboarding/steps/ProviderStep.tsx`
- `desktop/src/react/onboarding/steps/ModelStep.tsx`
- `desktop/src/react/components/chat/PluginCardBlock.tsx`
- `desktop/src/react/components/plugin/PluginPageView.tsx`
- `desktop/src/react/components/desk/DeskEditor.tsx`
- `desktop/src/react/settings/tabs/agent/AgentMemory.tsx`
- `desktop/src/react/settings/overlays/CompiledMemoryViewer.tsx`
- `desktop/src/react/settings/overlays/MemoryViewer.tsx`
- `lib/memory/compile.js`
- `README.md`
- `PLUGINS_EN.md`

## What You Must Figure Out

Produce a grounded comparison between OpenHanako and this repository across the following dimensions.

### 1. Architecture
Evaluate whether these OpenHanako patterns are worth borrowing:
- clear split between `desktop`, `server`, `core`, `hub`, `lib`, `plugins`
- a thin engine facade over multiple managers
- a central event bus / hub for scheduling, channels, bridges, and notifications
- a separate local server process packaged with the desktop app

For each pattern, answer:
- what problem it solves in OpenHanako
- whether the same problem exists here
- whether it should be borrowed now, later, or not at all
- what the Python/FastAPI/Harness translation would look like

### 2. Final Program Packaging
Evaluate OpenHanako's packaging strategy:
- Electron shell + bundled local server
- per-platform packaged server resources
- NSIS installer customization
- process kill hooks during upgrade
- updater/publish metadata
- unsigned Windows installer tradeoffs

Then propose the best packaging direction for this repository:
- keep backend-only and improve deployment packaging
- add a desktop shell around FastAPI
- bundle a Python runtime plus local API service
- or use a hybrid packaging model

You must compare at least two mature packaging directions before recommending one.
Do not default to Electron just because OpenHanako uses it.

### 3. UI and UX
Evaluate whether these patterns are worth borrowing:
- first-run onboarding wizard
- provider connection test before completing onboarding
- selecting chat model + utility model + utility-large model separately
- plugin cards embedded in chat
- plugin pages/widgets rendered in isolated frames
- a dedicated Desk/workbench for files, notes, and execution context
- memory viewers for compiled memory and raw memory records

For each UI idea, state:
- user value
- engineering cost
- fit with current repo
- whether it should become a near-term Harness phase

### 4. API and Provider Integration
Evaluate these OpenHanako patterns:
- provider summary endpoint
- model discovery with fallback layers
- connection probing before save
- plugin route proxying
- local token-protected server model
- WebSocket event delivery to the renderer

Map each one into this repository's current FastAPI and Harness model.
If you recommend streaming or real-time operator inspection, explain whether FastAPI WebSockets or SSE is the better fit here and why.

### 5. Plugin / Capability / Extension Surface
Evaluate OpenHanako's plugin model:
- tools
- skills
- routes
- providers
- commands
- pages
- widgets
- extension hooks

Then decide what an equivalent extension model should be here.
Important:
- do not confuse OpenHanako's trust model with real sandboxing
- if you recommend an extension system here, clearly state what is genuinely sandboxed and what is merely permission-gated
- ensure compatibility with current Harness capabilities, recovery APIs, and AI memory flows

### 6. AI Memory Compatibility
This is mandatory.

You must explicitly integrate current AI memory work into the recommendation, not treat it as an afterthought.

Analyze whether OpenHanako offers borrowable ideas in:
- compiled memory presentation
- raw memory inspection
- pins / persistent context
- import/export flows
- memory gating behind utility models
- recent vs long-term memory compilation

Then map those ideas into this repository's existing memory and recovery stack:
- canonical events
- temporal facts
- memory-grounded recovery recommendations
- evidence references
- audit trails
- replay / rehydration / invalidation

You must preserve this rule:
- canonical events and audited facts remain the primary operator-traceable truth
- AI memory can enrich context, suggestions, and summaries, but must stay traceable and reviewable

### 7. Security and Product Credibility
Evaluate:
- Electron remote content security implications
- iframe/plugin isolation limits
- unsigned installer trust tradeoffs
- plugin full-access risks
- local server token model
- update and packaging trust boundaries

Then translate those lessons into actionable recommendations for this repo.

## Required Deliverables

You must deliver all of the following.

1. `OPENHANAKO_BORROWING_ASSESSMENT.md`

This document must include:
- repository baseline summary
- OpenHanako 0.91.9 evidence summary
- architecture comparison
- packaging comparison
- UI/UX comparison
- API/provider comparison
- plugin/extensibility comparison
- AI memory comparison
- security comparison
- a strict classification table:
  - Borrow Now
  - Borrow Later
  - Do Not Borrow

Every major conclusion must cite the OpenHanako source file(s) or official doc(s) that support it.

2. `HARNESS_VNEXT_MULTIPHASE_ROADMAP.md`

This roadmap must not collapse into one giant phase.
Define at least six concrete phases, with IDs, in order.

At minimum, cover:
- one phase for operator observability / live event timeline
- one phase for AI memory workbench or evidence UI
- one phase for provider onboarding / model profile UX
- one phase for plugin or capability surface design
- one phase for packaging / installer / deployment productization
- one phase for security hardening and credibility validation

For each phase include:
- goal
- why it matters
- exact repo modules likely affected
- dependencies on earlier phases
- acceptance criteria
- validation strategy
- rollback considerations

3. If and only if there is a high-confidence, low-risk first slice, implement that first slice after the roadmap.

Acceptable first-slice examples:
- a typed provider onboarding API improvement
- a memory inspection endpoint refinement
- a structured event-stream API foundation
- a packaging manifest or build scaffold document

Do not jump into a broad UI rewrite or desktop shell implementation unless the repository already contains the necessary scaffolding.

## Mandatory Multi-Phase Shape

Your new plan must be multi-phase and precise. A good default shape is:
- Phase H2-A: Operator Event Stream and Timeline Foundations
- Phase H2-B: Memory Workbench and Evidence Inspection
- Phase H2-C: Provider Onboarding and Model Profile UX
- Phase H2-D: Capability / Plugin Surface for Recovery-Aware Extensions
- Phase H2-E: Product Packaging and Installer Strategy
- Phase H2-F: Security Hardening and Production Credibility

You may rename phases if a better grounded structure emerges, but you must keep a similarly granular multi-phase plan.

## Required Verification Checklist

Before declaring the work complete, verify all of the following:

- rollback snapshot path created and recorded
- OpenHanako analysis is grounded in local `0.91.9` files, not only `main`
- installer was not executed
- packaging recommendation compares at least two mature approaches
- every major borrowed idea is mapped into this repository's current Harness and AI memory design
- memory recommendations preserve evidence traceability and operator auditability
- plugin/extensibility recommendations state real trust boundaries
- roadmap has at least six phases
- every phase has acceptance criteria and validation
- any implementation done is low-risk, scoped, and tested
- documentation claims are truthful and repository-grounded

## Output Style

Be decisive and concrete.
Do not give a vague inspiration list.
Do not stop at "OpenHanako is interesting."
Produce a repository-grounded assessment, a real new Harness roadmap, and only then implement the safest justified first slice if appropriate.
