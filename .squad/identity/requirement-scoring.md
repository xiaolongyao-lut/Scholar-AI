# Requirement Scoring

## Purpose

Give Morpheus a fast, repeatable way to judge whether a requirement should be acted on now, deferred, or parked for user review.

## Scoring Dimensions (Priority-Ordered)

Score each from 1 to 5. Use weighted scoring to reflect priority.

### 1. Real Usage Necessity for the RAG Literature Assistant (Weight: 5)

- 5 = directly needed in real literature-assistant workflows
- 3 = useful but not essential to common usage
- 1 = weak or speculative user need

### 2. Mature Solution Availability (Weight: 3)

- 5 = mature, proven solution exists and can be adopted safely
- 3 = partial references exist, adaptation needed
- 1 = no mature path, high uncertainty

Mature online implementations in established communities/frameworks count as strong reliability evidence.

### 2b. Paper-Backed Reliability Signal (Supplementary)

If a direction has clear literature support (papers, established methods), treat it as additional reliability evidence that can lift confidence within the same recommendation band.

### 3. No-Refactor Implementability (Weight: 2)

- 5 = can be implemented within current structure and style, no refactor needed
- 3 = minor structural pressure but still manageable without real refactor
- 1 = likely needs refactor or architectural disturbance

## Weighted Score

Use:

`total = necessity * 5 + maturity * 3 + no_refactor * 2`

Maximum = 50.

## Total Score Recommendation

- **40-50:** `DO NOW` if no policy conflict
- **28-39:** `LATER` (schedule after current must-deliver items)
- **18-27:** `WAITING FOR USER` unless it removes an immediate blocker
- **<18:** reject for current phase

## Hard Stops

Regardless of score, do not auto-approve if the item:

- requires refactor without Morpheus approval
- contains schema/storage changes
- introduces any new dependency
- breaks current style freeze
- pushes the product beyond the current phase
- introduces unclear architectural risk

## Fast Rule

If a task clearly belongs to existing in-scope RAG/literature/frontend incremental work and does not need refactor, it may bypass requirement-pool scoring and be executed directly.

Also, existing code/design ideas from the `github` project can be reused directly as implementation thinking if they fit current phase constraints and do not trigger hard stops.

## Morpheus Guidance

If scoring remains ambiguous after one pass, choose `WAITING FOR USER` and keep the team moving on safer work.

Code-level final judgment is Morpheus-only.
When judging, Morpheus should prioritize consistency with current project requirements, active phase scope, and historical plans/design docs.
