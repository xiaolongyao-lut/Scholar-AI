# Frontend State Spec

Switch and Trinity should preserve the current design language while ensuring the UI clearly expresses the system state.

## Core Screen States

### Source Selection

- no folder selected
- folder selected and ready
- invalid path
- scanning source folders

### Keyword Input

- no keyword yet
- keyword ready
- invalid or too-broad keyword warning
- keyword accepted for relevance scan

### Relevance Scan

- not started
- running
- candidates found
- no relevant candidates
- error during relevance scan

### Extraction

- pending extraction
- extracting relevant candidates
- extraction completed
- partial extraction failure
- extraction failed

### Intelligent Chat

- unavailable because no literature context yet
- ready with literature context
- responding
- insufficient context to answer well
- grounded answer available

### Insight Message

- not generated
- generating
- available
- skipped because context quality is too low

## UI Rules

- The UI must help users understand which stage they are currently in.
- Provenance and relevance should be legible when results are shown.
- Do not redesign the visual system during normal implementation.
- Improve clarity within the current style, not by replacing it.
