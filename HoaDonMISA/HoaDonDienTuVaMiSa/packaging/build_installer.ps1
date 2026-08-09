# Luu file nay bang UTF-8 CO BOM. Windows PowerShell 5.1 doc .ps1 khong BOM theo ANSI,
# lam hong ten file tieng Viet co dau ("Tên Sản Phẩm.xlsx") ben duoi.
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BuildVenv = Join-Path $ProjectDir ".build_venv"
$Python = Join-Path $BuildVenv "Scripts\python.exe"
$PyInstaller = Join-Path $BuildVenv "Scripts\pyinstaller.exe"
$AppName = "ThongKeHoaDonMISA"
$MainScript = Join-Path $ProjectDir "hoa_don_stats_web.py"
$IconPath = Join-Path $ProjectDir "assets\hoa_don_misa.ico"
$DistDir = Join-Path $ProjectDir "dist"
$BuildDir = Join-Path $ProjectDir "build"
$SpecFile = Join-Path $ProjectDir "$AppName.spec"
$InstallerScript = Join-Path $ProjectDir "packaging\installer.iss"
$CatalogPath = Join-Path $ProjectDir "Tên Sản Phẩm.xlsx"

if (-not (Test-Path $IconPath)) {
    throw "Khong tim thay icon: $IconPath"
}

if (-not (Test-Path -LiteralPath $CatalogPath)) {
    throw "Khong tim thay danh muc thuoc: $CatalogPath"
}

if (-not (Test-Path $BuildVenv)) {
    $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        & $PyLauncher.Source -3 -m venv $BuildVenv
    } else {
        & python -m venv $BuildVenv
    }
}

& $Python -m pip install --upgrade pip
& $Python -m pip install --upgrade pyinstaller

if (Test-Path $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
if (Test-Path $BuildDir) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}
if (Test-Path $SpecFile) {
    Remove-Item -LiteralPath $SpecFile -Force
}

# --add-data: nhung .ico vao exe de cua so Tk lay duoc icon ke ca khi chay exe roi.
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $AppName `
    --icon $IconPath `
    --add-data "$IconPath;assets" `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $ProjectDir `
    $MainScript

# Chep danh muc canh exe: ban portable (chay thang exe trong dist) cung co danh muc thuoc.
Copy-Item -LiteralPath $CatalogPath -Destination $DistDir -Force

Write-Host "Da tao file exe:" -ForegroundColor Green
Write-Host (Join-Path $DistDir "$AppName.exe")
Write-Host (Join-Path $DistDir (Split-Path -Leaf $CatalogPath))

if ($SkipInstaller) {
    exit 0
}

$InnoPath = $null
$InnoCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($InnoCommand) {
    $InnoPath = $InnoCommand.Source
} else {
    # winget cai Inno Setup vao localappdata (per-user), khong phai Program Files.
    $Candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            $InnoPath = $Candidate
            break
        }
    }
}

if (-not $InnoPath) {
    throw "Chua cai Inno Setup. Cai Inno Setup 6 (winget install JRSoftware.InnoSetup), sau do chay lai script nay de tao file cai dat .exe."
}

& $InnoPath $InstallerScript

Write-Host "Da tao file cai dat:" -ForegroundColor Green
Write-Host (Join-Path $ProjectDir "dist\installer\Setup_ThongKeHoaDonMISA.exe")
