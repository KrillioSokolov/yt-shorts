"""Shared helpers for yt-shorts scripts. Standard library only."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

# Windows consoles default to cp1252; a video title with an emoji would crash print().
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKILL_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = SKILL_DIR / "workspace"
CONFIG_PATH = SKILL_DIR / "config.json"
EXAMPLE_CONFIG_PATH = SKILL_DIR / "config.example.json"
VENV_DIR = SKILL_DIR / ".venv"

SOURCE_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}")
    sys.exit(code)


def ensure_venv() -> None:
    """Re-run the current script under the skill venv when launched with another python."""
    vp = venv_python()
    if not vp.exists():
        die("venv missing. Run: python scripts/setup.py")
    try:
        same = Path(sys.executable).resolve() == vp.resolve()
    except OSError:
        same = False
    if not same:
        sys.exit(subprocess.call([str(vp), *sys.argv]))


def load_config() -> dict:
    cfg = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    cfg["output_dir"] = str(Path(cfg["output_dir"]).expanduser())
    return cfg


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "video"


def workspace_dir(slug: str) -> Path:
    d = WORKSPACE / slug
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def latest_slug() -> str | None:
    dirs = [d for d in WORKSPACE.glob("*") if (d / "meta.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: (d / "meta.json").stat().st_mtime).name


def resolve_slug(arg: str | None) -> str:
    slug = arg or latest_slug()
    if not slug or not (WORKSPACE / slug / "meta.json").exists():
        die("no video found. Run fetch.py first (or pass a slug).")
    return slug


def source_path(slug: str) -> Path:
    meta = load_json(WORKSPACE / slug / "meta.json")
    p = WORKSPACE / slug / meta["source"]
    if not p.exists():
        die(f"source video missing: {p}")
    return p


def run(cmd: list, log_path: Path | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command quietly. On failure raise RuntimeError with the last 5 stderr lines."""
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if log_path is not None:
        Path(log_path).write_text(
            f"$ {' '.join(cmd)}\n\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}",
            encoding="utf-8")
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-5:])
        raise RuntimeError(tail or f"exit code {p.returncode}")
    return p


def tool_path(name: str) -> str:
    p = shutil.which(name)
    if not p:
        die(f"{name} not found on PATH. Run: python scripts/setup.py")
    return p


def ffprobe_info(path) -> dict:
    """Return width/height of the first video stream and container duration."""
    p = run([tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json", path])
    data = json.loads(p.stdout)
    stream = data["streams"][0]
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "duration": float(data["format"]["duration"])}


def compute_keep_ranges(words: list[dict], start: float, end: float,
                        threshold: float, keep: float) -> list[list[float]]:
    """Split [start, end] into source-time ranges that drop silences longer than `threshold`.

    Each dropped gap keeps `keep/2` seconds on both sides, so cuts never touch a word.
    """
    ws = [w for w in words if w["s"] >= start - 1e-6 and w["e"] <= end + 1e-6]
    ranges: list[list[float]] = []
    cur = start
    for a, b in zip(ws, ws[1:]):
        if b["s"] - a["e"] > threshold:
            ranges.append([cur, round(a["e"] + keep / 2, 3)])
            cur = round(b["s"] - keep / 2, 3)
    ranges.append([cur, end])
    return [[a, b] for a, b in ranges if b - a > 1e-3]


def ranges_duration(ranges: list[list[float]]) -> float:
    return round(sum(b - a for a, b in ranges), 3)
