; Luu file nay bang UTF-8 CO BOM. Inno Setup 6 can BOM moi doc dung tieng Viet co dau.
; Bien dich: build.py tu goi ISCC sau khi PyInstaller chay xong (can dist\Mindcare\).
#define MyAppName "Mindcare"
#define MyAppExeName "Mindcare.exe"
#define MyAppVersion "1.0.0"
#define MyPriceTable "bang_ten_thuoc_gia_tien.xlsx"

[Setup]
AppId={{B4C1E7A2-5D3F-4E86-9A1B-6F2D8C0E4A71}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
; Cai theo nguoi dung (khong can quyen Admin) de app ghi duoc bang gia nam canh exe.
DefaultDirName={localappdata}\Mindcare
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=Setup_Mindcare
SetupIconFile=mindcare.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "vietnamese"; MessagesFile: "compiler:Languages\Vietnamese.isl"

[Tasks]
; Khong dung co checkedonce: lan cai nao o nay cung duoc tich san, ke ca khi cai de.
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài Desktop"; GroupDescription: "Tùy chọn bổ sung:"

[Files]
Source: "dist\Mindcare\*"; DestDir: "{app}"; Excludes: "{#MyPriceTable}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bang gia: chi chep khi may dich chua co, de cai lai khong de mat bang gia nguoi dung da sua.
; uninsneveruninstall: go cai dat van giu lai bang gia.
Source: "dist\Mindcare\{#MyPriceTable}"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở {#MyAppName}"; Flags: nowait postinstall skipifsilent
