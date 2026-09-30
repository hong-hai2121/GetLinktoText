"""Build the CPU edition: python packaging/build_installer.py (Python 3.12 x64)."""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".build-gettext"
STAGE = ROOT / "build" / "gettext" / "resources"
DENO_VERSION = "v2.9.7"
DENO_SHA256 = "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238"


def run(args):
    print("Running:", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def stage_deno(destination):
    archive = ROOT / "build" / "gettext" / f"deno-{DENO_VERSION}.zip"
    if not archive.is_file():
        url = f"https://github.com/denoland/deno/releases/download/{DENO_VERSION}/deno-x86_64-pc-windows-msvc.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "GetTextFromLink-build"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != DENO_SHA256:
            raise RuntimeError(f"Deno checksum mismatch: {archive}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        destination.write_bytes(package.read("deno.exe"))


def find_ffmpeg_bin(explicit):
    candidates = [Path(explicit)] if explicit else []
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found).parent)
    candidates += list(Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")).glob(
        "chocolatey/lib/ffmpeg*/tools/ffmpeg/bin"))
    for candidate in candidates:
        exe = candidate / "ffmpeg.exe"
        probe = candidate / "ffprobe.exe"
        # Chocolatey's PATH executable can be a tiny shim, not the real binary.
        if exe.is_file() and exe.stat().st_size > 1_000_000 and probe.is_file():
            return candidate
    raise RuntimeError("Cannot find real FFmpeg binaries. Use --ffmpeg-dir PATH_TO_BIN.")


def find_inno():
    found = shutil.which("ISCC.exe")
    if found:
        return Path(found)
    for parent in (os.environ.get("LOCALAPPDATA", "") + "/Programs",
                   os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                   os.environ.get("PROGRAMFILES", "C:/Program Files")):
        for version in ("6", "7"):
            candidate = Path(parent) / f"Inno Setup {version}" / "ISCC.exe"
            if candidate.is_file():
                return candidate
    raise RuntimeError("Install Inno Setup 6 or 7 from https://jrsoftware.org/isdl.php first.")


def stage_resources(args):
    # Remove only this build's staging folder so obsolete resources cannot ship.
    if STAGE.exists():
        assert STAGE.resolve().is_relative_to((ROOT / "build" / "gettext").resolve())
        shutil.rmtree(STAGE)
    bin_dir = STAGE / "bin"
    ffmpeg_dir = find_ffmpeg_bin(args.ffmpeg_dir)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        copy_file(ffmpeg_dir / name, bin_dir / name)
    for dll in ffmpeg_dir.glob("*.dll"):
        copy_file(dll, bin_dir / dll.name)
    copy_file(ROOT / "geckodriver.exe", bin_dir / "geckodriver.exe")
    stage_deno(bin_dir / "deno.exe")

    if args.model_dir:
        model_source = Path(args.model_dir)
    else:
        cache = ROOT / "whisper_cache" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
        ref = cache / "refs" / "main"
        if ref.is_file():
            model_source = cache / "snapshots" / ref.read_text().strip()
        else:
            from faster_whisper.utils import download_model
            model_source = Path(download_model("large-v3-turbo", cache_dir=str(ROOT / "whisper_cache")))
    model_target = STAGE / "models" / "large-v3-turbo"
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"):
        copy_file(model_source / name, model_target / name)

    notices = STAGE / "licenses"
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(entry))
                if source.is_file() and source.suffix not in (".py", ".pyc"):
                    safe_parts = [part for part in entry.parts if part not in ("..", ".")]
                    copy_file(source, notices / dist.metadata["Name"] / Path(*safe_parts))
    for name in ("LICENSE", "README.txt"):
        source = ffmpeg_dir.parent / name
        if source.is_file():
            copy_file(source, notices / "ffmpeg" / name)
    upstream_licenses = {
        "whisper-MIT.txt": "https://raw.githubusercontent.com/openai/whisper/main/LICENSE",
        "geckodriver-MPL-2.0.txt": "https://raw.githubusercontent.com/mozilla/geckodriver/master/LICENSE",
        "deno-MIT.txt": f"https://raw.githubusercontent.com/denoland/deno/{DENO_VERSION}/LICENSE.md",
    }
    for name, url in upstream_licenses.items():
        request = urllib.request.Request(url, headers={"User-Agent": "GetTextFromLink-build"})
        with urllib.request.urlopen(request, timeout=60) as response:
            (notices / name).write_bytes(response.read())
    (STAGE / "THIRD_PARTY_NOTICES.txt").write_text(
        "Third-party package licenses are in licenses/.\n"
        "FFmpeg: https://ffmpeg.org/ (build/source links in licenses/ffmpeg/README.txt).\n"
        "Geckodriver (MPL-2.0): https://github.com/mozilla/geckodriver\n"
        f"Deno {DENO_VERSION} (MIT): https://github.com/denoland/deno\n"
        "Whisper large-v3-turbo (MIT): https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo\n"
        "Original Whisper: https://github.com/openai/whisper\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--skip-freeze", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument("--model-dir")
    parser.add_argument("--ffmpeg-dir")
    args = parser.parse_args()
    if os.name != "nt" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("Run with Python 3.12 64-bit on Windows: py -3.12 packaging/build_installer.py")
    if Path(sys.prefix).resolve() != ENV.resolve():
        python = ENV / "Scripts" / "python.exe"
        if not python.is_file():
            run([sys.executable, "-m", "venv", ENV])
        run([python, __file__, *sys.argv[1:]])
        return
    inno = None if args.skip_installer else find_inno()
    if not args.skip_deps:
        lock = ROOT / "packaging" / "requirements-lock.txt"
        requirements = lock if lock.is_file() else ROOT / "packaging" / "requirements-build.txt"
        run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", requirements])
    if not args.skip_freeze:
        stage_resources(args)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", ROOT / "dist", "--workpath", ROOT / "build" / "gettext" / "pyinstaller",
             ROOT / "GetTextFromLink.spec"])
        copy_file(ROOT / "packaging" / "HUONG_DAN.html", ROOT / "dist" / "GetTextFromLink" / "HUONG_DAN.html")
    if inno:
        run([inno, ROOT / "packaging" / "installer.iss"])
        installer = ROOT / "dist" / "installer" / "GetTextFromLink-Setup-1.0.0-CPU-x64.exe"
        with installer.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        installer.with_suffix(".sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
        print(f"Installer ready: {installer}", flush=True)


if __name__ == "__main__":
    main()
