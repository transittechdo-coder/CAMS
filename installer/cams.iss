; Inno Setup script: turns dist\CAMS into CAMS-Setup-<version>.exe
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\cams.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B1C3E2A-4D7F-4C9B-9E1A-CA35C0A11E01}
AppName=CAMS - Camera AI Management System
AppVersion={#AppVersion}
AppVerName=CAMS {#AppVersion}
AppPublisher=TransitTech
AppCopyright=TransitTech and Godwill Andrew Madunda
DefaultDirName={autopf}\CAMS
DefaultGroupName=CAMS
UninstallDisplayIcon={app}\CAMS.exe
SetupIconFile=cams.ico
OutputDir=Output
OutputBaseFilename=CAMS-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; CAMS needs no administrator rights: install for the current user, with no
; Windows permission prompt (like Scratch, VS Code, Zoom). An IT admin can still
; install for all users with:  CAMS-Setup.exe /ALLUSERS
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DisableProgramGroupPage=yes
; refresh Explorer so the new desktop icon shows at once
ChangesAssociations=yes
CloseApplications=yes
SetupLogging=yes
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start CAMS when this PC starts (recommended for the security office)"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\CAMS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\PRIVACY.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
; The desktop and Start menu shortcuts are always created (not optional).
Name: "{autodesktop}\CAMS"; Filename: "{app}\CAMS.exe"; WorkingDir: "{app}"; IconFilename: "{app}\CAMS.exe"; Comment: "Camera AI Management System"
Name: "{group}\CAMS"; Filename: "{app}\CAMS.exe"; WorkingDir: "{app}"; IconFilename: "{app}\CAMS.exe"; Comment: "Camera AI Management System"
Name: "{group}\CAMS user guide"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall CAMS"; Filename: "{uninstallexe}"
Name: "{userstartup}\CAMS"; Filename: "{app}\CAMS.exe"; WorkingDir: "{app}"; Tasks: autostart

[Run]
Filename: "{app}\CAMS.exe"; WorkingDir: "{app}"; Description: "Open CAMS now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userdesktop}\CAMS.lnk"

[Messages]
FinishedLabel=CAMS is installed and ready. Open it with the CAMS icon on your desktop or in the Start menu.%n%nThe first time, CAMS asks you to name your site and create your CAMS sign-in. Your data is kept in %APPDATA%\CAMS and is not removed if you uninstall.

[Code]
{ Close a running CAMS before installing over it, so files can be replaced. }
function InitializeSetup(): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM CAMS.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM CAMS.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := True;
end;

{ Safety net: if the desktop shortcut could not be made (for example a
  locked-down or redirected desktop), put one on the installing user's own desktop. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Target, Link: String;
begin
  if CurStep = ssPostInstall then
  begin
    Target := ExpandConstant('{app}\CAMS.exe');
    if not FileExists(ExpandConstant('{autodesktop}\CAMS.lnk')) then
    begin
      Link := ExpandConstant('{userdesktop}\CAMS.lnk');
      Log('All-users desktop shortcut missing; creating ' + Link);
      try
        CreateShellLink(Link, 'Camera AI Management System', Target, '',
          ExpandConstant('{app}'), Target, 0, SW_SHOWNORMAL);
      except
        Log('Could not create the user desktop shortcut: ' + GetExceptionMessage);
      end;
    end;
  end;
end;
