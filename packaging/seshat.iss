; Inno Setup script for the Seshat desktop app.
; Build the PyInstaller onedir first (dist/Seshat), then compile this with
; the Inno Setup compiler (ISCC.exe packaging\seshat.iss) to produce
; dist/SeshatSetup.exe.

#define AppName "Seshat"
#define AppVersion "0.1.0"
#define AppPublisher "Dumee-25"
#define AppExe "Seshat.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=SeshatSetup
Compression=lzma2
SolidCompression=yes
; Per-user install: no admin prompt.
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=seshat.ico

[Files]
; The entire PyInstaller onedir output.
Source: "..\dist\Seshat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startuplaunch"; Description: "Start Seshat automatically at login"; GroupDescription: "Startup:"; Flags: unchecked

[Registry]
; Run at login, only if the user opted in. Per-user Run key, no admin needed.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Seshat"; ValueData: """{app}\{#AppExe}"""; \
    Tasks: startuplaunch; Flags: uninsdeletevalue

[Run]
; Offer to launch after install.
Filename: "{app}\{#AppExe}"; Description: "Launch Seshat"; Flags: nowait postinstall skipifsilent
