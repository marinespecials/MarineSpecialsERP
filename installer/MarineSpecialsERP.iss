; Inno Setup script - per-user install (no admin rights) so the app can update itself.
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppId={{6C2B7E3A-5D4F-4E1B-9C8A-3F7D2E1A9B60}
AppName=Marine Specials ERP
AppVersion={#AppVersion}
AppPublisher=Marine Specials
DefaultDirName={localappdata}\Programs\MarineSpecialsERP
DefaultGroupName=Marine Specials ERP
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=MarineSpecialsERP-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\MarineSpecialsERP.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\MarineSpecialsERP\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Marine Specials ERP"; Filename: "{app}\MarineSpecialsERP.exe"
Name: "{userdesktop}\Marine Specials ERP"; Filename: "{app}\MarineSpecialsERP.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MarineSpecialsERP.exe"; Description: "Start Marine Specials ERP"; Flags: nowait postinstall skipifsilent
