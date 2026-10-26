; Inno Setup script: turns dist\CAMS into CAMS-Setup-<version>.exe
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\cams.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B1C3E2A-4D7F-4C9B-9E1A-CA35C0A11E01}
AppName=CAMS - Camera AI Monitoring System
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
PrivilegesRequired=admin
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start CAMS when this PC starts (recommended for the security office)"; GroupDescription: "Startup:"; Flags: unchecked
Name: "lan"; Description: "Let other computers on this network open CAMS (opens port 8765 in the firewall)"; GroupDescription: "Network:"; Flags: unchecked

[Files]
Source: "..\dist\CAMS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\PRIVACY.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\CAMS"; Filename: "{app}\CAMS.exe"; Parameters: "{code:LanArg}"
Name: "{group}\CAMS user guide"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall CAMS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CAMS"; Filename: "{app}\CAMS.exe"; Parameters: "{code:LanArg}"; Tasks: desktopicon
Name: "{userstartup}\CAMS"; Filename: "{app}\CAMS.exe"; Parameters: "{code:LanArg}"; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""CAMS"" dir=in action=allow protocol=TCP localport=8765 profile=private,domain"; Flags: runhidden; Tasks: lan
Filename: "{app}\CAMS.exe"; Parameters: "{code:LanArg}"; Description: "Open CAMS now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""CAMS"""; Flags: runhidden; RunOnceId: "RemoveFirewall"

[Messages]
FinishedLabel=CAMS is installed. Your data (people, faces, sightings) is kept in %APPDATA%\CAMS and is not removed if you uninstall.

[Code]
function LanArg(Param: String): String;
begin
  if WizardIsTaskSelected('lan') then Result := '--lan' else Result := '';
end;
