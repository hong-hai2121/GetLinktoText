#define MyAppName "Thong ke hoa don MISA"
#define MyAppPublisher "HoaDonDienTuVaMiSa"
#define MyAppExeName "ThongKeHoaDonMISA.exe"
#define MyAppVersion "1.0.0"

[Setup]
AppId={{8F59A19E-9C8D-4D1D-ABDE-566592862C7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\HoaDonDienTuVaMiSa
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=Setup_ThongKeHoaDonMISA
SetupIconFile=..\assets\hoa_don_misa.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong ngoai Desktop"; GroupDescription: "Tuy chon bo sung:"; Flags: checkedonce

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\hoa_don_misa.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\hoa_don_misa.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\hoa_don_misa.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mo {#MyAppName}"; Flags: nowait postinstall skipifsilent
