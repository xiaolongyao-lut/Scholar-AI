# Algorithm Reliability Guide

This file protects the core retrieval and extraction path from gradual quality erosion.

## Core Principle

Reliability of traversal, relevance scan, extraction, and literature-grounded chat is more important than speculative speedups or stylistic rewrites.

## Reliability Rules

- Do not weaken the relevance filter just to increase throughput.
- Do not skip provenance tracking for convenience.
- Do not merge algorithm changes into the core path without at least targeted validation.
- Keep rollback easy when changing retrieval, extraction, or ranking behavior.

## Change Types That Need Extra Care

- folder traversal logic changes
- keyword filtering logic changes
- relevance scoring or ranking changes
- extraction parsing changes
- context assembly changes for intelligent chat

## Minimum Validation Expectations

When one of the above changes:

- verify the main workflow still works end-to-end
- verify irrelevant files are not exploding extraction cost
- verify relevant files are still reaching the chat context
- verify user-visible behavior remains explainable

## Escalation Rule

If an algorithm change improves one metric but weakens reliability or explainability, escalate to Morpheus instead of shipping it silently.
