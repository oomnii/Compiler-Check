# Build a source ZIP for manual publication (output OUTSIDE the repo root).
param(
    [string] $ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $OutZip = (Join-Path (Split-Path -Parent $ProjectRoot) "CompilerCheck-publication.zip")
)

Set-Location -LiteralPath $ProjectRoot
$stage = Join-Path $env:TEMP ("CompilerCheck_pub_" + [guid]::NewGuid().ToString("n"))
if (Test-Path -LiteralPath $OutZip) { Remove-Item -LiteralPath $OutZip -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

$excludeDirs = @(
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mctk_cache", ".mctk_probe_cache", ".dashboard_runs", ".mctk_work", ".mctk_work_fail",
    ".mctk_smoke_cache", "examples\.mctk_smoke_cache", "_smoke_dbg", ".pytest_runs_unknown",
    "mini_compiler_toolkit.egg-info"
)
$excludeFiles = @(
    "host_probe.json", "debug_report.txt", "debug_report.json",
    "normal.json", "normal.txt", "failure.json", "failure.txt"
)

$robArgs = @(
    $ProjectRoot, $stage,
    "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np",
    "/XF", "*.exe", "*.zip", "*.pyc"
)
foreach ($d in $excludeDirs) { $robArgs += "/XD"; $robArgs += $d }
foreach ($f in $excludeFiles) { $robArgs += "/XF"; $robArgs += $f }

$null = & robocopy @robArgs
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

$reportsStage = Join-Path $stage "reports"
if (Test-Path $reportsStage) {
    Get-ChildItem $reportsStage -File | Where-Object { $_.Extension -in ".json", ".txt" } | Remove-Item -Force
}

$toZip = Get-ChildItem -LiteralPath $stage -Force
if (-not $toZip) { throw "Staging directory is empty." }
Compress-Archive -Path ($toZip | ForEach-Object { $_.FullName }) -DestinationPath $OutZip -Force
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Created $OutZip ($((Get-Item -LiteralPath $OutZip).Length) bytes)"
