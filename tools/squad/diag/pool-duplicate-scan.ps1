# pool-duplicate-scan.ps1 — observability-only pool dedup scanner
# Spec anchor: .squad/identity/requirement-pool.md round-2 session 070234 (38/50)
# Reads requirement-pool.md, groups `### ` headers by normalized title,
# emits jsonl-style report of clusters with count >= 2 to .squad/audits/.
[CmdletBinding()]
param(
    [string]$Pool = ".squad/identity/requirement-pool.md",
    [string]$AuditDir = ".squad/audits"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Pool)) { Write-Error "pool not found: $Pool"; exit 1 }
$lines = Get-Content -LiteralPath $Pool
$groups = @{}
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -notmatch '^### ') { continue }
    $norm = ($line -replace '^### .*?\):\s*', '' -replace '^### \d{4}-\d{2}-\d{2}[^:]*:\s*', '' -replace '^### ', '').Trim().ToLower()
    if (-not $groups.ContainsKey($norm)) { $groups[$norm] = [System.Collections.ArrayList]::new() }
    [void]$groups[$norm].Add($i + 1)
}
$ts = Get-Date -Format 'yyyy-MM-dd-HHmm'
$reportPath = Join-Path $AuditDir "pool-duplicate-scan-$ts.json"
$tmp = "$reportPath.tmp"
$wasted = 0; $clusters = 0
$sb = New-Object System.Text.StringBuilder
foreach ($k in $groups.Keys) {
    if ($groups[$k].Count -lt 2) { continue }
    $clusters++; $wasted += ($groups[$k].Count - 1)
    $obj = [ordered]@{ normalized_title = $k; count = $groups[$k].Count; line_numbers = $groups[$k].ToArray() }
    [void]$sb.AppendLine(($obj | ConvertTo-Json -Compress -Depth 4))
}
if (-not (Test-Path $AuditDir)) { New-Item -ItemType Directory -Path $AuditDir -Force | Out-Null }
[System.IO.File]::WriteAllText($tmp, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $tmp -Destination $reportPath -Force
[Console]::Error.WriteLine("Found $clusters duplicate clusters, total wasted entries: $wasted")
[Console]::Error.WriteLine("Report: $reportPath")
exit 0
