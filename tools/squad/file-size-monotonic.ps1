#requires -Version 5.1
<#
.SYNOPSIS
  Detect non-monotonic shrinkage of append-only Morpheus state files.

.DESCRIPTION
  Compares current byte-counts of .squad/identity/requirement-pool.md and
  .squad/memory/DECISION_TRAIL.md against the previous high-watermark stored
  in .squad/memory/file-size-watermark.json. If either file is now smaller
  than its prior watermark, emit STDERR warning + exit 2 (regression). On
  success, update the watermark JSON via atomic .tmp + Move-Item -Force.

  Filed round-4 brief 074758 — empirical anchor: pool 4363->4050 and trail
  3420->3004 observed across rounds 6→7 (parallel-writer truncation race).
  Read-only on pool/trail; writes only the watermark JSON.

.PARAMETER WatermarkPath
  Where to persist the watermark. Default: .squad/memory/file-size-watermark.json.

.PARAMETER NoUpdate
  If set, only check; do not advance the watermark even on growth.

.EXAMPLE
  pwsh -NoProfile -File tools/squad/file-size-monotonic.ps1
#>
[CmdletBinding()]
param(
    [string]$WatermarkPath = ".squad/memory/file-size-watermark.json",
    [switch]$NoUpdate
)

$ErrorActionPreference = 'Stop'
$tracked = @(
    @{ Name = 'requirement-pool'; Path = '.squad/identity/requirement-pool.md' },
    @{ Name = 'decision-trail';   Path = '.squad/memory/DECISION_TRAIL.md' }
)

$current = @{}
foreach ($t in $tracked) {
    if (-not (Test-Path $t.Path)) { Write-Error "missing: $($t.Path)"; exit 1 }
    $fi = Get-Item $t.Path
    $current[$t.Name] = @{ bytes = [int64]$fi.Length; mtime_unix = [int64](Get-Date $fi.LastWriteTimeUtc -UFormat %s) }
}

$prior = $null
if (Test-Path $WatermarkPath) {
    try { $prior = Get-Content $WatermarkPath -Raw | ConvertFrom-Json } catch { $prior = $null }
}

$regressed = @()
if ($prior) {
    foreach ($t in $tracked) {
        $priorBytes = $prior.$($t.Name).bytes
        $nowBytes = $current[$t.Name].bytes
        if ($priorBytes -and $nowBytes -lt $priorBytes) {
            $regressed += @{ name = $t.Name; prior = $priorBytes; now = $nowBytes; delta = ($nowBytes - $priorBytes) }
        }
    }
}

if ($regressed.Count -gt 0) {
    foreach ($r in $regressed) {
        Write-Error ("REGRESSION {0}: prior={1}B now={2}B delta={3}B" -f $r.name, $r.prior, $r.now, $r.delta)
    }
    exit 2
}

if (-not $NoUpdate) {
    $payload = @{
        schema_version  = 'v0'
        updated_utc8    = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        files           = $current
    } | ConvertTo-Json -Depth 4

    $tmp = "$WatermarkPath.tmp"
    Set-Content -LiteralPath $tmp -Value $payload -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $tmp -Destination $WatermarkPath -Force
}

Write-Output ("monotonic OK pool={0}B trail={1}B" -f $current['requirement-pool'].bytes, $current['decision-trail'].bytes)
exit 0
