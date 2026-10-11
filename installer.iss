; ═══════════════════════════════════════════════════════════════
;  installer.iss — Inno Setup script for the Aether Term installer
;
;  Creates a standard Windows installer with:
;    - Start Menu shortcut
;    - Desktop shortcut (optional)
;    - Uninstaller in Add/Remove Programs
;    - File associations (none needed)
;
;  Prerequisites:
;    1. Build Aether Term first:  build.bat
;    2. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
;    3. Compile: iscc installer.iss
;       — or —  Right-click installer.iss → Compile
;
;  Output: dist\Aether_Term_Setup_<version>.exe
; ═══════════════════════════════════════════════════════════════

#define MyAppName "Aether Term"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "KK4ODA"
#define MyAppURL "https://github.com/KK4ODA/aether-term"
#define MyAppExeName "Aether Term.exe"

[Setup]
; Same AppId as VARA Term: installing Aether Term upgrades a VARA Term install in place
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output installer to dist\ folder
OutputDir=dist
OutputBaseFilename=Aether_Term_Setup_{#MyAppVersion}
; Require admin only if installing to Program Files
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Compression
Compression=lzma2/max
SolidCompression=yes
; Close Aether Term (or VARA Term) if it is running before upgrading
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes
; UI
WizardStyle=modern
; Uncomment when you have an icon:
; SetupIconFile=resources\aether_term.ico
; UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Bundle the entire one-dir output
Source: "dist\Aether Term\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Source: dist\Aether Term\Aether Term.exe" alone — the .exe needs its DLLs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
