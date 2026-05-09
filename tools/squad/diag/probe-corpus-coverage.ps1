#requires -Version 5.1
# probe-corpus-coverage.ps1
# Round-5 (2026-04-25 07:11) Morpheus self-applied artifact.
#
# WHAT: Read-only diagnostic that counts files at three corpus tiers and
#       emits a markdown verdict at .squad/audits/corpus-coverage-<ts>.md.
# WHY:  Today the question "is the indexed corpus actually a superset of the
#       Zotero source?" has no diagnostic. Once 6908f3cc lands and chat
#       returns 200s, the next-most-likely failure mode is "answer wrong
#       because relevant PDF was never indexed". This probe is a precondition
#       to ever filing that as a real bug.
# SCOPE: Pure read-only. No parsing of file content. No network. No mutation
#        of corpus, index, or .env. Atomic tmp+rename per CLAUDE.md §4.7.
# EXIT:  Always 0 (diagnostic, not gate).

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath)))
$AuditsDir = Join-Path $RepoRoot '.squad/audits'
if (-not (Test-Path $AuditsDir)) { New-Item -ItemType Directory -Path $AuditsDir -Force | Out-Null }

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$Out = Join-Path $AuditsDir "corpus-coverage-$ts.md"
$Tmp = "$Out.tmp"

function Count-Files {
    param([string]$Path, [string]$Pattern)
    if (-not (Test-Path $Path)) { return @{ count = 0; reachable = $false } }
    try {
        $n = (Get-ChildItem -LiteralPath $Path -Filter $Pattern -File -Recurse -ErrorAction Stop).Count
        return @{ count = $n; reachable = $true }
    } catch {
        return @{ count = -1; reachable = $false; error = $_.Exception.Message }
    }
}

# Tier A: Zotero source (PDFs)
$tierA = Count-Files -Path 'D:\zotero\zoterodate\storage' -Pattern '*.pdf'

# Tier B: extracted output (JSON)
$tierB = Count-Files -Path (Join-Path $RepoRoot 'output') -Pattern '*.json'

# Tier C: vector-index sidecar files (best-effort: parquet/sqlite/json under my-project)
$myProjPath = Join-Path $RepoRoot 'my-project'
$tierC = @{ count = 0; reachable = (Test-Path $myProjPath); files = @() }
if ($tierC.reachable) {
    $candidates = @()
    foreach ($pat in @('*.parquet','*.sqlite','*.duckdb','vectors*.json','index*.json','chunks*.json')) {
        $found = Get-ChildItem -LiteralPath $myProjPath -Filter $pat -File -Recurse -ErrorAction SilentlyContinue
        if ($found) { $candidates += $found }
    }
    $tierC.count = $candidates.Count
    $tierC.files = $candidates | Select-Object -First 5 | ForEach-Object { $_.FullName.Substring($RepoRoot.Length+1) }
}

# Tier C': Route-A bigram retrieval evidence (no vector store by design check).
# If my-project/src imports none of {chroma,faiss,qdrant,lancedb,weaviate,pgvector,chromadb,sqlite_vec,pinecone}
# the product retrieves via substring-prefilter over tier B — tier_C=0 is expected, not a gap.
$srcPath = Join-Path $myProjPath 'src'
$tierC.no_vector_lib = $false
if (Test-Path $srcPath) {
    $vecLibHits = Get-ChildItem -LiteralPath $srcPath -Filter '*.py' -File -Recurse -ErrorAction SilentlyContinue |
        Select-String -Pattern '^\s*(import|from)\s+(chroma|faiss|qdrant|lancedb|weaviate|pgvector|chromadb|sqlite_vec|pinecone)' -ErrorAction SilentlyContinue
    $tierC.no_vector_lib = ($null -eq $vecLibHits -or $vecLibHits.Count -eq 0)
}

# Verdict logic (deterministic, stated up front)
$verdict = if (-not $tierA.reachable) {
    'CORPUS_SOURCE_UNREACHABLE'
} elseif ($tierA.count -eq 0) {
    'CORPUS_SOURCE_EMPTY'
} elseif ($tierB.count -eq 0) {
    'EXTRACTION_NEVER_RAN'
} elseif ($tierB.count -lt [int]($tierA.count * 0.5)) {
    'EXTRACTION_PARTIAL'
} elseif ($tierC.count -eq 0 -and $tierC.no_vector_lib) {
    'NO_VECTOR_INDEX_BY_DESIGN'
} elseif ($tierC.count -eq 0) {
    'INDEX_SIDECAR_NOT_LOCATED'
} else {
    'COVERAGE_TRIPLE_PRESENT'
}

# Emit report
$body = @()
$body += "# corpus-coverage-$ts"
$body += ''
$body += "Generated: $(Get-Date -Format 'o')"
$body += ''
$body += '## A. Zotero source (PDFs)'
$body += "- path: ``D:\zotero\zoterodate\storage``"
$body += "- reachable: $($tierA.reachable)"
$body += "- pdf_count: $($tierA.count)"
$body += ''
$body += '## B. Extracted output (JSON)'
$body += "- path: ``output/``"
$body += "- reachable: $($tierB.reachable)"
$body += "- json_count: $($tierB.count)"
$body += ''
$body += '## C. Index sidecars (parquet/sqlite/duckdb/index json)'
$body += "- path: ``my-project/`` (recursive)"
$body += "- reachable: $($tierC.reachable)"
$body += "- sidecar_count: $($tierC.count)"
if ($tierC.files.Count -gt 0) {
    $body += '- first 5 sidecar paths:'
    foreach ($f in $tierC.files) { $body += "  - ``$f``" }
}
$body += ''
$body += '## D. Verdict'
$body += "**$verdict**"
$body += ''
$body += '## E. Notes'
$body += '- This probe is read-only and content-blind. It does NOT validate that JSON in (B) corresponds to PDFs in (A); that is a future requirement.'
$body += '- A C/A or B/A ratio implies coverage only if the index actually keys on document_id; not verified here.'
$body += '- Verdict CORPUS_SOURCE_UNREACHABLE means the Zotero allowlist may need to be applied per goal-drift §1 footnote.'
$body += '- Verdict NO_VECTOR_INDEX_BY_DESIGN means the product uses substring/bigram retrieval over tier B JSON; no vector-store library is imported by my-project/src. This is the current design, not a gap.'
$body += "- tier_C.no_vector_lib: $($tierC.no_vector_lib)"
$body += '- Round-5 self-applied (Morpheus); round-4 (2026-04-25 07:17) corrected verdict vocabulary to reflect Route-A bigram retrieval reality.'

$body -join "`r`n" | Out-File -FilePath $Tmp -Encoding utf8 -NoNewline
Move-Item -LiteralPath $Tmp -Destination $Out -Force

Write-Output "tier_A_pdf=$($tierA.count) tier_B_json=$($tierB.count) tier_C_sidecar=$($tierC.count) verdict=$verdict report=$Out"
exit 0
