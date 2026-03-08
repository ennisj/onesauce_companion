$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m PyInstaller --noconfirm --clean OnesaUCECompanion.spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Built executable:"
Write-Host "  $root\dist\OnesaUCECompanion\OnesaUCECompanion.exe"
