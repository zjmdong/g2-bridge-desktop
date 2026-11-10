param([string]$Iscc = "$PSScriptRoot\..\..\work\tools\InnoSetup\ISCC.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Push-Location $projectRoot
try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    & $python packaging/windows/verify_sdk.py
    if ($LASTEXITCODE) { throw 'SDK baseline differs' }
    & $python packaging/windows/prepare.py
    if ($LASTEXITCODE) { throw 'Dependency preparation failed' }
    Copy-Item -LiteralPath (Join-Path (Split-Path $Iscc) 'license.txt') -Destination 'vendor/licenses/InnoSetup-LICENSE.txt'
    & $python -m unittest discover -s desktop_tests
    if ($LASTEXITCODE) { throw 'Desktop tests failed' }
    & $python -m PyInstaller --noconfirm packaging/windows/streamer.spec
    if ($LASTEXITCODE) { throw 'Application build failed' }
    & $python packaging/windows/smoke_worker.py 'dist/DJI Goggles Streamer'
    if ($LASTEXITCODE) { throw 'Packaged worker smoke test failed' }
    & $Iscc packaging/windows/installer.iss
    if ($LASTEXITCODE) { throw 'Installer build failed' }
    & $python packaging/windows/source_bundle.py
    if ($LASTEXITCODE) { throw 'Source bundle failed' }
    Get-FileHash 'dist\DJI-Goggles-Streamer-0.0.1-Setup.exe' -Algorithm SHA256
} finally { Pop-Location }
