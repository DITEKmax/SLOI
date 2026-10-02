param([string]$Action = 'serve', [Parameter(ValueFromRemainingArguments=$true)][string[]]$Extra)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
try {
    $Active = Get-Content -LiteralPath (Join-Path $Root 'runtime\active.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $Python = Join-Path $Root $Active.environments.core
    if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment missing. Run install.bat.' }
    if ($Action -eq 'update') {
        & $Python -m sloi.updater --root $Root @Extra
    } else {
        & $Python -m sloi.cli --root $Root $Action @Extra
    }
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'Run install.bat first. Keep the project in a writable folder.'
    exit 1
}
