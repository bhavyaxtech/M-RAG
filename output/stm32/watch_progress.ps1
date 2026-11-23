param([switch]$Once)

# Read-only viewer: stopping this terminal does not stop the build workers.
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
$lastQueue = $null

do {
    try {
        $lastQueue = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'completion_status.json') -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        # The queue writes on stage transitions; keep the previous valid state
        # if this read happened during that brief write.
    }

    if (-not $Once) { Clear-Host }
    Write-Host '==============================================' -ForegroundColor Cyan
    Write-Host '          STM32 - LIVE BUILD PROGRESS' -ForegroundColor Cyan
    Write-Host '==============================================' -ForegroundColor Cyan
    Write-Host ("Refreshed: {0}  |  every 10 seconds" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
    Write-Host ''

    $queueAlive = $lastQueue -and (Get-Process -Id $lastQueue.wrapper_pid -ErrorAction SilentlyContinue)
    $status = if ($lastQueue.status -eq 'complete') { 'COMPLETE - ready for final review' }
        elseif ($lastQueue.status -eq 'failed') { 'FAILED - ask Codex to inspect the failure' }
        elseif ($queueAlive) { 'RUNNING' }
        else { 'NEEDS ATTENTION - completion worker is not running' }
    $color = if ($lastQueue.status -eq 'complete') { 'Green' }
        elseif ($lastQueue.status -eq 'failed' -or -not $queueAlive) { 'Red' }
        else { 'Yellow' }
    Write-Host $status -ForegroundColor $color
    Write-Host ("Current stage: {0}" -f $lastQueue.stage)
    if ($lastQueue.detail) { Write-Host $lastQueue.detail }
    Write-Host ''

    & $python -m scripts.collection_status
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Progress snapshot unavailable; will retry on the next refresh.' -ForegroundColor Yellow
    }

    $logName = switch ($lastQueue.stage) {
        'waiting_for_workers' { 'progressive_prepare_parallel.log' }
        'building' { 'full_build.log' }
        'cross_document_smoke' { 'full_smoke.log' }
        'local_api' { 'api_stderr.log' }
        'http_asset_verification' { 'app_verification.log' }
        'complete' { 'app_verification.log' }
        default { $null }
    }
    if ($logName) {
        Write-Host ''
        Write-Host ("Latest worker output ({0}):" -f $logName) -ForegroundColor Cyan
        Get-Content -LiteralPath (Join-Path $PSScriptRoot $logName) -Tail 6 -ErrorAction SilentlyContinue
    }
    Write-Host ''
    Write-Host 'Wait for COMPLETE, then message: "The build finished - verify it."'
    Write-Host 'If FAILED / NEEDS ATTENTION appears, message Codex immediately.'
    Write-Host 'COMPLETE means automated build/checks passed, not accuracy grading.'
    Write-Host 'Ctrl+C stops only this viewer. Keep the computer awake for the build.' -ForegroundColor DarkGray

    if ($Once -or $lastQueue.status -eq 'complete') { break }
    Start-Sleep -Seconds 10
} while ($true)
