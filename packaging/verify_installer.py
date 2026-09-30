"""Install, test offline with a clean user/PATH, then uninstall the test copy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import winreg

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "gettext" / "verification"


def main():
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7FC54B8A-566D-4247-BC87-944D2D3B9101}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise RuntimeError("GetTextFromLink is already installed for this user. Test on a separate Windows account.")
    except FileNotFoundError:
        pass
    WORK.mkdir(parents=True, exist_ok=True)
    installer = ROOT / "dist" / "installer" / "GetTextFromLink-Setup-1.0.0-CPU-x64.exe"
    install_dir = WORK / "Cài đặt thử"
    environment = os.environ.copy()
    for key in ("BASE_DIR", "WHISPER_MODEL_PATH", "LINKS_FILE", "OUTPUT_WORD_FILE",
                "OUTPUT_VIDEO_DIR", "GECKODRIVER_PATH", "MODEL_NAME", "PYTHONPATH", "PYTHONHOME",
                "FIREFOX_PROFILE_PATH", "PROCESSED_LINKS_FILE", "FAILED_LINKS_FILE"):
        environment.pop(key, None)
    environment["LOCALAPPDATA"] = str(WORK / "Người dùng mới")
    environment["PATH"] = os.pathsep.join((os.path.join(os.environ["SystemRoot"], "System32"), os.environ["SystemRoot"]))
    environment["HF_HUB_OFFLINE"] = "1"
    sample = ROOT / "build" / "gettext" / "test-data" / "speech.wav"
    if sample.is_file():
        environment["GETTEXT_TEST_AUDIO"] = str(sample)
    report_path = WORK / "installed-report.json"
    installation_log = WORK / "install.log"
    uninstall_log = WORK / "uninstall.log"
    marker = Path(environment["LOCALAPPDATA"]) / "GetTextFromLink" / "keep-user-data.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("Preserve user data during uninstall.", encoding="utf-8")
    run_options = dict(check=True, cwd=WORK, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/NOICONS", "/TASKS=", f"/DIR={install_dir}", f"/LOG={installation_log}"],
                   timeout=240, **run_options)
    try:
        subprocess.run([str(install_dir / "GetTextFromLink.exe"), "--self-test", str(report_path)],
                       env=environment, timeout=240, **run_options)
        subprocess.run([str(install_dir / "_internal" / "bin" / "deno.exe"), "--version"],
                       env=environment, capture_output=True, timeout=30, **run_options)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"], report
        assert Path(report["model"]).is_relative_to(install_dir)
        assert Path(report["ffmpeg"]).is_relative_to(install_dir)
        assert Path(report["data_dir"]) == marker.parent
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        subprocess.run([str(install_dir / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", f"/LOG={uninstall_log}"], timeout=120, **run_options)
    assert not (install_dir / "GetTextFromLink.exe").exists(), "Uninstall did not remove the executable"
    assert marker.is_file(), "Uninstall removed user data"
    print("PASS: install, offline CPU transcription, Word export, Unicode paths, Deno and uninstall.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(error, file=sys.stderr)
        raise
