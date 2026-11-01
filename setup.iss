; -------------------------------------------------------------------------
; Realtek HD Audio Universal Service - Inno Setup Script
; Stealth Windows Installer (No Desktop Icons, No Start Menu Shortcuts)
; -------------------------------------------------------------------------

#define MyAppName "Realtek HD Audio Universal Service"
#define MyAppPublisher "Realtek Semiconductor Corp."
#define MyAppVersion "2.0.0"
#define MyAppExeName "Realtek HD Audio Universal Service.exe"

[Setup]
AppId={{8B264E2A-98C1-4D6F-9E02-74895C9F1823}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=http://www.realtek.com/
AppSupportURL=http://www.realtek.com/
AppUpdatesURL=http://www.realtek.com/
DefaultDirName={commonpf}\Realtek\Audio\Service
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
DisableWelcomePage=no
OutputDir=setup_output
OutputBaseFilename=setup
SetupIconFile=app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\app_icon.ico
CreateUninstallRegKey=yes

; Crucial: Completely disable icon tasks so NO desktop shortcuts or start menu clutter are made
DisableFinishedPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\Realtek HD Audio Universal Service\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Intentionally left completely blank:
; 1. NO Desktop icon created.
; 2. NO Start Menu folder or program group created.
; Only registered in Windows Add/Remove Programs (Control Panel).

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start Realtek Audio Service"; Flags: nowait postinstall skipifsilent

