param([int[]]$WaitForProcesses)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
$stage = 'waiting_for_workers'

function Save-CompletionStatus([string]$State, [string]$Detail = '') {
    @{
        checked_at = (Get-Date).ToString('o')
        stage = $stage
        status = $State
        detail = $Detail
        wrapper_pid = $PID
        waiting_for = $WaitForProcesses
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'completion_status.json') -Encoding utf8
}

try {
    Save-CompletionStatus 'running'
    if ($WaitForProcesses.Count) {
        Wait-Process -Id $WaitForProcesses -ErrorAction SilentlyContinue
    }
    $registry = Get-Content -LiteralPath (Join-Path $root 'corpora.json') -Raw | ConvertFrom-Json
    if (-not ($registry.corpora | Where-Object corpus_id -eq 'stm32')) {
        $stage = 'building'
        Save-CompletionStatus 'running'
        & $python -u -m scripts.ingest_collection --execute --stage all --caption-workers 4 *> (Join-Path $PSScriptRoot 'full_build.log')
        if ($LASTEXITCODE -ne 0) { throw "Collection build failed (exit $LASTEXITCODE); see full_build.log" }
    }
    $stage = 'cross_document_smoke'
    Save-CompletionStatus 'running'
    & $python -u -m scripts.smoke_collection --execute *> (Join-Path $PSScriptRoot 'full_smoke.log')
    if ($LASTEXITCODE -ne 0) { throw "Cross-document smoke failed (exit $LASTEXITCODE); see full_smoke.log" }

    $stage = 'local_api'
    Save-CompletionStatus 'running'
    $listener = Get-NetTCPConnection -LocalPort 8012 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $owners = @($listener | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($owners.Count -ne 1) { throw 'Port 8012 has ambiguous ownership; no server was stopped' }
        $processes = @(Get-CimInstance Win32_Process)
        $oldServer = $processes | Where-Object ProcessId -eq $owners[0]
        $oldLauncher = $processes | Where-Object ProcessId -eq $oldServer.ParentProcessId
        $expectedLauncherPrefix = '"' + $python + '"'
        if ($oldServer.CommandLine -notlike '* -m uvicorn api.server:app *' -or $oldServer.CommandLine -notmatch '--port\s+8012\b' -or -not $oldLauncher.CommandLine.StartsWith($expectedLauncherPrefix) -or $oldLauncher.CommandLine -notlike '* -m uvicorn api.server:app *') {
            throw 'Port 8012 is not owned by this workspace test server; no process was stopped'
        }
        Stop-Process -Id $oldServer.ProcessId -ErrorAction SilentlyContinue
        Stop-Process -Id $oldLauncher.ProcessId -ErrorAction SilentlyContinue
        Wait-Process -Id $oldServer.ProcessId,$oldLauncher.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
        # Process exit and the TCP listener disappearing can be observed at different times.
        # Wait for release without stopping any newly observed port owner.
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $listener = Get-NetTCPConnection -LocalPort 8012 -State Listen -ErrorAction SilentlyContinue
            if (-not $listener) { break }
            Start-Sleep -Seconds 1
        }
        if ($listener) { throw 'The old test server did not release port 8012' }
    }
    if (-not $listener) {
        $server = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'api.server:app', '--host', '127.0.0.1', '--port', '8012') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'api_stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'api_stderr.log') -PassThru
        @{ pid = $server.Id; port = 8012; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'api_process.json') -Encoding utf8
    }
    # Only the identified workspace test server is restarted after publication.
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8012/api/health' -TimeoutSec 5
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Local API did not become ready; see api_stderr.log' }
    $stage = 'http_asset_verification'
    Save-CompletionStatus 'running'
    & $python -u -m output.stm32.verify_app *> (Join-Path $PSScriptRoot 'app_verification.log')
    if ($LASTEXITCODE -ne 0) { throw "HTTP asset verification failed (exit $LASTEXITCODE); see app_verification.log" }
    $stage = 'complete'
    Save-CompletionStatus 'complete' 'Full collection indexed; structural smoke and HTTP asset checks passed. Answers remain ungraded.'
} catch {
    Save-CompletionStatus 'failed' $_.Exception.Message
    Write-Error $_
    exit 1
}
