; GUNK Installer script — Inno Setup 6
; Compile: ISCC installer.iss

#define MyAppName "GUNK"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ShelfHead"
#define MyAppURL "https://github.com/KobeMotmans/GUNK-Game-Project"
#define MyAppExeName "GUNK.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=GUNK_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
SetupIconFile=assets\textures\ui\icon.ico
UninstallDisplayIcon={app}\GUNK.exe
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"

[Tasks]
Name: "desktopicon"; Description: "Maak een snelkoppeling op het &bureaublad"; GroupDescription: "Extra snelkoppelingen:"; Flags: checkedonce

[Dirs]
Name: "{app}\_internal"

[Files]
Source: "assets\textures\ui\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\GUNK\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\GUNK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "{#MyAppExeName}"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\GUNK\cache"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} starten"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\attrib.exe"; Parameters: "+h ""{app}\_internal"""; Flags: runhidden

[UninstallRun]
Filename: "{sys}\attrib.exe"; Parameters: "-h ""{app}\_internal"""; Flags: runhidden
