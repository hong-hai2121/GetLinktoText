; Inno Setup script - dong goi "Xem Ads" (trinh xem bao cao quang cao Facebook offline)
; Bien dich:  ISCC.exe installer.iss   (hoac chay build qua Claude/PowerShell)
; Bo cai chi chep 4 file tinh + tao shortcut mo index.html - khong can Python tren may nguoi dung.

[Setup]
AppId={{7C1E9B7A-4A3F-4C0D-9B7E-XEMADS000001}
AppName=Xem Ads
AppVersion=1.0
AppPublisher=GetLinktoText
DefaultDirName={autopf}\XemAds
DisableProgramGroupPage=yes
DisableDirPage=no
AlwaysShowDirOnReadyPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=XemAds_Setup
SetupIconFile=xem_ads.ico
UninstallDisplayIcon={app}\xem_ads.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "vietnamese"; MessagesFile: "compiler:Languages\Vietnamese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "index.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "xlsx.full.min.js"; DestDir: "{app}"; Flags: ignoreversion
Source: "xem_ads.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Xem Ads"; Filename: "{app}\index.html"; IconFilename: "{app}\xem_ads.ico"
Name: "{autodesktop}\Xem Ads"; Filename: "{app}\index.html"; IconFilename: "{app}\xem_ads.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\index.html"; Description: "{cm:LaunchProgram,Xem Ads}"; Flags: postinstall shellexec skipifsilent
