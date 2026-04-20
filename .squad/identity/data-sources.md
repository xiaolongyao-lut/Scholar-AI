# Data Sources and Retrieval Context

## Preferred Real Data Sources

Use real project-aligned sources first:

- User-provided literature folders
- Zotero-related export or storage folders
- Notebook folders with research materials
- Project-local document repositories

## Retrieval Principles

- Keyword filtering should happen early.
- Avoid extracting every file by default.
- Prefer relevance-oriented traversal over brute-force ingestion.
- Preserve traceability: know which folder or source produced a candidate result.

## Oracle Guidance

Oracle should prefer real folder-backed data sources before inventing synthetic placeholders.

## Switch Guidance

Switch should design UI flows that make source selection, keyword filtering, retrieval progress, and result provenance understandable.

## Tank Guidance

Tank should test with realistic path configurations, empty folders, noisy folders, irrelevant folders, and ambiguous keyword cases.
