; Per-user Inno Setup installer. Stable AppId across CPU/GPU builds/upgrades.
#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#ifndef Runtime
  #define Runtime "CPU"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\AccessibilityAI"
#endif

[Setup]
AppId={{DAC32F61-389D-4D71-8845-0EA1BFA34F18}
AppName=Audial-AI
AppVersion={#AppVersion}
AppPublisher=Audial-AI contributors
AppPublisherURL=https://github.com/Vedant-Sood/Audial-AI
AppSupportURL=https://github.com/Vedant-Sood/Audial-AI/issues
DefaultDirName={localappdata}\Programs\AudialAI
DefaultGroupName=Audial-AI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installers
OutputBaseFilename=Audial-AI-{#AppVersion}-Windows-x64-{#Runtime}-Setup
UninstallDisplayName=Audial-AI ({#Runtime})
UninstallDisplayIcon={app}\AccessibilityAI.exe
LicenseFile=..\LICENSE
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
Compression=lzma2/normal
SolidCompression=yes
DiskSpanning=no
CloseApplications=yes
CloseApplicationsFilter=AccessibilityAI.exe,AccessibilityAIWorker.exe
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Audial-AI {#Runtime} per-user setup
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "native-host.json"; DestDir: "{app}\native-host"; Flags: ignoreversion

[InstallDelete]
; Replace bundled libraries on upgrades, including CPU/NVIDIA switches. User
; models and settings live outside the installation directory.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Audial-AI"; Filename: "{app}\AccessibilityAI.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Audial-AI"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Audial-AI"; Filename: "{app}\AccessibilityAI.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\org.audialai.bridge"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host\native-host.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\org.audialai.bridge"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host\native-host.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\AccessibilityAI.exe"; Description: "Launch Audial-AI and set up local models"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  DeleteUserData := False;
  if UninstallSilent then
    DeleteUserData := ExpandConstant('{param:PURGEUSERDATA|0}') = '1'
  else
    DeleteUserData := MsgBox('Delete Audial-AI models, settings, logs and saved sessions for this Windows account?' + #13#10 + #13#10 +
      'Choose No to keep your data for reinstalling. This is the default.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExitCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and DeleteUserData then
  begin
    Exec(ExpandConstant('{app}\AccessibilityAIWorker.exe'), '--forget-model-token', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  end;
  if (CurUninstallStep = usPostUninstall) and DeleteUserData then
  begin
    if not DelTree(ExpandConstant('{localappdata}\AccessibilityAI'), True, True, True) then
      Log('Some user data could not be deleted. Close running sessions before removing it.');
  end;
end;
