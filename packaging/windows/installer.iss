#define AppName "DJI Goggles Streamer"
#define AppVersion "0.2.3"
#define Root "..\.."
[Setup]
AppId={{CDE1872A-4912-4C24-A51A-3F69CCF74302}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=G2 Bridge Community
AppPublisherURL=https://github.com/zjmdong/g2-bridge-desktop
AppSupportURL=https://github.com/zjmdong/g2-bridge-desktop/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#Root}\dist
OutputBaseFilename=DJI-Goggles-Streamer-{#AppVersion}-Setup
SetupIconFile={#Root}\build\app.ico
UninstallDisplayIcon={app}\DJI Goggles Streamer.exe
LicenseFile={#Root}\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "{#Root}\dist\DJI Goggles Streamer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\DJI Goggles Streamer.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\DJI Goggles Streamer.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\DJI Goggles Streamer.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
