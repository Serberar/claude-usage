; Instalador de Claude Usage (Inno Setup 6). Se compila con build.ps1, que le pasa la versión.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7F4AB592-8EFE-486C-AC71-466940D30782}
AppName=Claude Usage
AppVersion={#AppVersion}
AppPublisher=Sergio Bernabé
AppPublisherURL=https://github.com/Serberar/claude-usage
; para el usuario actual y sin pedir administrador: así la app puede actualizarse sola
PrivilegesRequired=lowest
DefaultDirName={autopf}\ClaudeUsage
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist
OutputBaseFilename=ClaudeUsage-Setup
SetupIconFile=claude_usage.ico
UninstallDisplayIcon={app}\claude_usage.ico
UninstallDisplayName=Claude Usage
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"
Name: "startup"; Description: "Abrir Claude Usage al iniciar Windows"

[Files]
Source: "dist\ClaudeUsage.exe"; DestDir: "{app}"; Flags: ignoreversion
; los accesos directos usan este .ico: si usaran el del .exe, Windows enseñaría el que
; guardó en caché para esa ruta aunque el .exe nuevo traiga otro
Source: "claude_usage.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Claude Usage"; Filename: "{app}\ClaudeUsage.exe";   IconFilename: "{app}\claude_usage.ico"
Name: "{autodesktop}\Claude Usage"; Filename: "{app}\ClaudeUsage.exe";   IconFilename: "{app}\claude_usage.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "ClaudeUsage"; ValueData: """{app}\ClaudeUsage.exe"" --tray"; \
  Tasks: startup; Flags: uninsdeletevalue
; la casilla de la app crea el mismo valor: se borra al desinstalar aunque no lo creara el instalador
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; \
  ValueName: "ClaudeUsage"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\ClaudeUsage.exe"; Description: "Abrir Claude Usage"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; suele estar abierta en la bandeja: sin cerrarla no se puede borrar el .exe
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ClaudeUsage.exe /F"; Flags: runhidden; \
  RunOnceId: "CerrarClaudeUsage"

[UninstallDelete]
; restos de las actualizaciones automáticas
Type: files; Name: "{app}\ClaudeUsage.old.exe"
Type: files; Name: "{app}\ClaudeUsage.new.exe"
