; Kandha per-user installer. Same AppId as Audial-AI so one install upgrades the other
; (decision 0008); the payload is the Audial-AI PyInstaller folder, which contains Kandha.exe.
#ifndef AppVersion
  #define AppVersion "0.6.0"
#endif
#ifndef Runtime
  #define Runtime "CPU"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\AccessibilityAI"
#endif

[Setup]
AppId={{DAC32F61-389D-4D71-8845-0EA1BFA34F18}
AppName=Kandha
AppVersion={#AppVersion}
AppVerName=Kandha {#AppVersion}
AppPublisher=Audial-AI contributors
AppPublisherURL=https://github.com/Vedant-Sood/Audial-AI
AppSupportURL=https://github.com/Vedant-Sood/Audial-AI/issues
DefaultDirName={localappdata}\Programs\AudialAI
DefaultGroupName=Kandha
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installers
OutputBaseFilename=Kandha-Setup-{#AppVersion}
UninstallDisplayName=Kandha {#AppVersion} ({#Runtime}, with Audial-AI)
UninstallDisplayIcon={app}\Kandha.exe
LicenseFile=..\LICENSE
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
Compression=lzma2/normal
SolidCompression=yes
DiskSpanning=no
CloseApplications=yes
CloseApplicationsFilter=Kandha.exe,AccessibilityAI.exe,AccessibilityAIWorker.exe
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Kandha {#Runtime} per-user setup
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut for Kandha"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "native-host.json"; DestDir: "{app}\native-host"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Kandha"; Filename: "{app}\Kandha.exe"; WorkingDir: "{app}"; Comment: "Captions, who is speaking, and the Kandha Stole"
Name: "{group}\Audial-AI workspace"; Filename: "{app}\AccessibilityAI.exe"; WorkingDir: "{app}"
; HTML rendering made at build time (AccessibilityAI.spec): stock Windows opens .html in the browser but has no program for .md.
Name: "{group}\Kandha user guide"; Filename: "{app}\_internal\docs\kandha\USER_GUIDE.html"; Comment: "Opens in your web browser; works offline"
Name: "{group}\Uninstall Kandha"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Kandha"; Filename: "{app}\Kandha.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\org.audialai.bridge"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host\native-host.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\org.audialai.bridge"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host\native-host.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\Kandha.exe"; Description: "Open Kandha"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeleteUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  DeleteUserData := False;
  if UninstallSilent then
    DeleteUserData := ExpandConstant('{param:PURGEUSERDATA|0}') = '1'
  else
    DeleteUserData := MsgBox('Delete Kandha and Audial-AI models, settings, saved rooms, logs and saved sessions for this Windows account?' + #13#10 + #13#10 +
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
