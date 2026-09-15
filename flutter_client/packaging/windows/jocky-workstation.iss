; Inno Setup script for the JOCKY forensic workstation.
;
; Requires Inno Setup on a Windows build machine. Build the release bundle
; with packaging\windows\build.ps1 first, then compile this script. The
; release workflow (.github/workflows/release.yml) does both on a
; windows-latest runner.

#define AppName "JOCKY Forensic Workstation"
#define AppVersion GetEnv("JOCKY_VERSION") != "" ? GetEnv("JOCKY_VERSION") : "0.9.0"
#define AppExe "jocky_client.exe"
#define BundleDir "..\..\build\windows\x64\runner\Release"

[Setup]
AppId={{8B1F3E2A-6C4D-4E77-9E2B-2C6E1D4F7A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=JOCKY
DefaultDirName={autopf}\JOCKY Workstation
DefaultGroupName=JOCKY
DisableProgramGroupPage=yes
OutputBaseFilename=jocky-workstation-{#AppVersion}-windows-x64-setup
; Installer lands with the other build output so CI can collect it by path.
OutputDir=..\..\..\build\windows\installer
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
WizardStyle=modern
PrivilegesRequired=admin

[Files]
; Complete Flutter and one-directory backend runtime bundle. The engine is
; listed separately as well: Inno Setup fails the compile when a named source
; is missing, so an installer can never be produced without an engine.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BundleDir}\backend\JOCKY-backend.exe"; DestDir: "{app}\backend"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[UninstallDelete]
; PyInstaller writes _internal at install time from the payload; remove the
; whole application directory so an uninstall leaves nothing behind. Operator
; investigations live in %LOCALAPPDATA%\JOCKY and are deliberately preserved.
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\data"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
