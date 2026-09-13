; Inno Setup script for the JOCKY forensic workstation.
;
; Not executed by this repository's automation: it requires Inno Setup on a
; Windows build machine. Build the release bundle with
; scripts\build_windows.ps1 first, then compile this script.

#define AppName "JOCKY Forensic Workstation"
#define AppVersion "0.2.0"
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
OutputBaseFilename=jocky-workstation-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
WizardStyle=modern
PrivilegesRequired=admin

[Files]
; Complete Flutter and one-directory backend runtime bundle.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
