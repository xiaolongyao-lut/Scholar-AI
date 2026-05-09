# pool-rotate-gate.ps1
# Scheduled-task gate wrapper for tools/squad/pool_rotate.py.
# Discharges .squad/specs/pool-rotate-trigger-policy.md §4 (named wrapper script
# implementing the §4 size-gated + quorum-token-gated invocation contract).
# Designed to be invoked by Windows Task Scheduler under the
# `Squad-Pool-Rotate-Gate` job (15-min cadence per §4).
#
# Implements the §4 4-step contract verbatim:
#   1. Get-Item .squad/identity/requirement-pool.md → reads file size in bytes.
#   2. If size < 800,000 bytes: exit 0, no-op.
#   3. Else: read .squad/state/pool-rotate-quorum-token.json. If a Morpheus has
#      authorised a rotation in the last 60 minutes (token unexpired), proceed.
#      Else: emit one warning line to .squad/audits/pool-rotate-gate-skipped-
#      YYYYMMDD.log and exit 0.
#   4. Else: write `### [<ts>] pool-rotate triggered (size=<bytes>,
#      quorum-token=<id>)` to DECISION_TRAIL.md (atomic .tmp + Move-Item -Force),
#      then invoke `python tools/squad/pool_rotate.py`.
#
# The 800KB threshold is L13488's number (per spec §4). The 60-minute quorum-
# token window matches pool-archival.md §3 manual-trigger-with-trail-record
# discipline: the scheduler is the EXECUTOR, but go/no-go authority remains a
# Morpheus quorum decision recorded in the token file (issued by Morpheus,
# read-but-not-written by this wrapper).
#
# Path-locked: this script reads pool, reads/writes audits, writes a single
# trail line via the trail_append.py serialised primitive, and execs
# pool_rotate.py (which holds its own pool lock). No new lock semantics here.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Get-Location).Path,
    [int]$ThresholdBytes = 800000,
    [int]$QuorumWindowMinutes = 60,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$poolPath        = Join-Path $RepoRoot '.squad/identity/requirement-pool.md'
$tokenPath       = Join-Path $RepoRoot '.squad/state/pool-rotate-quorum-token.json'
$trailAppendPath = Join-Path $RepoRoot '.squad/tools/trail_append.py'
$rotateScript    = Join-Path $RepoRoot 'tools/squad/pool_rotate.py'
$skipLogDate     = Get-Date -Format 'yyyyMMdd'
$skipLogPath     = Join-Path $RepoRoot ".squad/audits/pool-rotate-gate-skipped-$skipLogDate.log"

function Write-SkipLog {
    param([string]$Reason)
    $dir = Split-Path -Parent $skipLogPath
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] $Reason`n"
    # Append; per-line, no atomicity required for skip-log (advisory).
    Add-Content -LiteralPath $skipLogPath -Value $line -NoNewline
}

# --- Step 1: read pool size ---
if (-not (Test-Path -LiteralPath $poolPath)) {
    Write-SkipLog "pool not found at $poolPath"
    Write-Output "[pool-rotate-gate] pool missing; no-op"
    exit 0
}
$poolBytes = (Get-Item -LiteralPath $poolPath).Length
Write-Output "[pool-rotate-gate] pool_bytes=$poolBytes threshold=$ThresholdBytes"

# --- Step 2: short-circuit on under-threshold ---
if ($poolBytes -lt $ThresholdBytes) {
    Write-Output "[pool-rotate-gate] pool below 800KB threshold; no-op"
    exit 0
}

# --- Step 3: read quorum token ---
if (-not (Test-Path -LiteralPath $tokenPath)) {
    Write-SkipLog "pool over threshold ($poolBytes >= $ThresholdBytes) but no quorum token at $tokenPath"
    Write-Output "[pool-rotate-gate] no quorum token; skipped (logged)"
    exit 0
}

try {
    $tokenRaw = Get-Content -LiteralPath $tokenPath -Raw
    $token = $tokenRaw | ConvertFrom-Json
} catch {
    Write-SkipLog "quorum token at $tokenPath unparseable: $($_.Exception.Message)"
    Write-Output "[pool-rotate-gate] token unparseable; skipped (logged)"
    exit 0
}

# Token expiry check. issued_at + 60min must be > now.
$now = Get-Date
$expiresAt = $null
try {
    $expiresAt = [DateTime]::Parse($token.expires_at)
} catch {
    Write-SkipLog "quorum token expires_at unparseable: '$($token.expires_at)'"
    Write-Output "[pool-rotate-gate] token expires_at unparseable; skipped (logged)"
    exit 0
}

if ($expiresAt -lt $now) {
    Write-SkipLog "quorum token expired at $($token.expires_at) (now=$($now.ToString('o'))); issued_by=$($token.issued_by)"
    Write-Output "[pool-rotate-gate] token expired; skipped (logged)"
    exit 0
}

$tokenId = $token.issued_by
Write-Output "[pool-rotate-gate] valid token: issued_by=$tokenId expires=$($token.expires_at)"

# --- Step 4: trail-line + invoke pool_rotate.py ---
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$trailLine = @"

### [$ts UTC+8] pool-rotate triggered (size=$poolBytes, quorum-token=$tokenId)
- gate_script: tools/squad/pool-rotate-gate.ps1
- pool_bytes_pre: $poolBytes
- threshold_bytes: $ThresholdBytes
- token_issued_at: $($token.issued_at)
- token_expires_at: $($token.expires_at)
- trail_line_anchor: $($token.trail_line_anchor)
"@

if ($DryRun) {
    Write-Output "[pool-rotate-gate] DRY-RUN would write trail line:"
    Write-Output $trailLine
    Write-Output "[pool-rotate-gate] DRY-RUN would invoke $rotateScript"
    exit 0
}

# Atomic trail-line write via trail_append.py (serialised against parallel
# Morpheus instances + parallel scheduled-task firings via shared lockfile).
if (-not (Test-Path -LiteralPath $trailAppendPath)) {
    Write-Error "trail_append.py not found at $trailAppendPath"
    exit 1
}
$trailLine | & py -3 $trailAppendPath --stdin
if ($LASTEXITCODE -ne 0) {
    Write-Error "[pool-rotate-gate] trail_append.py failed exit=$LASTEXITCODE"
    exit 1
}
Write-Output "[pool-rotate-gate] trail-line appended"

# Invoke pool_rotate.py.
if (-not (Test-Path -LiteralPath $rotateScript)) {
    Write-Error "pool_rotate.py not found at $rotateScript"
    exit 1
}
$rotateOutput = & py -3 $rotateScript 2>&1 | Out-String
$rotateExit = $LASTEXITCODE
Write-Output "[pool-rotate-gate] pool_rotate exit=$rotateExit"
Write-Output $rotateOutput

# Per spec §4 the wrapper does NOT delete the token after consumption.
# Token expires naturally at expires_at; subsequent firings within the 60-min
# window will all be authorised by the same token. Anti-cherry-pick: if a
# Morpheus wants to authorise exactly one pass, it sets expires_at to a short
# window (e.g. issued_at + 16min so the next 15-min scheduled firing catches
# it but the one after does not).

exit $rotateExit
