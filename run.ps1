$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = (Join-Path $scriptDir "src")
}
else {
    $env:PYTHONPATH = "$(Join-Path $scriptDir 'src');$env:PYTHONPATH"
}

python -m onesauce_companion.app

