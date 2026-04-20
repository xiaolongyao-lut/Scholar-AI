# Test Scenario Checklist

Use these as high-value realistic scenarios for phase-1 validation.

## Folder and Path Cases

- valid single folder path
- multiple folder paths
- folder path with spaces or non-ASCII characters
- nonexistent folder path
- empty folder
- folder with mixed relevant and irrelevant files
- very large folder with many files

## Data Source Cases

- Zotero-like folder structure
- notebook folder containing literature plus unrelated notes
- project-local literature repository with nested subfolders
- partially corrupted or unsupported files mixed into a valid corpus

## Keyword Cases

- strong narrow keywords
- broad keywords returning too many candidates
- irrelevant keywords
- empty keyword input
- multiple keyword combinations
- ambiguous keyword that matches both relevant and irrelevant files

## Retrieval and Extraction Cases

- relevance scan correctly reduces unnecessary extraction
- candidate ranking or filtering keeps useful files
- extraction succeeds on relevant files only
- extraction handles unsupported or malformed files gracefully
- provenance remains visible after extraction

## Intelligent Chat Cases

- user asks a question clearly grounded in retrieved literature
- user asks when context is insufficient
- user asks a question unrelated to current literature context
- system gives an insight message grounded in the literature base
- conversation after partial retrieval vs full relevant retrieval

## Pain-Point Cases

- user expects quick results but filtering is slow
- user cannot tell why a file was included or excluded
- user does not understand current retrieval stage
- user sees no useful answer after providing a seemingly good folder and keyword set
- user wants confidence that answers come from actual literature rather than generic model output

## Regression Rule

When a bug is found on the core path, add a scenario here or map it to one of the cases above.
