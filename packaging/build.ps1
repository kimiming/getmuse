# Build both exes, then assemble a clean, versioned portable package.
# Version comes from muse_auto/__init__.py (bump it before a release).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name MuseAuto --distpath dist --workpath build\gui --paths . `
        --collect-submodules muse_auto --collect-all xlrd --collect-all xlwt `
        packaging/gui_entry.py
    if ($LASTEXITCODE -ne 0) { throw "GUI PyInstaller 失败" }

    python -m PyInstaller --noconfirm --clean --onefile --console `
        --name MuseAutoCLI --distpath dist --workpath build\cli --paths . `
        --collect-submodules muse_auto --collect-all xlrd --collect-all xlwt `
        packaging/cli_entry.py
    if ($LASTEXITCODE -ne 0) { throw "CLI PyInstaller 失败" }

    python packaging/build_portable.py
    if ($LASTEXITCODE -ne 0) { throw "便携包组装失败" }
}
finally {
    Pop-Location
}
