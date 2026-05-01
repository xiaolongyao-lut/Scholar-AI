# Phase P3: Scoring Configuration Externalization and Safe Parallelization

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to externalize scoring configuration from the analysis pipeline and then add optional, benchmarked parallel scoring without disturbing the Harness / Recovery stack.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - Python `multiprocessing` official docs, especially Windows `spawn`
   - configuration validation patterns in Python
   - deterministic parallel batch processing patterns
3. This phase must be implemented in two internal steps:
   - Step A: externalize scoring configuration
   - Step B: add optional parallel scoring
4. Do not begin Step B until Step A is tested and stable.
5. Do not modify recovery/autopilot architecture in this phase.

## Preconditions

Only start this phase after P0 is green.

## Current repo-grounded facts

These are true in the current codebase:

- `07_analysis_scoring_improved_v9.py` exists and is the likely scoring target.
- The repo already contains tests for config management, paper processing, evidence classification, and parallel processing.
- The repository includes Windows-focused parallel processing validation, so new work must remain Windows-safe and deterministic.

## Required outcome

1. Hard-coded scoring rules must be moved into an external configuration source.
2. The scoring pipeline must load and validate that configuration safely.
3. Optional multiprocessing must be added only if output parity is preserved.

## Step A requirements: configuration externalization

Implement a configuration-backed scoring layer:

- create or extend a scoring config file under `config/`
- add a robust loader with validation and caching
- replace hard-coded weights, thresholds, or patterns in `07_analysis_scoring_improved_v9.py` with config-backed values
- keep default behavior unchanged for equivalent config

## Step B requirements: optional parallel scoring

Add opt-in parallel scoring only after configuration externalization is stable:

- use a Windows-safe multiprocessing design
- keep ordering deterministic
- avoid large pickle payloads
- expose worker count through a CLI argument or equivalent opt-in mechanism
- preserve exact output parity between single-worker and multi-worker modes

## Important constraints

1. Parallel mode must be optional, not mandatory.
2. If benchmarks do not show meaningful improvement, do not oversell the result.
3. If the current workload is I/O-bound or too small to benefit, report that truthfully.
4. Keep the change local to the scoring path.

## Acceptance criteria

All of the following must be true:

1. Scoring configuration is externalized and validated.
2. Default scoring output remains unchanged for equivalent config.
3. Parallel scoring can be enabled without breaking determinism.
4. Single-worker and multi-worker outputs match after normalization.
5. Benchmarks are reported truthfully with exact commands and sample sizes.

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest tests/test_config_manager.py tests/test_evidence_classifier.py tests/test_paper_processor.py tests/test_parallel_processor.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

Also run at least one reproducible parity check and one benchmark command, and report them exactly.

## Deliverables

1. Config externalization implementation
2. Optional parallel scoring implementation
3. Tests and parity validation
4. A truthful completion report with:
   - exact benchmark commands
   - exact timing results
   - exact regression status

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- whether config is now externalized
- whether parallel scoring is optional and deterministic
- exact passing test counts
