; Inno Setup script for the Goggles Bridge installer. packaging/build_windows.py passes /DVersion
#define Name "Goggles Bridge Personal"
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{C4A17041-C777-4F12-9D54-403E784A964D}
AppName={#Name}
AppVersion={#Version}
AppPublisher=zjmdong and Goggles Bridge contributors
AppPublisherURL=https://github.com/zjmdong/g2-bridge-desktop
; installs for the current user, so no administrator prompt
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#Name}
DefaultGroupName={#Name}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=GogglesBridgePersonal-{#Version}-Setup
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

[UninstallDelete]
; Dedicated runtime directories can contain modules retired by an upgrade.
; Keep this list explicit: the user may have chosen a shared install directory.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_display_setup_internal"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\ffmpeg-stock"
Type: filesandordirs; Name: "{app}\ffmpeg-native"
Type: filesandordirs; Name: "{app}\licenses"
Type: files; Name: "{app}\GogglesBridgeWorker.exe"
Type: files; Name: "{app}\GogglesBridgeDisplaySetup.exe"

[Run]
Filename: "{app}\{#Name}.exe"; Description: "Open {#Name}"; Flags: nowait postinstall skipifsilent
; an update started from the app installs silently, so reopen the app afterward
Filename: "{app}\{#Name}.exe"; Flags: nowait; Check: WizardSilent

[Code]
#include "protected_runtime.iss"

type
  TAppTokenUser = record
    Sid, Attributes: Cardinal;
    SidStorage: array[0..67] of Byte;
  end;

var
  UninstallGate: THandle;

function AppOpenToken(Process: THandle; Access: Cardinal; var Token: THandle): Boolean;
  external 'OpenProcessToken@advapi32.dll stdcall';
function AppTokenUser(Token: THandle; InfoClass: Integer; var Info: TAppTokenUser;
  InfoSize: Cardinal; var ReturnSize: Cardinal): Boolean;
  external 'GetTokenInformation@advapi32.dll stdcall';
function AppSidString(Sid: Cardinal; var Text: Cardinal): Boolean;
  external 'ConvertSidToStringSidW@advapi32.dll stdcall';
function AppCopySidString(Destination: String; Source, Capacity: Cardinal): Cardinal;
  external 'lstrcpynW@kernel32.dll stdcall';
function AppSidStringLength(Text: Cardinal): Integer;
  external 'lstrlenW@kernel32.dll stdcall';
function AppCurrentProcess: THandle;
  external 'GetCurrentProcess@kernel32.dll stdcall';
function AppCreateMutex(Security: Integer; InitialOwner: Boolean; Name: String): THandle;
  external 'CreateMutexW@kernel32.dll stdcall';
function AppWait(Handle: THandle; Milliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function AppRelease(Handle: THandle): Boolean;
  external 'ReleaseMutex@kernel32.dll stdcall';
function AppClose(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function AppMutexName: String;
var
  Token: THandle;
  User: TAppTokenUser;
  Size, Text: Cardinal;
  SidLength: Integer;
begin
  if not AppOpenToken(AppCurrentProcess, 8, Token) then
    RaiseException('Cannot identify the app account.');
  try
    if not AppTokenUser(Token, 1, User, 76, Size) or
       not AppSidString(User.Sid, Text) then
      RaiseException('Cannot identify the app account.');
    try
      SidLength := AppSidStringLength(Text);
      Result := StringOfChar(#0, SidLength + 1);
      AppCopySidString(Result, Text, SidLength + 1);
      SetLength(Result, SidLength);
      Result := 'Global\GogglesBridge.' + Result;
    finally
      FreeSecurity(Text);
    end;
  finally
    AppClose(Token);
  end;
end;

procedure LockAppUninstall;
var
  Name: String;
  Status: Cardinal;
begin
  Name := AppMutexName;
  UninstallGate := AppCreateMutex(0, False, Name + '.Uninstall');
  if UninstallGate = 0 then RaiseException('Cannot lock the app for uninstall.');
  Status := AppWait(UninstallGate, 0);
  if (Status <> 0) and (Status <> $80) then begin
    AppClose(UninstallGate);
    UninstallGate := 0;
    RaiseException('Another setup or app startup is running. Retry uninstalling.');
  end;
  if CheckForMutexes(Name + '.Running') then
    RaiseException('Close all Goggles Bridge windows, including other Windows sessions, then retry uninstalling.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Keep the original GUI's removal action available. A sequential device ID
    cannot safely be adopted by this version after Windows has reused it. }
  if PreviousDevicePresent then
    Result := 'Remove the previous virtual display with the currently installed Goggles Bridge app or its display component in Windows Installed apps, then retry this update. The existing app has not been replaced.';
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  DriverFolder: String;
  DataFolder: String;
  ResultCode: Integer;
begin
  if Step = usUninstall then begin
    try
      LockAppUninstall;
    except
      SuppressibleMsgBox(GetExceptionMessage, mbError, MB_OK, IDOK);
      Abort;
    end;
    DriverFolder := ExpandConstant('{commonpf64}\Goggles Bridge Display');
    if FileExists(DriverFolder + '\unins000.exe') then begin
      try
        CheckProtectedRuntime;
      except
        SuppressibleMsgBox(GetExceptionMessage, mbError, MB_OK, IDOK);
        Abort;
      end;
      if not ShellExec('runas', DriverFolder + '\unins000.exe', '/SILENT /NORESTART',
                       DriverFolder, SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) or
         (ResultCode <> 0) then begin
        SuppressibleMsgBox('Virtual display removal did not finish. The app has been retained so you can retry from the setup guide.', mbError, MB_OK, IDOK);
        Abort;
      end;
    end else if DirExists(DriverFolder) or
                RegKeyExists(HKLM64, 'SOFTWARE\G2Bridge\GogglesBridgeDisplay') then begin
      SuppressibleMsgBox('Repair the virtual display component from the setup guide before uninstalling the app.', mbError, MB_OK, IDOK);
      Abort;
    end;
    DataFolder := ExpandConstant('{localappdata}\Goggles Bridge Personal');
    if DirExists(DataFolder) and not DelTree(DataFolder, True, True, True) then begin
      SuppressibleMsgBox('App data could not be removed. Close programs using the logs or settings and retry uninstalling.', mbError, MB_OK, IDOK);
      Abort;
    end;
  end;
end;

procedure DeinitializeUninstall;
begin
  if UninstallGate <> 0 then begin
    AppRelease(UninstallGate);
    AppClose(UninstallGate);
  end;
end;
