<#
.SYNOPSIS
    Drive a packaged JOCKY Windows application the way a user would.

.DESCRIPTION
    Runs against the FINAL artifact -- an unpacked portable archive or an
    installed directory -- not against the repository checkout. A build that
    only proves `flutter build windows` succeeded proves nothing about whether
    the thing you ship starts: the Linux release shipped once with no backend
    directory at all, and the failure surfaced as a misleading error about a
    port the engine never uses.

    So this locates the bundled engine inside the artifact, starts it over the
    same NDJSON bootstrap channel the desktop client uses, and then exercises
    the API over the port and per-process token the engine chose. Everything it
    does is read-only.

    It proves the Windows application packaging and runtime work. It does not
    prove the Windows forensic collectors work on any given Windows host --
    that is a separate question and is recorded separately.

.PARAMETER Bundle
    The unpacked application directory to test.
#>
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [int]$ReadyTimeoutSeconds = 120,
    [int]$CollectTimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Fail($message) {
    Write-Host "   PROBLEM: $message" -ForegroundColor Red
    exit 1
}

function Step($message) { Write-Host "   $message" }

Write-Host '=============================================================================='
Write-Host '  JOCKY WINDOWS PACKAGED RUNTIME SMOKE TEST'
Write-Host '=============================================================================='
Write-Host ''

$Bundle = (Resolve-Path $Bundle).Path
Write-Host "  Artifact: $Bundle"
Write-Host ''

Write-Host '-- 1. The artifact carries everything it needs -------------------------'
$engine = Join-Path $Bundle 'backend\JOCKY-backend.exe'
$client = Join-Path $Bundle 'jocky_client.exe'

foreach ($required in @($client, $engine, (Join-Path $Bundle 'backend\_internal'))) {
    if (-not (Test-Path $required)) { Fail "missing from the artifact: $required" }
    Step "ok      $($required.Substring($Bundle.Length + 1))"
}

# Data the engine reads at import time. A missing one is not a degraded feature:
# the module fails to import and the engine does not start at all, which is how
# the Linux build was once found to be shipping without its grammar.
$data = @(
    'backend\_internal\compiler\grammar.lark',
    'backend\_internal\compiler\investigation.lark',
    'backend\_internal\analysis\data\driver_risk_reference.json',
    'backend\_internal\analysis\data\software_reference.json'
)
foreach ($relative in $data) {
    $path = Join-Path $Bundle $relative
    if (-not (Test-Path $path)) { Fail "bundled data missing: $relative" }
    Step "ok      $relative"
}

# No developer Python may be required. The engine is a frozen one-directory
# build and must carry its own interpreter.
$runtime = Get-ChildItem (Join-Path $Bundle 'backend\_internal') -Filter 'python*.dll' -File `
           -ErrorAction SilentlyContinue
if (-not $runtime) { Fail 'the artifact contains no Python runtime; it would need one installed' }
Step "ok      bundled interpreter: $($runtime[0].Name)"

Write-Host ''
Write-Host '-- 2. Start the bundled engine as the client does -----------------------'
$workspace = Join-Path ([System.IO.Path]::GetTempPath()) ("jocky-smoke-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force $workspace | Out-Null
$bootstrap = Join-Path $workspace 'bootstrap.ndjson'
$errors = Join-Path $workspace 'engine.err'

# The engine holds stdin open for as long as its owner lives and announces its
# port, token and instance id on stdout. That is the whole bootstrap protocol.
$process = Start-Process -FilePath $engine `
    -ArgumentList @('--workspace', $workspace) `
    -RedirectStandardOutput $bootstrap -RedirectStandardError $errors `
    -PassThru -WindowStyle Hidden

try {
    $ready = $null
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $bootstrap) {
            $ready = Get-Content $bootstrap -ErrorAction SilentlyContinue |
                     Where-Object { $_ -match '"event":\s*"ready"' } | Select-Object -First 1
            if ($ready) { break }
        }
        if ($process.HasExited) {
            Write-Host (Get-Content $errors -Tail 20 -ErrorAction SilentlyContinue)
            Fail "the engine exited with code $($process.ExitCode) before becoming ready"
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Write-Host (Get-Content $errors -Tail 20 -ErrorAction SilentlyContinue)
        Fail "the engine did not become ready within $ReadyTimeoutSeconds seconds"
    }

    $boot = $ready | ConvertFrom-Json
    $port = $boot.port
    $token = $boot.token
    $instance = $boot.instance_id
    if (-not $port -or -not $token -or -not $instance) {
        Fail "the bootstrap line is incomplete: $ready"
    }
    Step "engine ready on port $port with a per-process token"
    Step "instance $($instance.Substring(0, 8)), engine version $($boot.versions.application)"

    $api = "http://127.0.0.1:$port"
    $headers = @{ 'Authorization' = "Bearer $token"; 'X-Jocky-Instance' = $instance }

    function Get-Api($path) {
        Invoke-RestMethod -Uri "$api$path" -Headers $headers -Method Get -TimeoutSec 120
    }
    function Post-Api($path, $body) {
        Invoke-RestMethod -Uri "$api$path" -Headers $headers -Method Post `
            -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress -Depth 6) `
            -TimeoutSec 600
    }

    Write-Host ''
    Write-Host '-- 3. The application and engine handshake -----------------------------'
    $health = Get-Api '/api/v1/health'
    if (-not $health.ready) { Fail 'the engine did not report ready over its own API' }
    Step "health: ready, version $($health.versions.application), schema $($health.versions.database_schema)"

    if ($health.instance_id -ne $instance) {
        Fail 'the health reply belongs to a different engine instance'
    }
    Step 'the health reply carries the instance the bootstrap announced'

    # The credential has to matter. An engine that answers without it is not
    # loopback-only in any meaningful sense.
    try {
        Invoke-WebRequest -Uri "$api/api/v1/health" -Method Get -TimeoutSec 30 `
            -UseBasicParsing | Out-Null
        Fail 'an unauthenticated request was answered'
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ne 401) { Fail "an unauthenticated request returned $code, expected 401" }
        Step 'an unauthenticated request is refused (401)'
    }

    $capabilities = Get-Api '/api/v1/capabilities'
    Step "platform reported by the packaged engine: $($capabilities.historical_execution_platform)"
    $sources = Get-Api '/api/v1/collection-sources'
    Step "collectors advertised: $($sources.selectable.Count) selectable, $($sources.baseline.Count) baseline"

    Write-Host ''
    Write-Host '-- 4. A minimal read-only workflow -------------------------------------'
    $case = Post-Api '/api/v1/investigations' @{ title = 'Windows packaged runtime smoke test' }
    if (-not $case.id) { Fail 'no investigation was created' }
    Step "investigation $($case.id) created"

    # Read-only by construction: a short window, one file JOCKY only hashes, and
    # collectors that observe. Nothing here writes to the machine.
    $collected = Post-Api "/api/v1/investigations/$($case.id)/collect" @{
        paths          = @("$env:SystemRoot\System32\notepad.exe")
        window_hours   = 1
        sources        = @('NETWORK')
    }
    Step 'collection requested with a one-hour window and one file to hash'

    $status = $null
    $deadline = (Get-Date).AddSeconds($CollectTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $transitions = Get-Api "/api/v1/investigations/$($case.id)/transitions"
        $status = ($transitions.items | Select-Object -Last 1).state
        if ($status -in @('completed', 'partially_completed', 'failed', 'cancelled')) { break }
        Start-Sleep -Seconds 2
    }
    if ($status -eq 'failed' -or -not $status) {
        Fail "collection did not complete (state: $(if ($status) { $status } else { 'none' }))"
    }
    Step "collection finished: $status"

    $evidence = Get-Api "/api/v1/investigations/$($case.id)/evidence"
    if ($evidence.items.Count -lt 1) { Fail 'the collection produced no evidence records' }
    Step "$($evidence.items.Count) evidence record(s): $(($evidence.items.type | Select-Object -Unique) -join ', ')"

    $report = Get-Api "/api/v1/investigations/$($case.id)/reports"
    if ($report.items.Count -lt 1) { Fail 'no report was issued' }
    Step 'a report was issued and stored'

    # The investigator report, rendered by the packaged engine's own reportlab
    # and its own bundled fonts.
    $pdf = Join-Path $workspace 'report.pdf'
    Invoke-WebRequest -Uri "$api/api/v1/investigations/$($case.id)/report/export" `
        -Headers $headers -Method Post -ContentType 'application/json' `
        -Body '{"format":"pdf"}' -OutFile $pdf -TimeoutSec 300 -UseBasicParsing
    $magic = [System.IO.File]::ReadAllBytes($pdf)[0..3]
    if ((($magic | ForEach-Object { [char]$_ }) -join '') -ne '%PDF') {
        Fail 'the exported report is not a PDF'
    }
    # Pages from the document's own page tree. Counting /Type /Page objects with
    # a line-based search returns zero, because the object spans a newline --
    # which would make this check pass on any file.
    $text = [System.IO.File]::ReadAllText($pdf, [System.Text.Encoding]::Latin1)
    $match = [regex]::Match($text, '/Count\s+(\d+)')
    if (-not $match.Success) { Fail 'the report has no page tree' }
    $pages = [int]$match.Groups[1].Value
    Step "investigator report: $pages pages, $((Get-Item $pdf).Length) bytes"

    $offered = Get-Api "/api/v1/investigations/$($case.id)/artifacts-available"
    if ($offered.investigator_report.pages -ne $pages) {
        Fail "the engine advertised $($offered.investigator_report.pages) pages but produced $pages"
    }
    Step 'the advertised page count matches the document'

    Write-Host ''
    Write-Host '-- 5. Shut down cleanly -------------------------------------------------'
    Post-Api '/api/v1/shutdown' @{} | Out-Null
    if (-not $process.WaitForExit(30000)) { Fail 'the engine did not exit when asked' }
    if ($process.ExitCode -ne 0) { Fail "the engine exited with code $($process.ExitCode)" }
    Step 'the engine shut down on request with exit code 0'

    Write-Host ''
    Write-Host '-- Result ---------------------------------------------------------------'
    Write-Host '   WINDOWS APPLICATION BUILD:     VALIDATED'
    Write-Host '   WINDOWS PACKAGED RUNTIME:      VALIDATED'
    Write-Host '   WINDOWS FORENSIC HOST:         NOT VALIDATED by this test.'
    Write-Host '     This proves the packaged application starts, serves its own API and'
    Write-Host '     completes a read-only workflow on a GitHub Windows runner. It does not'
    Write-Host '     establish that the Windows forensic collectors read what they should on'
    Write-Host '     a real investigated host.'
    Write-Host ''
    Write-Host '   RESULT: PASSED' -ForegroundColor Green
    exit 0
} finally {
    if ($process -and -not $process.HasExited) { $process.Kill() }
    Remove-Item $workspace -Recurse -Force -ErrorAction SilentlyContinue
}
