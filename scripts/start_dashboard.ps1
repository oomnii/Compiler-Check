# Stop anything listening on the dashboard port, then start CompilerCheck UI.
param(
    [int] $Port = 8765,
    [string] $ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $pids) {
    if ($procId -and $procId -ne 0) {
        Write-Host "Stopping PID $procId (was listening on $Port)..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Set-Location $ProjectRoot
Write-Host "Starting CompilerCheck on http://127.0.0.1:$Port (look for green header + title CompilerCheck)"
python -m mctk.dashboard --project-root $ProjectRoot --port $Port
