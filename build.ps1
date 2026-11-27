param([string]$Python = "py")

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Force -Path 'build' | Out-Null
    & $Python -m PyInstaller --noconfirm --windowed --onefile --name PowerControl `
        --distpath dist --workpath build --specpath build main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
