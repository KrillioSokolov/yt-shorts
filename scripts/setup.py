"""One-time setup: check tools, create venv, install python deps, prefetch the Whisper model.

Run with a python >= 3.10 (system python, or the venv python if it already exists):
    python scripts/setup.py [--dev] [--skip-model]
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG_PATH, EXAMPLE_CONFIG_PATH, VENV_DIR, WORKSPACE, load_config, venv_python  # noqa: E402

# av>=16 removed the metadata_errors kwarg faster-whisper 1.2 still passes
PY_DEPS = ["faster-whisper>=1.0", "av<16", "opencv-python-headless>=4.8", "Pillow>=10.1"]
DEV_DEPS = ["pytest>=8"]
TOOLS = ("ffmpeg", "ffprobe", "yt-dlp")


def install_hint(missing: list[str]) -> str:
    if sys.platform == "darwin":
        pkgs = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "yt-dlp": "yt-dlp"}
        return "brew install " + " ".join(dict.fromkeys(pkgs[m] for m in missing))
    if sys.platform.startswith("win"):
        pkgs = {"ffmpeg": "Gyan.FFmpeg", "ffprobe": "Gyan.FFmpeg", "yt-dlp": "yt-dlp.yt-dlp"}
        return ("winget install " + " ".join(dict.fromkeys(pkgs[m] for m in missing))
                + "   (then open a NEW terminal so PATH updates)")
    return "sudo apt install ffmpeg && pipx install yt-dlp"


def stderr_tail(text: str, n: int = 3) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def print_table(rows: list[tuple[str, str]]) -> None:
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k.ljust(width)}  {v}")


def main() -> None:
    dev = "--dev" in sys.argv
    skip_model = "--skip-model" in sys.argv
    rows: list[tuple[str, str]] = []

    if sys.version_info < (3, 10):
        print(f"ERROR: python >= 3.10 required, found {platform.python_version()}")
        sys.exit(1)
    rows.append(("python", platform.python_version()))

    missing = [t for t in TOOLS if not shutil.which(t)]
    rows.append(("ffmpeg", "MISSING" if "ffmpeg" in missing or "ffprobe" in missing else "ok"))
    rows.append(("yt-dlp", "MISSING" if "yt-dlp" in missing else "ok"))
    if missing:
        print_table(rows)
        print(f"ERROR: missing {', '.join(missing)}. Install with:\n  {install_hint(missing)}\nthen rerun setup.")
        sys.exit(1)

    vp = venv_python()
    if vp.exists():
        chk = subprocess.run([str(vp), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"])
        if chk.returncode != 0:
            print("ERROR: existing .venv uses python < 3.10; delete the .venv folder and rerun setup")
            sys.exit(1)
    else:
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        except subprocess.CalledProcessError:
            print("ERROR: could not create venv (on Debian/Ubuntu: sudo apt install python3-venv)")
            sys.exit(1)
    pkgs = PY_DEPS + (DEV_DEPS if dev else [])
    r = subprocess.run([str(vp), "-m", "pip", "install", "-q", "--disable-pip-version-check", *pkgs],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(stderr_tail(r.stderr))
        print("ERROR: pip install failed (see above)")
        sys.exit(1)
    rows.append(("venv", str(VENV_DIR)))

    if not CONFIG_PATH.exists():
        shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
    cfg = load_config()
    rows.append(("config", str(CONFIG_PATH)))
    rows.append(("channel_url", cfg["channel_url"] or "(not set - ask the user for it)"))

    if not skip_model:
        code = (f"from faster_whisper import WhisperModel; "
                f"WhisperModel({cfg['whisper_model']!r}, device='cpu', compute_type='int8')")
        r = subprocess.run([str(vp), "-c", code], capture_output=True, text=True)
        if r.returncode != 0:
            print(stderr_tail(r.stderr, 2))
        rows.append(("whisper model", cfg["whisper_model"] + (" ok" if r.returncode == 0 else " FAILED (see above)")))
        if r.returncode != 0:
            print_table(rows)
            print("ERROR: whisper model download failed (see above); check network and rerun setup")
            sys.exit(1)

    WORKSPACE.mkdir(exist_ok=True)
    rows.append(("output_dir", cfg["output_dir"]))
    print_table(rows)
    print("SETUP OK")


if __name__ == "__main__":
    main()
