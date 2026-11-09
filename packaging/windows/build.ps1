$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$buildDir = Join-Path $repo "build\windows-agent"
$outputDir = Join-Path $repo "dist"
$pythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:ProgramFiles "Python312\python.exe")
)
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand -and $pythonCommand.Source -notlike "*\WindowsApps\*") {
    $pythonCandidates += $pythonCommand.Source
}
$pythonPath = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonPath) {
    throw "Python 3.12 is required. Install it from https://www.python.org/downloads/windows/ and reopen PowerShell."
}

$venvPython = Join-Path $buildDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    & $pythonPath -m venv (Join-Path $buildDir "venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not install pip build dependencies." }
& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install UDME packaging dependencies." }
& $venvPython -m pip install -e (Join-Path $repo "core") -e (Join-Path $repo "agent")
if ($LASTEXITCODE -ne 0) { throw "Could not install UDME agent packages." }

$agentDist = Join-Path $buildDir "agent-dist"
$agentWork = Join-Path $buildDir "agent-work"
$installerWork = Join-Path $buildDir "installer-work"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

& $venvPython -m PyInstaller --noconfirm --clean --onefile --name udme-agent `
    --paths (Join-Path $repo "core") --paths (Join-Path $repo "agent") `
    --collect-all sqlalchemy --collect-all cryptography `
    --distpath $agentDist --workpath $agentWork --specpath $buildDir `
    (Join-Path $PSScriptRoot "agent_entry.py")
if ($LASTEXITCODE -ne 0) { throw "Could not build udme-agent.exe." }

$agentExe = Join-Path $agentDist "udme-agent.exe"
& $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name UDME-Agent-Setup `
    --add-data "$agentExe;payload" `
    --distpath $outputDir --workpath $installerWork --specpath $buildDir `
    (Join-Path $PSScriptRoot "installer.py")
if ($LASTEXITCODE -ne 0) { throw "Could not build the installer." }

$installedAgent = Join-Path $outputDir "udme-agent.exe"
Copy-Item -LiteralPath $agentExe -Destination $installedAgent -Force
& $installedAgent --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The packaged agent failed its command-line smoke test." }

$setupExe = Join-Path $outputDir "UDME-Agent-Setup.exe"
& $setupExe --self-test
if ($LASTEXITCODE -ne 0) { throw "The installer failed its installation smoke test." }

Write-Host "Build successful:"
Write-Host "  Installer: $setupExe"
Write-Host "  Agent CLI: $installedAgent"
