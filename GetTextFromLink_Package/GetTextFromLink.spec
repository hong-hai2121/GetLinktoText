# All generated files live inside GetTextFromLink_Package.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

package_dir = Path(SPECPATH)
root = package_dir.parent
stage = package_dir / "build" / "resources"
datas = [(str(root / "GetTextFromLink.ico"), "."), (str(stage), ".")]
binaries = []
hiddenimports = ["win32clipboard", "src.diagnostics"]
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "av"):
    data, libs, imports = collect_all(package)
    datas += data
    binaries += libs
    hiddenimports += imports
datas += collect_data_files("selenium")
datas += copy_metadata("yt-dlp", recursive=True)

a = Analysis(
    [str(root / "GetTextFromLink.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "torchaudio", "torchvision", "matplotlib", "pandas", "scipy", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="GetTextFromLink", console=False,
    icon=str(root / "GetTextFromLink.ico"), upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GetTextFromLink", upx=False)
