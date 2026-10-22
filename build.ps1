# Compila dist\ClaudeUsage.exe y dist\ClaudeUsage-Setup.exe con la versión de claude_usage.pyw.
# Sin ErrorActionPreference=Stop: pyinstaller escribe su log en stderr y PowerShell 5.1 lo
# tomaría por un error. Se mira el código de salida de cada paso.
Set-Location $PSScriptRoot

$version = (Select-String -Path claude_usage.pyw -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Compilando Claude Usage $version"

python make_icon.py
pyinstaller --noconfirm --onefile --windowed --name ClaudeUsage --icon claude_usage.ico `
    --add-data "claude_usage.ico;." --hidden-import pystray._win32 `
    --collect-data customtkinter claude_usage.pyw
if ($LASTEXITCODE -ne 0) { throw "pyinstaller falló" }

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = Get-ChildItem "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $iscc) { throw "Falta Inno Setup 6 (winget install JRSoftware.InnoSetup)" }
& $iscc "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falló" }

Write-Host "Listo: dist\ClaudeUsage.exe y dist\ClaudeUsage-Setup.exe (v$version)"
