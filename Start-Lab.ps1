$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimePython = Join-Path $projectRoot '.runtime\python\python.exe'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $labPython = $venvPython }
elseif (Test-Path -LiteralPath $runtimePython) { $labPython = $runtimePython }
else { $labPython = (Get-Command python -ErrorAction Stop).Source }
Push-Location -LiteralPath $projectRoot
try { & $labPython (Join-Path $projectRoot 'run_lab.py') }
finally { Pop-Location }
