# Compila dist\ClaudeUsage.exe y dist\ClaudeUsage-Setup.exe con la versión de version.py.
# Sin ErrorActionPreference=Stop: pyinstaller escribe su log en stderr y PowerShell 5.1 lo
# tomaría por un error. Se mira el código de salida de cada paso.
#
# -Only exe        solo el .exe
# -Only installer  solo el instalador, con el .exe que ya haya en dist (en GitHub Actions se
#                  firma el .exe entre un paso y otro, para que el instalador lleve el firmado)
param([ValidateSet("all", "exe", "installer")][string]$Only = "all")

Set-Location $PSScriptRoot

$version = (Select-String -Path version.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Compilando Claude Usage $version ($Only)"

if ($Only -ne "installer") {
    python make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "make_icon.py falló" }
    python make_version_info.py
    if ($LASTEXITCODE -ne 0) { throw "make_version_info.py falló" }
    pyinstaller --noconfirm --onefile --windowed --name ClaudeUsage --icon claude_usage.ico `
        --version-file build\version_info.txt `
        --add-data "claude_usage.ico;." --hidden-import pystray._win32 `
        --collect-data customtkinter claude_usage.pyw
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller falló" }
}

if ($Only -ne "exe") {
    if (-not (Test-Path dist\ClaudeUsage.exe)) { throw "Falta dist\ClaudeUsage.exe: compila antes el .exe" }
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $iscc = Get-ChildItem "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $iscc) { throw "Falta Inno Setup 6 (winget install JRSoftware.InnoSetup)" }
    & $iscc "/DAppVersion=$version" installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup falló" }
}

Write-Host "Listo (v$version): $(Get-ChildItem dist\*.exe | ForEach-Object Name)"
