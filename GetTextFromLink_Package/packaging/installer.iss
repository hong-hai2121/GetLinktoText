#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif

[Setup]
AppId={{7FC54B8A-566D-4247-BC87-944D2D3B9101}
AppName=GetTextFromLink
AppVersion={#AppVersion}
AppPublisher=GetTextFromLink
DefaultDirName={localappdata}\Programs\GetTextFromLink
DefaultGroupName=GetTextFromLink
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=GetTextFromLink-Setup-{#AppVersion}-CPU-x64
SetupIconFile=..\..\GetTextFromLink.ico
UninstallDisplayIcon={app}\GetTextFromLink.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\GetTextFromLink\*"; DestDir: "{app}"; Excludes: "model.bin"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\GetTextFromLink\_internal\models\large-v3-turbo\model.bin"; DestDir: "{app}\_internal\models\large-v3-turbo"; Flags: ignoreversion nocompression
Source: "HUONG_DAN.html"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\GetTextFromLink"

[Icons]
Name: "{group}\GetTextFromLink"; Filename: "{app}\GetTextFromLink.exe"; WorkingDir: "{localappdata}\GetTextFromLink"
Name: "{group}\Huong dan su dung"; Filename: "{app}\HUONG_DAN.html"
Name: "{group}\Thu muc ket qua"; Filename: "{localappdata}\GetTextFromLink"
Name: "{autodesktop}\GetTextFromLink"; Filename: "{app}\GetTextFromLink.exe"; WorkingDir: "{localappdata}\GetTextFromLink"; Tasks: desktopicon

[Run]
Filename: "{app}\GetTextFromLink.exe"; Description: "Open GetTextFromLink"; Flags: nowait postinstall skipifsilent
