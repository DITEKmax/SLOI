param([switch]$SkipSmoke, [switch]$RangeDownloads)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'runtime\python'
$env:UV_PYTHON_BIN_DIR = Join-Path $Root 'runtime\bin'
$env:UV_CACHE_DIR = Join-Path $Root 'runtime\cache\uv'
$env:HF_HOME = Join-Path $Root 'models\.cache'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
if ($RangeDownloads) {
    $env:HF_HUB_DISABLE_XET = '1'
    $env:SLOI_MODEL_RANGE_DOWNLOAD = '1'
}
Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
$env:UV_LINK_MODE = 'copy'
$Cache = Join-Path $Root 'runtime\bootstrap'
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
$Log = Join-Path $Cache 'bootstrap.log'
Start-Transcript -Path $Log -Append | Out-Null
try {
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) { throw 'Windows x64 and 64-bit PowerShell are required.' }
    $LockPath = Join-Path $Root 'runtime\instance.lock'
    $Guard = [IO.File]::Open($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $Guard.Close()
    $GpuTool = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $GpuTool) { $GpuTool = Get-Item "$env:WINDIR\System32\nvidia-smi.exe" -ErrorAction SilentlyContinue }
    if (-not $GpuTool) { throw 'NVIDIA driver is not available. Install a current NVIDIA driver, then run install.bat again.' }
    & $GpuTool --query-gpu=name,memory.total,driver_version --format=csv,noheader
    if ($LASTEXITCODE -ne 0) { throw 'NVIDIA driver check failed.' }
    $Uv = Join-Path $Cache 'uv.exe'
    if (-not (Test-Path -LiteralPath $Uv)) {
        Write-Host '[1/6] Downloading verified uv bootstrap...'
        $Archive = Join-Path $Cache 'uv.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://releases.astral.sh/github/uv/releases/download/0.10.9/uv-x86_64-pc-windows-msvc.zip' -OutFile $Archive
        $Expected = 'f58dc40896000229db7c52b8bdd931394040ef2ad59abd1eda841f6d70b13d7a'
        if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLower() -ne $Expected) { throw 'uv checksum mismatch. Nothing was executed.' }
        $Stage = Join-Path $Cache 'unpack'
        Expand-Archive -LiteralPath $Archive -DestinationPath $Stage -Force
        $Binary = Get-ChildItem -LiteralPath $Stage -Filter uv.exe -Recurse | Select-Object -First 1
        if (-not $Binary) { throw 'uv.exe missing in verified archive.' }
        Copy-Item -LiteralPath $Binary.FullName -Destination $Uv -Force
        Remove-Item -LiteralPath $Stage -Recurse -Force
        Remove-Item -LiteralPath $Archive -Force
    }
    Write-Host '[2/6] Preparing project-local Python 3.13.5 and core environment...'
    & $Uv python install 3.13.5
    if ($LASTEXITCODE -ne 0) { throw 'Managed Python download failed. Re-run install.bat to resume.' }
    $Req = Join-Path $Root 'requirements\core.txt'
    $Fingerprint = (Get-FileHash -LiteralPath $Req -Algorithm SHA256).Hash.Substring(0,12).ToLower()
    $Core = Join-Path $Root "runtime\envs\core-313-$Fingerprint"
    $Python = Join-Path $Core 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        & $Uv venv --python 3.13.5 --managed-python $Core
        if ($LASTEXITCODE -ne 0) { throw 'Core environment could not be created.' }
    }
    & $Uv pip install --python $Python --only-binary :all: -r $Req
    if ($LASTEXITCODE -ne 0) { throw 'Core dependencies did not resolve. See runtime/bootstrap/bootstrap.log.' }
    if ([string]::IsNullOrWhiteSpace($env:SSL_CERT_FILE)) {
        $TrustBundle = Join-Path $Root 'runtime\certs\windows-roots.pem'
        $TrustBundleBuilder = @'
import base64
import pathlib
import ssl
import sys

certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
if not certificates:
    raise SystemExit('Windows trust stores returned no certificates.')

def pem(certificate):
    encoded = base64.b64encode(certificate).decode('ascii')
    lines = [encoded[offset:offset + 64] for offset in range(0, len(encoded), 64)]
    return '-----BEGIN CERTIFICATE-----\n' + '\n'.join(lines) + '\n-----END CERTIFICATE-----\n'

destination = pathlib.Path(sys.argv[1])
destination.parent.mkdir(parents=True, exist_ok=True)
temporary = destination.with_suffix(destination.suffix + '.partial')
temporary.write_text(''.join(pem(certificate) for certificate in certificates), encoding='ascii', newline='\n')
temporary.replace(destination)
print('Loaded', len(certificates), 'trusted Windows TLS certificates.')
'@
        & $Python -c $TrustBundleBuilder $TrustBundle
        if ($LASTEXITCODE -ne 0) { throw 'Windows TLS trust bundle could not be generated.' }
        $env:SSL_CERT_FILE = $TrustBundle
    }
    $Arguments = @('-m','sloi.installation','--root',$Root,'--uv',$Uv)
    if ($SkipSmoke) { $Arguments += '--skip-smoke' }
    & $Python @Arguments
    if ($LASTEXITCODE -notin @(0,2)) { throw 'Installation was not completed. See data/reports/install.json.' }
    $Code = $LASTEXITCODE
    if ($Code -eq 2) { Write-Host 'Installed with GPU test warnings. Read data/reports/diagnostics.txt before using affected models.' -ForegroundColor Yellow }
    Write-Host 'Next: start.bat' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Bootstrap report: $Log"
    $Code = 1
} finally {
    Stop-Transcript | Out-Null
}
exit $Code
