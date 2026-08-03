; ARSM Suite Windows installer. The stable AppId enables in-place upgrades.
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ARSM-Suite"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif

[Setup]
AppId={{B86B4F4B-0E88-4A50-8C73-E2E0C62B5E10}
AppName=ARSM Suite
AppVersion={#AppVersion}
AppPublisher=ARSM Suite
DefaultDirName={localappdata}\Programs\ARSM Suite
DefaultGroupName=ARSM Suite
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=ARSM-Suite-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=force
RestartApplications=no
UninstallDisplayName=ARSM Suite
UninstallDisplayIcon={app}\ARSM-Suite.exe

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed.marker"; DestDir: "{app}"; DestName: "arsm-installed.marker"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ARSM Suite"; Filename: "{app}\ARSM-Suite.exe"
Name: "{autodesktop}\ARSM Suite"; Filename: "{app}\ARSM-Suite.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: unchecked

[Run]
Filename: "{app}\ARSM-Suite.exe"; Description: "启动 ARSM Suite"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if FileExists(ExpandConstant('{app}\ARSM-Suite.exe')) then
  begin
    Exec(ExpandConstant('{app}\ARSM-Suite.exe'), '--shutdown', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
    Sleep(15000);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\ARSM-Suite.exe')) then
  begin
    Exec(ExpandConstant('{app}\ARSM-Suite.exe'), '--shutdown', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;
  Result := '';
end;



