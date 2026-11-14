; Inno Setup script for the Goggles Bridge installer. packaging/build_windows.py passes /DVersion
#define Name "Goggles Bridge"
#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Repository
  #define Repository "Ammaar-Alam/goggles-bridge"
#endif

[Setup]
AppId={{4BEF1AEE-4D83-4F9B-9B91-C31BE10F9FB1}
AppName={#Name}
AppVersion={#Version}
AppPublisher=Goggles Bridge contributors
AppPublisherURL=https://github.com/{#Repository}
; installs for the current user, so no administrator prompt
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#Name}
DefaultGroupName={#Name}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=GogglesBridge-{#Version}-Setup
SetupIconFile=goggles-bridge.ico
UninstallDisplayIcon={app}\{#Name}.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\{#Name}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#Name}"; Filename: "{app}\{#Name}.exe"
Name: "{autodesktop}\{#Name}"; Filename: "{app}\{#Name}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Name}.exe"; Description: "Open {#Name}"; Flags: nowait postinstall skipifsilent
; an update started from the app installs silently, so reopen the app afterward
Filename: "{app}\{#Name}.exe"; Flags: nowait; Check: ReopenAfterUpdate

[Code]
function ReopenAfterUpdate: Boolean;
var
  I: Integer;
begin
  Result := WizardSilent;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOREOPEN') = 0 then
      Result := False;
end;
