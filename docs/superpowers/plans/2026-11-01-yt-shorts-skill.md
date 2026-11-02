# yt-shorts Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code skill (`yt-shorts`) that downloads a YouTube talking-head video, transcribes it locally, pre-chunks candidate segments for Claude to score, and renders approved segments into ≤60 s vertical 1080x1920 shorts with silence removed and white/yellow phrase subtitles burned in.

**Architecture:** Pure-Python CLI scripts under `scripts/` do every heavy step (yt-dlp, faster-whisper, OpenCV, ffmpeg) and write small JSON files into `workspace/<slug>/`. `SKILL.md` tells Claude which script to run in which order and which two files it may read (`candidates.json`, `report.json`). Scripts import shared helpers from `scripts/common.py`; `run_clips.py` imports `cut_clip` and `subtitle_clip` as functions.

**Tech Stack:** Python 3.10+ (stdlib + `faster-whisper`, `opencv-python-headless`), system `ffmpeg`/`ffprobe`/`yt-dlp`, `pytest` for tests. Cross-platform (Mac dev, Windows target).

Spec: `docs/superpowers/specs/2026-11-01-yt-shorts-skill-design.md`

## Global Constraints

- Python ≥ 3.10, stdlib `pathlib` for all paths, no shell/bash in scripts. Must run on macOS and Windows.
- Third-party imports (`faster_whisper`, `cv2`) only inside functions or after `ensure_venv()`; `common.py` and `setup.py` import stdlib only.
- Every script prints ≤ 10 lines to stdout; verbose output goes to `workspace/<slug>/logs/`. Failures: last stdout line starts with `ERROR:` and exit code ≠ 0.
- Output video: 1080x1920, 30 fps, H.264 `libx264 -preset veryfast -crf 20`, AAC 160k, `+faststart`, loudness `loudnorm=I=-14:TP=-1.5:LRA=11`.
- Clip hard limit 60.0 s after silence removal; warn under 15 s. End pad 0.4 s.
- Silence removal: word gap > `gap_threshold` (0.6) collapsed to `gap_keep` (0.25), half kept on each side. Cuts never inside a word.
- Subtitles: 3-5 words per chunk (max 5, max 22 chars), one line, uppercase by default, font `Arial Black` size 72, outline 4 black, Alignment 2, MarginV 560, PlayRes 1080x1920. Colors: white `&H00FFFFFF`, yellow `&H0000FFFF`.
- ffmpeg subtitle burn runs with `cwd=clip_dir` and relative filenames (Windows drive-colon escaping).
- Default Whisper model `small.en`, `device="cpu"`, `compute_type="int8"`, `word_timestamps=True`, `vad_filter=True`.
- Candidates: windows 20-58 s raw, cap `max_candidates` (25), sentence split on `.?!` or gap > 0.7 s.
- Commit messages end with the attribution lines from the session reminder.

---

## File structure

```
yt-shorts/
  SKILL.md                      # Claude workflow (Task 9)
  README.md                     # Spiro install steps (Task 9)
  config.example.json           # defaults (Task 1)
  .gitignore                    # .venv, workspace, config.json, __pycache__ (exists)
  scripts/
    common.py                   # paths, config, json, slugify, run(), ffprobe, keep-ranges (Task 1)
    setup.py                    # tool check, venv, pip, model prefetch, config init (Task 2)
    fetch.py                    # yt-dlp download + meta.json (Task 3)
    transcribe.py               # faster-whisper -> words.json, transcript.txt (Task 4)
    candidates.py               # words -> candidates.json (Task 5)
    cut.py                      # one clip: snap, keep-ranges, face crop, ffmpeg cut (Task 6)
    subtitle.py                 # one clip: remap words, chunk, ASS, burn (Task 7)
    run_clips.py                # approved.json -> clips + report.json (Task 8)
  tests/
    conftest.py                 # sys.path + fixtures (Task 1)
    test_common.py              # (Task 1)
    test_candidates.py          # (Task 5)
    test_cut.py                 # (Task 6)
    test_subtitle.py            # (Task 7)
    test_run_clips.py           # (Task 8)
```

All tests run with: `.venv/bin/python -m pytest tests -q` (Mac) from repo root `~/yt-shorts`.

---

### Task 1: Scaffold, `common.py`, test harness

**Files:**
- Create: `config.example.json`
- Create: `scripts/common.py`
- Create: `tests/conftest.py`
- Create: `tests/test_common.py`

**Interfaces:**
- Produces (used by every later task):
  - `SKILL_DIR, WORKSPACE, CONFIG_PATH, EXAMPLE_CONFIG_PATH, VENV_DIR: Path`
  - `venv_python() -> Path`, `ensure_venv() -> None`
  - `die(msg: str, code: int = 1) -> NoReturn` (prints `ERROR: msg`, exits)
  - `load_config() -> dict` (example merged with config.json, `output_dir` expanded)
  - `load_json(path) -> Any`, `save_json(path, data) -> None`
  - `slugify(text: str, max_len: int = 40) -> str`
  - `workspace_dir(slug) -> Path` (creates `<ws>/logs`), `latest_slug() -> str | None`, `resolve_slug(arg) -> str`, `source_path(slug) -> Path`
  - `run(cmd: list, log_path: Path | None = None, cwd: Path | None = None) -> CompletedProcess` (raises `RuntimeError(last 5 stderr lines)`)
  - `tool_path(name) -> str`
  - `ffprobe_info(path) -> {"width": int, "height": int, "duration": float}`
  - `compute_keep_ranges(words, start, end, threshold, keep) -> list[list[float]]`
  - `ranges_duration(ranges) -> float`
  - word dict shape everywhere: `{"w": str, "s": float, "e": float}`

- [ ] **Step 1: Create dev venv with pytest**

Run from `~/yt-shorts`:
```bash
python3 -m venv .venv && .venv/bin/python -m pip install -q --disable-pip-version-check pytest
.venv/bin/python -m pytest --version
```
Expected: `pytest 8.x`

- [ ] **Step 2: Write `config.example.json`**

```json
{
  "channel_url": "",
  "output_dir": "~/shorts",
  "whisper_model": "small.en",
  "subtitle_color": "white",
  "subtitle_font": "Arial Black",
  "subtitle_uppercase": true,
  "crop_x_offset": null,
  "remove_silence": true,
  "gap_threshold": 0.6,
  "gap_keep": 0.25,
  "max_candidates": 25
}
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 4: Write failing tests `tests/test_common.py`**

```python
import json
import subprocess

import pytest

import common


def test_slugify_strips_unicode_and_punctuation():
    assert common.slugify("Héllo, World! — Ep. 12") == "hello-world-ep-12"


def test_slugify_truncates_and_defaults():
    assert len(common.slugify("a" * 100, max_len=10)) == 10
    assert common.slugify("!!!") == "video"


WORDS = [
    {"w": "Hi", "s": 0.0, "e": 0.5},
    {"w": "there.", "s": 0.6, "e": 1.0},
    {"w": "So", "s": 2.0, "e": 2.5},
    {"w": "yeah.", "s": 2.6, "e": 3.0},
]


def test_keep_ranges_collapses_long_gap_only():
    ranges = common.compute_keep_ranges(WORDS, 0.0, 3.0, threshold=0.6, keep=0.25)
    assert ranges == [[0.0, 1.125], [1.875, 3.0]]
    assert common.ranges_duration(ranges) == 2.25


def test_keep_ranges_no_gap_returns_single_range():
    ranges = common.compute_keep_ranges(WORDS[:2], 0.0, 1.0, threshold=0.6, keep=0.25)
    assert ranges == [[0.0, 1.0]]


def test_load_config_merges_example(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({"subtitle_color": "yellow"}))
    cfg = common.load_config()
    assert cfg["subtitle_color"] == "yellow"
    assert cfg["gap_threshold"] == 0.6
    assert "~" not in cfg["output_dir"]


def test_run_raises_with_stderr_tail(tmp_path):
    log = tmp_path / "x.log"
    with pytest.raises(RuntimeError) as ei:
        common.run(["python3", "-c", "import sys; sys.stderr.write('boom\\n'); sys.exit(2)"], log_path=log)
    assert "boom" in str(ei.value)
    assert "boom" in log.read_text()


def test_run_ok_returns_stdout():
    p = common.run(["python3", "-c", "print('hi')"])
    assert p.stdout.strip() == "hi"
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_common.py -q`
Expected: `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 6: Write `scripts/common.py`**

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_common.py -q`
Expected: `7 passed`

- [ ] **Step 8: Commit**

```bash
git add config.example.json scripts/common.py tests/conftest.py tests/test_common.py
git commit -m "feat: scaffold yt-shorts skill with shared helpers and config defaults"
```

---

### Task 2: `setup.py`

**Files:**
- Create: `scripts/setup.py`

**Interfaces:**
- Consumes: `common.VENV_DIR, CONFIG_PATH, EXAMPLE_CONFIG_PATH, WORKSPACE, load_config, venv_python`
- Produces: `.venv/` with `faster-whisper`, `opencv-python-headless` (+ `pytest` with `--dev`); `config.json`; prefetched Whisper model; prints status table ending in `SETUP OK`.

- [ ] **Step 1: Write `scripts/setup.py`**

```python
"""One-time setup: check tools, create venv, install python deps, prefetch the Whisper model.

Run with the system python (not the venv):
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

PY_DEPS = ["faster-whisper>=1.0", "opencv-python-headless>=4.8"]
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
    if not vp.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pkgs = PY_DEPS + (DEV_DEPS if dev else [])
    r = subprocess.run([str(vp), "-m", "pip", "install", "-q", "--disable-pip-version-check", *pkgs],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
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
            print(r.stderr[-1500:])
        rows.append(("whisper model", cfg["whisper_model"] + (" ok" if r.returncode == 0 else " FAILED (see above)")))

    WORKSPACE.mkdir(exist_ok=True)
    rows.append(("output_dir", cfg["output_dir"]))
    print_table(rows)
    print("SETUP OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run setup on the Mac (dev mode)**

Run: `python3 scripts/setup.py --dev`
Expected: table with `ffmpeg ok`, `yt-dlp ok`, `whisper model small.en ok`, last line `SETUP OK`. Model download ~480 MB on first run (1-3 min).

- [ ] **Step 3: Verify venv imports**

Run: `.venv/bin/python -c "import faster_whisper, cv2; print('deps ok')"`
Expected: `deps ok`

- [ ] **Step 4: Commit**

```bash
git add scripts/setup.py
git commit -m "feat: add setup script for tools, venv, deps and Whisper model prefetch"
```

---

### Task 3: `fetch.py`

**Files:**
- Create: `scripts/fetch.py`

**Interfaces:**
- Consumes: `common.WORKSPACE, die, load_config, run, save_json, slugify, tool_path, workspace_dir`
- Produces: `workspace/<slug>/source.<ext>`, `workspace/<slug>/meta.json` with keys `id, url, title, duration, upload_date, chapters: [{title, start, end}], comments: [str], source: str`. Slug format `"{slugify(title)}-{video_id}"`. Prints 5 lines (`title:`, `duration:`, `slug:`, `comments: N  chapters: M`, `source: downloaded|cached (name)`).

- [ ] **Step 1: Write `scripts/fetch.py`**

```python
"""Download a YouTube video plus metadata into workspace/<slug>/.

Usage:
    python scripts/fetch.py [URL] [--cookies-from-browser chrome|edge|firefox] [--force]
Without URL: the latest upload of config.json "channel_url".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SOURCE_EXTS, WORKSPACE, die, load_config, run, save_json, slugify, tool_path, workspace_dir  # noqa: E402

COMMENT_ARGS = "youtube:max_comments=30,all,0,0;comment_sort=top"
FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"


def latest_video_url(channel_url: str, base: list[str]) -> str:
    url = channel_url.rstrip("/")
    if "list=" not in url and not url.endswith("/videos"):
        url += "/videos"
    p = run(base + ["--flat-playlist", "--playlist-items", "1", "--print", "id", url])
    ids = p.stdout.strip().splitlines()
    if not ids:
        die("could not find the latest video for channel_url")
    return f"https://www.youtube.com/watch?v={ids[0]}"


def fetch_info(url: str, base: list[str], log: Path) -> dict:
    p = run(base + ["--no-playlist", "--dump-single-json", "--skip-download", "--write-comments",
                    "--extractor-args", COMMENT_ARGS, url], log_path=log)
    return json.loads(p.stdout)


def classify_error(msg: str) -> str:
    low = msg.lower()
    if "sign in" in low or "age" in low or "private" in low or "cookies" in low:
        return msg + "\nHint: rerun with --cookies-from-browser chrome (or edge / firefox)"
    if "unable to extract" in low or "403" in low or "nsig" in low:
        return msg + "\nHint: YouTube changed something; update with: yt-dlp -U"
    return msg


def existing_source(wdir: Path) -> Path | None:
    for p in sorted(wdir.glob("source.*")):
        if p.suffix.lower() in SOURCE_EXTS:
            return p
    return None


def fmt_duration(seconds) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--cookies-from-browser")
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    args = ap.parse_args()
    cfg = load_config()

    base = [tool_path("yt-dlp"), "--no-warnings"]
    if args.cookies_from_browser:
        base += ["--cookies-from-browser", args.cookies_from_browser]

    WORKSPACE.mkdir(exist_ok=True)
    tmp_log = WORKSPACE / "fetch_info.log"
    try:
        if args.url:
            url = args.url
        elif cfg["channel_url"]:
            url = latest_video_url(cfg["channel_url"], base)
        else:
            die("no URL given and channel_url is empty in config.json")
        info = fetch_info(url, base, tmp_log)
        slug = f"{slugify(info['title'])}-{info['id']}"
        wdir = workspace_dir(slug)
        tmp_log.replace(wdir / "logs" / "fetch_info.log")

        src = existing_source(wdir)
        if src and not args.force:
            status = "cached"
        else:
            run(base + ["--no-playlist", "-f", FORMAT, "-S", "ext:mp4:m4a", "--merge-output-format", "mp4",
                        "-o", str(wdir / "source.%(ext)s"), url], log_path=wdir / "logs" / "fetch_download.log")
            src = existing_source(wdir)
            if src is None:
                die("download finished but no source.* file was produced")
            status = "downloaded"
    except RuntimeError as e:
        die(classify_error(str(e)))

    comments = sorted(info.get("comments") or [], key=lambda c: c.get("like_count") or 0, reverse=True)[:30]
    meta = {
        "id": info["id"],
        "url": url,
        "title": info["title"],
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "chapters": [{"title": c["title"], "start": c["start_time"], "end": c["end_time"]}
                     for c in (info.get("chapters") or [])],
        "comments": [c["text"] for c in comments if c.get("text")],
        "source": src.name,
    }
    save_json(wdir / "meta.json", meta)

    print(f"title:    {meta['title']}")
    print(f"duration: {fmt_duration(meta['duration'])}")
    print(f"slug:     {slug}")
    print(f"comments: {len(meta['comments'])}  chapters: {len(meta['chapters'])}")
    print(f"source:   {status} ({src.name})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual test with a short public English talking-head video**

Run (pick any ~5-10 min public English talking-head video, e.g. a TED-style talk):
```bash
.venv/bin/python scripts/fetch.py "https://www.youtube.com/watch?v=<VIDEO_ID>"
```
Expected: 5 lines, `source: downloaded (source.mp4)`, `workspace/<slug>/meta.json` exists with a non-empty `comments` list.

- [ ] **Step 3: Verify cache path**

Run the same command again. Expected: `source: cached (source.mp4)`, no re-download (finishes in seconds).

- [ ] **Step 4: Verify error classification with a private video id**

Run: `.venv/bin/python scripts/fetch.py "https://www.youtube.com/watch?v=aaaaaaaaaaa"`
Expected: exit code 1, last lines include `ERROR:` and either the cookies hint or a yt-dlp "Video unavailable" message.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch.py
git commit -m "feat: fetch YouTube video, chapters and top comments into workspace"
```

---

### Task 4: `transcribe.py`

**Files:**
- Create: `scripts/transcribe.py`

**Interfaces:**
- Consumes: `common.WORKSPACE, die, ensure_venv, load_config, resolve_slug, save_json, source_path`
- Produces: `workspace/<slug>/words.json` = `[{"w": str, "s": float, "e": float}, ...]` sorted by time, `transcript.txt`, `logs/transcribe.log` (one line per segment, written progressively). Prints `words:`, `audio:`, `elapsed:`, `model:` lines. Skips work if `words.json` exists unless `--force`.

- [ ] **Step 1: Write `scripts/transcribe.py`**

```python
"""Transcribe workspace/<slug>/source.* with faster-whisper into word timestamps.

Usage:
    python scripts/transcribe.py [slug] [--force]
Long-running on CPU (roughly 0.3-1.0x the video duration). Progress: workspace/<slug>/logs/transcribe.log
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, die, ensure_venv, load_config, resolve_slug, save_json, source_path  # noqa: E402


def fmt(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def main() -> None:
    ensure_venv()
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    slug = resolve_slug(args.slug)
    wdir = WORKSPACE / slug
    out = wdir / "words.json"
    if out.exists() and not args.force:
        print(f"words:    cached ({out.name})")
        return

    from faster_whisper import WhisperModel  # heavy import, venv only

    cfg = load_config()
    model_name = cfg["whisper_model"]
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    language = "en" if model_name.endswith(".en") else None
    segments, info = model.transcribe(
        str(source_path(slug)), language=language, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}, beam_size=5)

    words, lines = [], []
    with (wdir / "logs" / "transcribe.log").open("w", encoding="utf-8") as log:
        for seg in segments:  # generator: iterating performs the transcription
            text = seg.text.strip()
            lines.append(text)
            for w in seg.words or []:
                token = w.word.strip()
                if token:
                    words.append({"w": token, "s": round(w.start, 3), "e": round(w.end, 3)})
            log.write(f"[{seg.start:8.2f}] {text}\n")
            log.flush()

    if not words:
        die("no speech found in the video")
    save_json(out, words)
    (wdir / "transcript.txt").write_text(" ".join(lines), encoding="utf-8")
    print(f"words:    {len(words)}")
    print(f"audio:    {fmt(info.duration)}")
    print(f"elapsed:  {fmt(time.time() - t0)}")
    print(f"model:    {model_name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run on the fetched video**

Run: `.venv/bin/python scripts/transcribe.py`
Expected: 4 lines; `words.json` exists; `python3 -c "import json;w=json.load(open('workspace/<slug>/words.json'));print(w[:3], all(a['e']<=b['s']+0.01 for a,b in zip(w,w[1:])))"` prints three word dicts and `True` (monotonic).

- [ ] **Step 3: Verify cache**

Run again. Expected: `words:    cached (words.json)` instantly.

- [ ] **Step 4: Commit**

```bash
git add scripts/transcribe.py
git commit -m "feat: transcribe source video to word timestamps with faster-whisper"
```

---

### Task 5: `candidates.py`

**Files:**
- Create: `scripts/candidates.py`
- Create: `tests/test_candidates.py`

**Interfaces:**
- Consumes: `common.compute_keep_ranges, ranges_duration, load_config, load_json, resolve_slug, save_json, WORKSPACE`
- Produces: `workspace/<slug>/candidates.json` = `{"slug", "video_title", "video_duration", "candidates": [ {id, start, end, dur_raw, dur_tight, opener, gist, signals: {comment_hits, chapter, has_question, pace}} ]}`. Pure functions: `split_sentences(words, gap=0.7) -> list[list[word]]`, `build_windows(sents, min_dur=20, max_dur=58) -> list[tuple[int,int]]`, `keywords_from_comments(comments, top=40) -> list[str]`, `chapter_at(chapters, t) -> str | None`, `make_candidates(words, meta, cfg) -> list[dict]`.

- [ ] **Step 1: Write failing tests `tests/test_candidates.py`**

```python
import candidates


def mk_words(sentences, start=0.0, word_dur=0.3, gap=0.1, sentence_gap=0.4):
    """Build word dicts from a list of sentence strings with regular timing."""
    words, t = [], start
    for sent in sentences:
        for token in sent.split():
            words.append({"w": token, "s": round(t, 3), "e": round(t + word_dur, 3)})
            t += word_dur + gap
        t += sentence_gap
    return words


def test_split_sentences_on_punctuation_and_gap():
    words = mk_words(["Hello there.", "How are you?", "Fine"])
    words.append({"w": "later", "s": words[-1]["e"] + 2.0, "e": words[-1]["e"] + 2.3})
    sents = candidates.split_sentences(words)
    assert [candidates.sent_text(s) for s in sents] == ["Hello there.", "How are you?", "Fine", "later"]


def test_build_windows_respects_duration_bounds():
    # 10 sentences x 5 words x 0.4s = 2s each + 0.4 gap => ~2.4s per sentence
    words = mk_words([f"w{i} w w w w." for i in range(30)])
    sents = candidates.split_sentences(words)
    wins = candidates.build_windows(sents, min_dur=20, max_dur=58)
    assert wins, "expected at least one window"
    for i, j in wins:
        dur = sents[j][-1]["e"] - sents[i][0]["s"]
        assert 20 <= dur <= 58


def test_build_windows_emits_question_subwindow():
    sents_text = [f"s{i} a b c d." for i in range(10)] + ["why is that?"] + [f"t{i} a b c d." for i in range(15)]
    words = mk_words(sents_text)
    sents = candidates.split_sentences(words)
    wins = candidates.build_windows(sents, min_dur=20, max_dur=58)
    q_idx = 10
    assert any(j == q_idx for _, j in wins)


def test_keywords_from_comments_filters_stopwords_and_short():
    kws = candidates.keywords_from_comments(["Great video about python", "python is great", "the the the"])
    assert "python" in kws
    assert "great" in kws
    assert "about" not in kws  # stopword
    assert "the" not in kws


def test_chapter_at():
    chapters = [{"title": "Intro", "start": 0, "end": 10}, {"title": "Main", "start": 10, "end": 50}]
    assert candidates.chapter_at(chapters, 5) == "Intro"
    assert candidates.chapter_at(chapters, 10) == "Main"
    assert candidates.chapter_at(chapters, 99) is None


def test_make_candidates_shape_and_cap():
    words = mk_words([f"s{i} alpha beta gamma delta." for i in range(80)])
    meta = {"comments": ["alpha is key", "delta rocks"], "chapters": []}
    cfg = {"gap_threshold": 0.6, "gap_keep": 0.25, "max_candidates": 5}
    out = candidates.make_candidates(words, meta, cfg)
    assert 1 <= len(out) <= 5
    assert [c["id"] for c in out] == list(range(1, len(out) + 1))
    assert out == sorted(out, key=lambda c: c["start"])
    c = out[0]
    assert set(c) == {"id", "start", "end", "dur_raw", "dur_tight", "opener", "gist", "signals"}
    assert set(c["signals"]) == {"comment_hits", "chapter", "has_question", "pace"}
    assert c["signals"]["comment_hits"] >= 1
    assert c["dur_tight"] <= c["dur_raw"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_candidates.py -q`
Expected: `ModuleNotFoundError: No module named 'candidates'`

- [ ] **Step 3: Write `scripts/candidates.py`**

```python
"""Pre-chunk the transcript into short-form candidate windows -> candidates.json

Usage:
    python scripts/candidates.py [slug]
Claude reads candidates.json (compact) and scores it; nothing here needs tokens.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, compute_keep_ranges, die, load_config, load_json, ranges_duration, resolve_slug, save_json  # noqa: E402

MIN_DUR = 20.0
MAX_DUR = 58.0
SENTENCE_GAP = 0.7
SPACING = 5.0  # windows with start AND end within this many seconds of a kept one are dropped
OPENER_WORDS = 15

STOPWORDS = {
    "about", "above", "after", "again", "against", "really", "would", "could", "should", "there",
    "their", "these", "those", "which", "while", "where", "because", "being", "before", "between",
    "under", "until", "video", "videos", "thanks", "thank", "please", "watch", "watching", "channel",
    "subscribe", "great", "awesome", "amazing", "love", "loved", "think", "thing", "things", "something",
    "every", "everyone", "people", "always", "never", "still", "other", "another", "doesn", "didn",
    "wasn", "aren", "isn", "can't", "don't", "doesn't", "didn't", "that's", "there's", "you're", "it's",
    "going", "getting", "making", "makes", "first", "pretty", "actually", "literally", "basically",
}


def sent_text(sent: list[dict]) -> str:
    return " ".join(w["w"] for w in sent)


def split_sentences(words: list[dict], gap: float = SENTENCE_GAP) -> list[list[dict]]:
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["w"][-1] in ".?!" or nxt is None or nxt["s"] - w["e"] > gap:
            sents.append(cur)
            cur = []
    return sents


def build_windows(sents: list[list[dict]], min_dur: float = MIN_DUR, max_dur: float = MAX_DUR) -> list[tuple[int, int]]:
    """Return (i, j) inclusive sentence-index windows whose raw duration is within bounds.

    For each start i: the longest run that fits, plus the first run that ends on a ? or ! sentence.
    """
    wins: set[tuple[int, int]] = set()
    for i in range(len(sents)):
        start = sents[i][0]["s"]
        j, sub = i, None
        while j < len(sents) and sents[j][-1]["e"] - start <= max_dur:
            dur = sents[j][-1]["e"] - start
            if sub is None and dur >= min_dur and sent_text(sents[j])[-1] in "?!":
                sub = j
            j += 1
        j -= 1
        if j >= i and sents[j][-1]["e"] - start >= min_dur:
            wins.add((i, j))
            if sub is not None and sub != j:
                wins.add((i, sub))
    return sorted(wins)


def keywords_from_comments(comments: list[str], top: int = 40) -> list[str]:
    freq: dict[str, int] = {}
    for c in comments:
        for token in set(re.findall(r"[a-z][a-z']{4,}", c.lower())):
            if token not in STOPWORDS:
                freq[token] = freq.get(token, 0) + 1
    return [k for k, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]


def chapter_at(chapters: list[dict], t: float) -> str | None:
    for c in chapters:
        if c["start"] <= t < c["end"]:
            return c["title"]
    return None


def make_candidates(words: list[dict], meta: dict, cfg: dict) -> list[dict]:
    sents = split_sentences(words)
    kws = keywords_from_comments(meta.get("comments") or [])
    chapters = meta.get("chapters") or []
    total = words[-1]["e"] - words[0]["s"]
    video_pace = len(words) / total if total > 0 else 1.0

    items = []
    for i, j in build_windows(sents):
        ws = [w for s in sents[i:j + 1] for w in s]
        start, end = ws[0]["s"], ws[-1]["e"]
        text = " ".join(w["w"] for w in ws)
        low = text.lower()
        tight = ranges_duration(compute_keep_ranges(ws, start, end, cfg["gap_threshold"], cfg["gap_keep"]))
        gist = sent_text(sents[i]) if j == i else sent_text(sents[i]) + " … " + sent_text(sents[j])
        items.append({
            "id": 0,
            "start": round(start, 2),
            "end": round(end, 2),
            "dur_raw": round(end - start, 1),
            "dur_tight": round(tight, 1),
            "opener": " ".join(w["w"] for w in ws[:OPENER_WORDS]),
            "gist": gist,
            "signals": {
                "comment_hits": sum(1 for k in kws if k in low),
                "chapter": chapter_at(chapters, (start + end) / 2),
                "has_question": "?" in text,
                "pace": round((len(ws) / max(tight, 1.0)) / video_pace, 2),
            },
        })

    # Prefer strong signals and ~40s length, then enforce diversity and the cap.
    items.sort(key=lambda c: (c["signals"]["comment_hits"] + int(c["signals"]["has_question"]),
                              -abs(c["dur_tight"] - 40)), reverse=True)
    kept: list[dict] = []
    for c in items:
        if all(abs(c["start"] - k["start"]) >= SPACING or abs(c["end"] - k["end"]) >= SPACING for k in kept):
            kept.append(c)
        if len(kept) >= cfg["max_candidates"]:
            break
    kept.sort(key=lambda c: c["start"])
    for n, c in enumerate(kept, 1):
        c["id"] = n
    return kept


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    args = ap.parse_args()
    slug = resolve_slug(args.slug)
    wdir = WORKSPACE / slug
    if not (wdir / "words.json").exists():
        die("words.json missing; run transcribe.py first")
    words = load_json(wdir / "words.json")
    meta = load_json(wdir / "meta.json")
    cfg = load_config()
    cands = make_candidates(words, meta, cfg)
    if not cands:
        die("no 20-58s candidate windows found (video too short or no sentence boundaries)")
    save_json(wdir / "candidates.json", {"slug": slug, "video_title": meta["title"],
                                         "video_duration": meta.get("duration"), "candidates": cands})
    print(f"candidates: {len(cands)}")
    print(f"file:       {wdir / 'candidates.json'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_candidates.py -q`
Expected: `6 passed`

- [ ] **Step 5: Run on the real video and eyeball**

Run: `.venv/bin/python scripts/candidates.py && .venv/bin/python -c "import json;d=json.load(open('workspace/$(ls workspace | head -1)/candidates.json'));print(len(json.dumps(d))//4, 'approx tokens');print(d['candidates'][0])"`
Expected: `candidates: N` (N ≤ 25), approx tokens under 10000, first candidate has a readable opener.

- [ ] **Step 6: Commit**

```bash
git add scripts/candidates.py tests/test_candidates.py
git commit -m "feat: pre-chunk transcript into scored candidate windows"
```

---

### Task 6: `cut.py`

**Files:**
- Create: `scripts/cut.py`
- Create: `tests/test_cut.py`

**Interfaces:**
- Consumes: `common.compute_keep_ranges, ranges_duration, ffprobe_info, run, save_json, tool_path, load_config, load_json, source_path, ensure_venv, WORKSPACE`
- Produces:
  - `snap_to_words(words, start, end, pad=0.4) -> tuple[float, float]`
  - `crop_geometry(iw, ih) -> tuple[int, int]` (crop_w even, crop_h = ih)
  - `detect_face_x(source, t, iw, ih, crop_w, work_dir, log) -> tuple[int, str]` mode `"face"|"center"`
  - `build_filter(keep_ranges, offset, crop_w, crop_h, x) -> str`
  - `cut_clip(src: Path, clip: dict, words, cfg, clip_dir: Path) -> dict` with keys `raw: Path, keep_ranges, dur, crop, warn, start, end`; writes `clip_NN_raw.mp4`, `clip_NN_keep_ranges.json`, logs. Raises `RuntimeError` when `dur > 60`.
  - `clip` dict shape: `{"n": int, "start": float, "end": float, "remove_silence": bool (optional)}`

- [ ] **Step 1: Write failing tests `tests/test_cut.py`**

```python
import shutil
import subprocess
from pathlib import Path

import pytest

import common
import cut

WORDS = [
    {"w": "One", "s": 1.0, "e": 1.4},
    {"w": "two.", "s": 1.5, "e": 1.9},
    {"w": "Three", "s": 5.0, "e": 5.4},
    {"w": "four.", "s": 5.5, "e": 5.9},
]


def test_snap_to_words_uses_nearest_word_edges_and_pad():
    s, e = cut.snap_to_words(WORDS, 0.8, 6.2)
    assert s == 1.0
    assert e == pytest.approx(5.9 + 0.4)


def test_crop_geometry_even_width():
    assert cut.crop_geometry(1920, 1080) == (606, 1080)
    assert cut.crop_geometry(1280, 720) == (404, 720)


def test_build_filter_single_range():
    f = cut.build_filter([[10.0, 20.0]], offset=9.5, crop_w=606, crop_h=1080, x=657)
    assert "trim=start=0.500:end=10.500" in f
    assert "atrim=start=0.500:end=10.500" in f
    assert "concat=n=1:v=1:a=1" in f
    assert "crop=606:1080:657:0,scale=1080:1920,fps=30" in f
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in f


def test_build_filter_two_ranges_chains_inputs():
    f = cut.build_filter([[0, 1], [2, 3]], offset=0, crop_w=404, crop_h=720, x=438)
    assert "[v0][a0][v1][a1]concat=n=2" in f


HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def make_video(path: Path, seconds: int) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(path)], check=True)
    return path


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_cut_clip_produces_vertical_tightened_clip(tmp_path):
    src = make_video(tmp_path / "source.mp4", 20)
    # words 1-8s, silence 7.8-13s (dropped), words 13-18s
    words = [{"w": f"w{i}", "s": t, "e": t + 0.3} for i, t in enumerate([1, 2, 3, 4, 5, 6, 7, 7.5])]
    words += [{"w": f"v{i}", "s": t, "e": t + 0.3} for i, t in enumerate([13, 14, 15, 16, 17, 17.5])]
    cfg = common.load_config()
    cfg["crop_x_offset"] = None
    clip = {"n": 1, "start": 0.9, "end": 18.0}
    res = cut.cut_clip(src, clip, words, cfg, tmp_path)
    assert res["raw"].exists()
    assert res["crop"] in ("face", "center")
    assert (res["start"], res["end"]) == (1.0, 18.2)   # snapped: word start 1.0, word end 17.8 + 0.4 pad
    assert res["keep_ranges"] == [[1.0, 7.925], [12.875, 18.2]]
    assert res["dur"] == pytest.approx(12.25)
    info = common.ffprobe_info(res["raw"])
    assert (info["width"], info["height"]) == (1080, 1920)
    assert abs(info["duration"] - res["dur"]) < 0.5
    assert (tmp_path / "clip_01_keep_ranges.json").exists()


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_cut_clip_rejects_over_60s(tmp_path):
    src = make_video(tmp_path / "source.mp4", 75)
    words = [{"w": "a", "s": 0.5, "e": 0.8}, {"w": "b", "s": 70.0, "e": 70.3}]
    cfg = common.load_config()
    cfg["remove_silence"] = False
    with pytest.raises(RuntimeError, match="60s limit"):
        cut.cut_clip(src, {"n": 2, "start": 0.5, "end": 70.3}, words, cfg, tmp_path)
    assert not (tmp_path / "clip_02_raw.mp4").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cut.py -q`
Expected: `ModuleNotFoundError: No module named 'cut'`

- [ ] **Step 3: Write `scripts/cut.py`**

```python
"""Cut one approved clip: snap to words, drop silences, face-aware 9:16 crop, loudness normalize.

Debug usage:
    python scripts/cut.py <slug> <n>      # renders clip n from approved.json into workspace/<slug>/clips/
Normally called by run_clips.py through cut_clip().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (WORKSPACE, compute_keep_ranges, ensure_venv, ffprobe_info, load_config, load_json,  # noqa: E402
                    ranges_duration, run, save_json, source_path, tool_path)

MAX_DUR = 60.0
MIN_DUR = 15.0
END_PAD = 0.4
SEEK_LEAD = 0.5  # seconds before the clip start for the input seek


def snap_to_words(words: list[dict], start: float, end: float, pad: float = END_PAD) -> tuple[float, float]:
    """Snap start to the nearest word start and end to the nearest word end (plus pad)."""
    s = min(words, key=lambda w: abs(w["s"] - start))["s"]
    e = min(words, key=lambda w: abs(w["e"] - end))["e"] + pad
    return round(s, 3), round(e, 3)


def crop_geometry(iw: int, ih: int) -> tuple[int, int]:
    crop_w = int(ih * 9 / 16) // 2 * 2
    return min(crop_w, iw), ih


def detect_face_x(source: Path, t: float, iw: int, ih: int, crop_w: int, work_dir: Path, log: Path) -> tuple[int, str]:
    """Pick the crop x so the largest detected face is centered. Falls back to a centered crop."""
    center = (iw - crop_w) // 2
    frame = work_dir / "face_probe.jpg"
    try:
        run([tool_path("ffmpeg"), "-y", "-hide_banner", "-ss", f"{t:.3f}", "-i", source,
             "-frames:v", "1", "-q:v", "3", frame], log_path=log)
        import cv2  # venv only
        img = cv2.imread(str(frame))
        if img is None:
            return center, "center"
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clf = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(ih // 12, ih // 12))
        if len(faces) == 0:
            return center, "center"
        x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
        cx = x + w / 2
        return int(max(0, min(iw - crop_w, cx - crop_w / 2))), "face"
    except Exception:
        return center, "center"


def build_filter(keep_ranges: list[list[float]], offset: float, crop_w: int, crop_h: int, x: int) -> str:
    """ffmpeg filter_complex: trim each keep range (relative to the input seek), concat, crop, scale, loudnorm."""
    parts, inputs = [], ""
    for i, (a, b) in enumerate(keep_ranges):
        a, b = a - offset, b - offset
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        inputs += f"[v{i}][a{i}]"
    parts.append(f"{inputs}concat=n={len(keep_ranges)}:v=1:a=1[vc][ac]")
    parts.append(f"[vc]crop={crop_w}:{crop_h}:{x}:0,scale=1080:1920,fps=30,format=yuv420p[vout]")
    parts.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    return ";".join(parts)


def cut_clip(src: Path, clip: dict, words: list[dict], cfg: dict, clip_dir: Path) -> dict:
    """Render clip_NN_raw.mp4 for one approved clip. Returns a dict describing the result."""
    n = clip["n"]
    info = ffprobe_info(src)
    start, end = snap_to_words(words, clip["start"], clip["end"])
    end = min(end, info["duration"])
    if clip.get("remove_silence", cfg["remove_silence"]):
        ranges = compute_keep_ranges(words, start, end, cfg["gap_threshold"], cfg["gap_keep"])
    else:
        ranges = [[start, end]]
    dur = ranges_duration(ranges)
    if dur > MAX_DUR:
        raise RuntimeError(f"clip is {dur - MAX_DUR:.1f}s over the 60s limit after tightening ({dur:.1f}s); "
                           f"shorten start/end")
    warn = f"short clip ({dur:.1f}s)" if dur < MIN_DUR else ""

    crop_w, crop_h = crop_geometry(info["width"], info["height"])
    center = (info["width"] - crop_w) // 2
    if cfg.get("crop_x_offset") is not None:
        x = int(max(0, min(info["width"] - crop_w, center + int(cfg["crop_x_offset"]))))
        mode = "config"
    else:
        x, mode = detect_face_x(src, (start + end) / 2, info["width"], info["height"], crop_w,
                                clip_dir, clip_dir / f"clip_{n:02d}_face.log")

    out = clip_dir / f"clip_{n:02d}_raw.mp4"
    seek = max(0.0, start - SEEK_LEAD)
    cmd = [tool_path("ffmpeg"), "-y", "-hide_banner",
           "-ss", f"{seek:.3f}", "-t", f"{end - seek + SEEK_LEAD:.3f}", "-i", src,
           "-filter_complex", build_filter(ranges, seek, crop_w, crop_h, x),
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
    run(cmd, log_path=clip_dir / f"clip_{n:02d}_cut.log")
    save_json(clip_dir / f"clip_{n:02d}_keep_ranges.json", ranges)
    return {"raw": out, "keep_ranges": ranges, "dur": dur, "crop": mode, "warn": warn, "start": start, "end": end}


def main() -> None:
    ensure_venv()
    if len(sys.argv) != 3:
        print("usage: cut.py <slug> <n>")
        sys.exit(2)
    slug, n = sys.argv[1], int(sys.argv[2])
    wdir = WORKSPACE / slug
    approved = load_json(wdir / "approved.json")
    clip = next(c for c in approved["clips"] if c["n"] == n)
    clip_dir = wdir / "clips"
    clip_dir.mkdir(exist_ok=True)
    res = cut_clip(source_path(slug), clip, load_json(wdir / "words.json"), load_config(), clip_dir)
    print(f"raw:   {res['raw']}")
    print(f"dur:   {res['dur']}s  crop={res['crop']}  {res['warn']}".rstrip())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cut.py -q`
Expected: `6 passed` (the two ffmpeg tests take ~10 s)

- [ ] **Step 5: Verify loudness of the synthetic output manually**

Run (use the tmp path printed by adding `-s` or re-run cut on the real video later in Task 8). Skip here if awkward; Task 10 checks loudness on the real clip.

- [ ] **Step 6: Commit**

```bash
git add scripts/cut.py tests/test_cut.py
git commit -m "feat: cut clips with silence removal, face-aware vertical crop and loudnorm"
```

---

### Task 7: `subtitle.py`

**Files:**
- Create: `scripts/subtitle.py`
- Create: `tests/test_subtitle.py`

**Interfaces:**
- Consumes: `common.run, tool_path, load_config, load_json, WORKSPACE, ensure_venv`
- Produces:
  - `remap_time(t, keep_ranges) -> float | None`
  - `words_in_clip(words, keep_ranges) -> list[word]` (clip-relative times)
  - `chunk_words(words, max_words=5, max_chars=22, gap=0.5, tail=0.15) -> list[{"text", "s", "e"}]`
  - `ass_time(t) -> str` (`H:MM:SS.cc`)
  - `ass_text(chunks, color="white", font="Arial Black", uppercase=True) -> str`
  - `subtitle_clip(n, words, keep_ranges, cfg, clip_dir, color=None) -> tuple[Path, int]` writes `clip_NN.ass`, burns into `clip_NN.mp4` from `clip_NN_raw.mp4`; returns (final path, chunk count).
  - `COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF"}`

- [ ] **Step 1: Write failing tests `tests/test_subtitle.py`**

```python
import shutil
import subprocess

import pytest

import common
import subtitle

RANGES = [[10.0, 12.0], [15.0, 18.0]]  # 3s gap dropped (12-15)


def test_remap_time_accumulates_offsets():
    assert subtitle.remap_time(10.0, RANGES) == 0.0
    assert subtitle.remap_time(11.5, RANGES) == 1.5
    assert subtitle.remap_time(15.0, RANGES) == 2.0
    assert subtitle.remap_time(17.0, RANGES) == 4.0
    assert subtitle.remap_time(13.0, RANGES) is None


def test_words_in_clip_drops_outside_words():
    words = [{"w": "a", "s": 10.2, "e": 10.5}, {"w": "gap", "s": 13.0, "e": 13.4}, {"w": "b", "s": 16.0, "e": 16.3}]
    out = subtitle.words_in_clip(words, RANGES)
    assert [w["w"] for w in out] == ["a", "b"]
    assert out[1]["s"] == 3.0


def mk(words_with_times):
    return [{"w": w, "s": s, "e": e} for w, s, e in words_with_times]


def test_chunk_words_breaks_on_punctuation_count_gap_and_length():
    words = mk([("Hi", 0, 0.2), ("there,", 0.3, 0.5), ("how", 0.6, 0.8), ("are", 0.9, 1.0), ("you", 1.1, 1.3),
                ("doing", 1.4, 1.6), ("today", 1.7, 1.9), ("friend", 2.0, 2.2), ("yes", 3.5, 3.7),
                ("supercalifragilistic", 3.8, 4.5), ("expialidocious", 4.6, 5.0)])
    chunks = subtitle.chunk_words(words)
    texts = [c["text"] for c in chunks]
    assert texts[0] == "Hi there,"                       # punctuation break
    assert texts[1] == "how are you doing today"         # 5-word cap
    assert texts[2] == "friend"                          # gap > 0.5 before "yes"
    assert "supercalifragilistic" in texts[3] and "expialidocious" not in texts[3]  # 22-char cap
    for a, b in zip(chunks, chunks[1:]):
        assert a["e"] <= b["s"] + 1e-6
    assert chunks[-1]["e"] == pytest.approx(5.0 + 0.15)


def test_ass_time_format():
    assert subtitle.ass_time(0) == "0:00:00.00"
    assert subtitle.ass_time(65.5) == "0:01:05.50"
    assert subtitle.ass_time(3600 + 1.234) == "1:00:01.23"


def test_ass_text_style_and_dialogue():
    chunks = [{"text": "hello {world}", "s": 0.0, "e": 1.2}]
    txt = subtitle.ass_text(chunks, color="yellow")
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt
    assert "Style: Default,Arial Black,72,&H0000FFFF," in txt
    assert ",1,4,0,2,60,60,560,1" in txt  # BorderStyle 1, Outline 4, Shadow 0, Align 2, margins
    assert "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,HELLO (WORLD)" in txt


HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_subtitle_clip_burns_from_raw(tmp_path):
    raw = tmp_path / "clip_03_raw.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(raw)], check=True)
    words = [{"w": "Hello", "s": 100.2, "e": 100.6}, {"w": "world.", "s": 100.7, "e": 101.1}]
    cfg = common.load_config()
    final, n_chunks = subtitle.subtitle_clip(3, words, [[100.0, 103.0]], cfg, tmp_path, color="white")
    assert final.name == "clip_03.mp4" and final.exists()
    assert n_chunks == 1
    assert "HELLO WORLD." in (tmp_path / "clip_03.ass").read_text()
    info = common.ffprobe_info(final)
    assert (info["width"], info["height"]) == (1080, 1920)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_subtitle.py -q`
Expected: `ModuleNotFoundError: No module named 'subtitle'`

- [ ] **Step 3: Write `scripts/subtitle.py`**

```python
"""Build phrase subtitles for one cut clip and burn them with ffmpeg.

Debug usage:
    python scripts/subtitle.py <slug> <n>     # needs clip_NN_raw.mp4 + clip_NN_keep_ranges.json
Normally called by run_clips.py through subtitle_clip().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, ensure_venv, load_config, load_json, run, tool_path  # noqa: E402

MAX_WORDS = 5
MAX_CHARS = 22
CHUNK_GAP = 0.5
TAIL = 0.15
PUNCT = ".?!,"
COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF"}

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},72,{color},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def remap_time(t: float, keep_ranges: list[list[float]]) -> float | None:
    """Map a source time to clip time through the keep ranges. None when inside a dropped gap."""
    cum = 0.0
    for a, b in keep_ranges:
        if a - 1e-6 <= t <= b + 1e-6:
            return round(cum + (t - a), 3)
        cum += b - a
    return None


def words_in_clip(words: list[dict], keep_ranges: list[list[float]]) -> list[dict]:
    out = []
    for w in words:
        s, e = remap_time(w["s"], keep_ranges), remap_time(w["e"], keep_ranges)
        if s is None or e is None:
            continue
        s = max(0.0, s)
        out.append({"w": w["w"], "s": s, "e": max(e, s + 0.05)})
    return out


def chunk_words(words: list[dict], max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS,
                gap: float = CHUNK_GAP, tail: float = TAIL) -> list[dict]:
    """Group words into one-line phrase chunks with display times."""
    chunks: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if cur:
            chunks.append({"text": " ".join(w["w"] for w in cur), "s": cur[0]["s"], "e": cur[-1]["e"]})
            cur.clear()

    for i, w in enumerate(words):
        if cur and len(" ".join(x["w"] for x in cur)) + 1 + len(w["w"]) > max_chars:
            flush()
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if len(cur) >= max_words or w["w"][-1] in PUNCT or (nxt is not None and nxt["s"] - w["e"] > gap):
            flush()
    flush()

    for idx, c in enumerate(chunks):
        nxt = chunks[idx + 1] if idx + 1 < len(chunks) else None
        e = c["e"] + tail
        if nxt is not None:
            e = min(e, nxt["s"])
        if e <= c["s"]:
            e = c["s"] + 0.3
        c["e"] = round(e, 3)
        c["s"] = round(c["s"], 3)
    return chunks


def ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_text(chunks: list[dict], color: str = "white", font: str = "Arial Black", uppercase: bool = True) -> str:
    lines = []
    for c in chunks:
        text = c["text"].upper() if uppercase else c["text"]
        text = text.replace("\\", "").replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{ass_time(c['s'])},{ass_time(c['e'])},Default,,0,0,0,,{text}")
    return ASS_HEADER.format(font=font, color=COLORS[color]) + "\n".join(lines) + "\n"


def subtitle_clip(n: int, words: list[dict], keep_ranges: list[list[float]], cfg: dict,
                  clip_dir: Path, color: str | None = None) -> tuple[Path, int]:
    """Write clip_NN.ass and burn it into clip_NN_raw.mp4 -> clip_NN.mp4. Returns (path, chunk count)."""
    color = color or cfg["subtitle_color"]
    if color not in COLORS:
        raise RuntimeError(f"unknown subtitle_color {color!r}; use white or yellow")
    chunks = chunk_words(words_in_clip(words, keep_ranges))
    ass_name, raw_name, out_name = f"clip_{n:02d}.ass", f"clip_{n:02d}_raw.mp4", f"clip_{n:02d}.mp4"
    (clip_dir / ass_name).write_text(
        ass_text(chunks, color, cfg.get("subtitle_font", "Arial Black"), cfg.get("subtitle_uppercase", True)),
        encoding="utf-8")
    # Relative names + cwd avoid Windows drive-letter escaping inside the ass= filter argument.
    run([tool_path("ffmpeg"), "-y", "-hide_banner", "-i", raw_name, "-vf", f"ass={ass_name}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
         "-movflags", "+faststart", out_name],
        log_path=clip_dir / f"clip_{n:02d}_sub.log", cwd=clip_dir)
    return clip_dir / out_name, len(chunks)


def main() -> None:
    ensure_venv()
    if len(sys.argv) != 3:
        print("usage: subtitle.py <slug> <n>")
        sys.exit(2)
    slug, n = sys.argv[1], int(sys.argv[2])
    wdir = WORKSPACE / slug
    clip_dir = wdir / "clips"
    approved = load_json(wdir / "approved.json")
    ranges = load_json(clip_dir / f"clip_{n:02d}_keep_ranges.json")
    final, count = subtitle_clip(n, load_json(wdir / "words.json"), ranges, load_config(), clip_dir,
                                 approved.get("subtitle_color"))
    print(f"final: {final}")
    print(f"subs:  {count} chunks")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_subtitle.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/subtitle.py tests/test_subtitle.py
git commit -m "feat: phrase subtitles remapped through silence cuts, burned as ASS"
```

---

### Task 8: `run_clips.py`

**Files:**
- Create: `scripts/run_clips.py`
- Create: `tests/test_run_clips.py`

**Interfaces:**
- Consumes: `cut.cut_clip(src, clip, words, cfg, clip_dir)`, `subtitle.subtitle_clip(n, words, keep_ranges, cfg, clip_dir, color)`, `common.*`
- Produces: `render_all(slug, cfg, only: list[int] | None) -> dict` (the report), `caption_text(clip) -> str`; files `workspace/<slug>/clips/clip_NN{_raw.mp4,.mp4,.ass,.txt}`, copies `clip_NN.mp4` + `clip_NN.txt` to `<output_dir>/<slug>/`, writes `workspace/<slug>/report.json` = `{"slug", "output_dir", "clips": [{n, status: "ok"|"fail", title, dur, size_mb, crop, subs, note}]}`. Stdout: one line per clip plus `output:   <dir>`.
- `approved.json` schema: `{"slug": str, "subtitle_color": "white"|"yellow" (optional), "clips": [{"n": int, "start": float, "end": float, "title": str, "description": str, "hashtags": [str, str, str], "remove_silence": bool (optional)}]}`

- [ ] **Step 1: Write failing tests `tests/test_run_clips.py`**

```python
import json
import shutil
import subprocess

import pytest

import common
import run_clips

HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def test_caption_text_layout():
    txt = run_clips.caption_text({"title": "T", "description": "D", "hashtags": ["#a", "#b", "#c"]})
    assert txt == "T\n\nD\n#a #b #c\n"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_render_all_writes_outputs_and_report(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    slug = "demo-abc"
    wdir = ws / slug
    (wdir / "logs").mkdir(parents=True)
    monkeypatch.setattr(common, "WORKSPACE", ws)
    monkeypatch.setattr(run_clips, "WORKSPACE", ws)
    src = wdir / "source.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "75",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    common.save_json(wdir / "meta.json", {"title": "Demo", "source": "source.mp4", "duration": 75})
    words = [{"w": f"w{i}.", "s": 1.0 + i, "e": 1.4 + i} for i in range(70)]  # words 1.0 .. 70.4 s
    common.save_json(wdir / "words.json", words)
    common.save_json(wdir / "approved.json", {"slug": slug, "subtitle_color": "yellow", "clips": [
        {"n": 1, "start": 1.0, "end": 20.0, "title": "First", "description": "d1", "hashtags": ["#x", "#y", "#z"]},
        {"n": 2, "start": 2.0, "end": 70.4, "title": "Too long", "description": "d2", "hashtags": []},
    ]})
    cfg = common.load_config()
    cfg["output_dir"] = str(tmp_path / "out")
    cfg["remove_silence"] = False

    report = run_clips.render_all(slug, cfg, only=None)

    by_n = {r["n"]: r for r in report["clips"]}
    assert by_n[1]["status"] == "ok"
    assert by_n[2]["status"] == "fail" and "60s limit" in by_n[2]["note"]
    out_dir = tmp_path / "out" / slug
    assert (out_dir / "clip_01.mp4").exists()
    assert (out_dir / "clip_01.txt").read_text().startswith("First\n")
    assert "&H0000FFFF" in (wdir / "clips" / "clip_01.ass").read_text()
    saved = json.loads((wdir / "report.json").read_text())
    assert saved["output_dir"] == str(out_dir)
    assert len(saved["clips"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_clips.py -q`
Expected: `ModuleNotFoundError: No module named 'run_clips'`

- [ ] **Step 3: Write `scripts/run_clips.py`**

```python
"""Render every approved clip: cut -> subtitles -> caption txt -> copy to output_dir -> report.json

Usage:
    python scripts/run_clips.py [slug] [--only 2 5]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, die, ensure_venv, load_config, load_json, resolve_slug, save_json, source_path  # noqa: E402
from cut import cut_clip  # noqa: E402
from subtitle import subtitle_clip  # noqa: E402


def caption_text(clip: dict) -> str:
    return f"{clip['title']}\n\n{clip.get('description', '')}\n{' '.join(clip.get('hashtags', []))}\n"


def render_all(slug: str, cfg: dict, only: list[int] | None) -> dict:
    wdir = WORKSPACE / slug
    approved_path = wdir / "approved.json"
    if not approved_path.exists():
        die("approved.json missing; approve clips first")
    approved = load_json(approved_path)
    words = load_json(wdir / "words.json")
    src = source_path(slug)
    clip_dir = wdir / "clips"
    clip_dir.mkdir(exist_ok=True)
    out_dir = Path(cfg["output_dir"]) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    color = approved.get("subtitle_color") or cfg["subtitle_color"]

    previous = {}
    report_path = wdir / "report.json"
    if only and report_path.exists():
        previous = {r["n"]: r for r in load_json(report_path)["clips"]}

    results: dict[int, dict] = dict(previous)
    for clip in approved["clips"]:
        n = clip["n"]
        if only and n not in only:
            continue
        try:
            cut = cut_clip(src, clip, words, cfg, clip_dir)
            final, n_chunks = subtitle_clip(n, words, cut["keep_ranges"], cfg, clip_dir, color)
            txt = clip_dir / f"clip_{n:02d}.txt"
            txt.write_text(caption_text(clip), encoding="utf-8")
            shutil.copy2(final, out_dir / final.name)
            shutil.copy2(txt, out_dir / txt.name)
            results[n] = {"n": n, "status": "ok", "title": clip["title"], "dur": cut["dur"],
                          "size_mb": round(final.stat().st_size / 1e6, 1), "crop": cut["crop"],
                          "subs": n_chunks, "note": cut["warn"]}
        except Exception as e:  # one bad clip must not stop the others
            results[n] = {"n": n, "status": "fail", "title": clip.get("title", ""), "note": str(e)[:300]}

    report = {"slug": slug, "output_dir": str(out_dir), "clips": [results[k] for k in sorted(results)]}
    save_json(report_path, report)
    return report


def main() -> None:
    ensure_venv()
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--only", type=int, nargs="*", help="clip numbers to (re)render")
    args = ap.parse_args()
    cfg = load_config()
    slug = resolve_slug(args.slug)
    report = render_all(slug, cfg, args.only or None)
    for r in report["clips"]:
        if r["status"] == "ok":
            print(f"clip_{r['n']:02d}  ok    {r['dur']:5.1f}s  {r['size_mb']}MB  crop={r['crop']}  subs={r['subs']}  {r['note']}".rstrip())
        else:
            last = r["note"].strip().splitlines()[-1] if r["note"].strip() else "unknown error"
            print(f"clip_{r['n']:02d}  FAIL  {last}")
    print(f"output:   {report['output_dir']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all tests pass (`21 passed` or similar).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_clips.py tests/test_run_clips.py
git commit -m "feat: render approved clips end to end and write report"
```

---

### Task 9: `SKILL.md`, `README.md`, install symlink

**Files:**
- Create: `SKILL.md`
- Create: `README.md`

**Interfaces:**
- Consumes: every script's CLI and the `approved.json` / `candidates.json` / `report.json` shapes above.

- [ ] **Step 1: Write `SKILL.md`**

````markdown
---
name: yt-shorts
description: Turn a long YouTube talking-head video into vertical 9:16 shorts (max 60 s) with silence removed and white/yellow phrase subtitles burned in. Use when the user asks to clip, cut, repurpose, or make shorts/reels from a YouTube video or from their latest upload. Modes: setup, prep [url], clip [url].
---

# yt-shorts

Scripts do all heavy work. You read only `candidates.json`, `report.json`, and script stdout.
NEVER read or cat: `words.json`, `transcript.txt`, `meta.json`, `source.*`, anything in `logs/`, or `.ass` files.
Every script prints at most 10 lines. A last line starting with `ERROR:` means stop, relay it verbatim, and suggest the hint it contains.

## Paths

- SKILL = the folder containing this file.
- Venv python (use for every script except setup.py):
  - macOS/Linux: `SKILL/.venv/bin/python`
  - Windows: `SKILL\.venv\Scripts\python.exe`
- Workspace: `SKILL/workspace/<slug>/` (slug is printed by fetch.py).
- Output: `output_dir/<slug>/clip_NN.mp4` + `clip_NN.txt` (output_dir from config.json, default `~/shorts`).

## Modes (parse from the arguments; no argument = `clip`)

### setup
1. Run `python3 SKILL/scripts/setup.py` (Windows: `python SKILL\scripts\setup.py`) with the SYSTEM python. Takes 2-5 minutes on first run (model download).
2. Relay the status table. If it ends with `ERROR:` listing missing tools, show the install command and stop.
3. If `channel_url` shows `(not set ...)`, ask the user for their YouTube channel URL and write it into `SKILL/config.json` under `"channel_url"`.

### prep [url]
1. `VENV_PY SKILL/scripts/fetch.py [url] ` (omit url to use the latest upload of channel_url). Relay the 5 lines. Note the slug.
2. `VENV_PY SKILL/scripts/transcribe.py <slug>`. This is slow on CPU (about 0.3-1.0x the video length). Run it in the background if the tool allows and tell the user they can leave; progress is in `workspace/<slug>/logs/transcribe.log` (do not read it yourself). Relay the 4 lines when done.

### clip [url]
1. Run prep steps 1-2 (both are cached: they return instantly when already done).
2. `VENV_PY SKILL/scripts/candidates.py <slug>`.
3. Read `SKILL/workspace/<slug>/candidates.json`. Score every candidate with the rubric below.
4. Present the top 6-10 with AskUserQuestion (multiSelect: true). Option label: `#<id> <title> (<dur_tight>s)`. Description: one-line why + the opener. Mention they can ask for time nudges, title changes, yellow subtitles, or keeping pauses.
5. Apply requested adjustments (e.g. "clip 3 start 2s earlier" -> start -= 2; "keep pauses in 2" -> `"remove_silence": false`).
6. Write `SKILL/workspace/<slug>/approved.json` (schema below). Numbering `n` starts at 1 in the order chosen.
7. `VENV_PY SKILL/scripts/run_clips.py <slug>`. Relay every stdout line and the output folder.
8. If a line says `FAIL ... over the 60s limit`: propose a tighter start or end for that clip, confirm with the user, update approved.json, rerun with `--only <n>`.
9. Finish with: output folder path, list of `clip_NN.mp4` with titles, reminder that `clip_NN.txt` holds the caption.

## Scoring rubric (score each 1-5, sum)

1. Hook: would the `opener` keep a stranger watching with zero context?
2. Self-contained: no "as I said", "this", "that thing" pointing outside the window.
3. Payoff: `gist` ends on a conclusion, punchline, or clear takeaway.
4. Audience signal: `comment_hits` >= 2 or a matching `chapter`.
5. Emotion/stakes: opinion, story, number, contrast, or `has_question`.

Drop a candidate that overlaps a higher-scored one by more than half its length. Prefer `dur_tight` 25-50 s. Reject anything with `dur_tight` > 60.
For each kept candidate write: title (max 60 chars, curiosity or bold claim, no clickbait lies), one-line why, one-line description, 3 hashtags.

## approved.json

```json
{
  "slug": "<slug>",
  "subtitle_color": "white",
  "clips": [
    {"n": 1, "start": 123.4, "end": 171.9, "title": "Why I quit ML for SWE",
     "description": "The one reason that changed everything.", "hashtags": ["#career", "#softwareengineer", "#shorts"],
     "remove_silence": true}
  ]
}
```

`start`/`end` are source-video seconds (from candidates.json, plus any user nudges). `subtitle_color` is `white` or `yellow`. `remove_silence` is optional (default from config).

## Token rules

- Read only `candidates.json` (once) and script stdout. Read `report.json` only when a FAIL line needs its full note.
- One approval round per video unless the user asks for more.
- Do not open video files, logs, transcripts, or word lists. Do not summarize the whole video.
- Target under 30K tokens per video end to end.
````

- [ ] **Step 2: Write `README.md`**

```markdown
# yt-shorts — YouTube long video → vertical shorts

Runs inside Claude Code. Scripts handle download, transcription, cutting and subtitles; Claude picks the moments with you.

## Install (Windows)

1. Install Git for Windows: https://git-scm.com/download/win (defaults are fine).
2. Install Claude Code: use the Claude desktop app's **Code** tab, or follow the install guide at https://docs.anthropic.com/en/docs/claude-code. Sign in with your Claude account (Pro plan works).
3. Open PowerShell and run:
   `winget install Gyan.FFmpeg yt-dlp.yt-dlp Python.Python.3.12`
   Then close and reopen the terminal so PATH updates.
4. Unzip this folder to `%USERPROFILE%\.claude\skills\yt-shorts` (so `SKILL.md` sits directly inside `yt-shorts`).
5. Start Claude Code and run `/yt-shorts setup`. First run downloads the speech model (~480 MB) and takes a few minutes. Give it your channel URL when asked.
6. Use it:
   - Before bed: `/yt-shorts prep https://youtube.com/watch?v=...` (or just `/yt-shorts prep` for your latest upload). Transcription is slow on an older PC; leave it running.
   - Next morning: `/yt-shorts clip`. Pick the clips you like, then find them in `%USERPROFILE%\shorts\<video>\`.

## Install (macOS)

1. `brew install ffmpeg yt-dlp`
2. Clone or unzip to `~/.claude/skills/yt-shorts`, then `/yt-shorts setup` in Claude Code.

## Settings (`config.json`)

| key | default | meaning |
|---|---|---|
| `channel_url` | "" | Your channel; used when no URL is given |
| `output_dir` | `~/shorts` | Where finished clips go |
| `whisper_model` | `small.en` | `medium.en` = better, ~3x slower |
| `subtitle_color` | `white` | or `yellow` |
| `subtitle_uppercase` | true | ALL CAPS captions |
| `crop_x_offset` | null | Pixels left/right of center to crop; null = auto face detect |
| `remove_silence` | true | Cut pauses longer than `gap_threshold` |
| `gap_threshold` / `gap_keep` | 0.6 / 0.25 | Pause length that gets cut, and how much stays |

## Troubleshooting

- `ERROR: ... Sign in to confirm` → age-restricted video. Tell Claude: "rerun fetch with --cookies-from-browser chrome".
- `ERROR: Unable to extract` → YouTube changed; run `yt-dlp -U`.
- Captions look off after cuts → rerun `/yt-shorts clip` and say "keep pauses in clip N".
```

- [ ] **Step 3: Symlink into the skills folder and verify discovery**

Run:
```bash
ln -sfn ~/yt-shorts ~/.claude/skills/yt-shorts && ls -la ~/.claude/skills/yt-shorts/SKILL.md
```
Expected: the SKILL.md path resolves. Then in a fresh Claude Code session type `/yt-shorts` and confirm it appears in the skill list.

- [ ] **Step 4: Commit**

```bash
git add SKILL.md README.md
git commit -m "docs: add SKILL.md workflow and README install guide"
```

---

### Task 10: End-to-end verification on the Mac (manual)

**Files:** none created; fixes go into the relevant script with a test when a bug is found.

- [ ] **Step 1: Fresh-setup check**

```bash
rm -rf .venv && python3 scripts/setup.py --dev
```
Expected: table + `SETUP OK`.

- [ ] **Step 2: Full run through Claude**

In a new Claude Code session (so token usage is measurable): `/yt-shorts clip https://www.youtube.com/watch?v=<public English talking-head video, 10-20 min>`. Approve 3 clips, one with yellow subtitles requested, one with "keep pauses".

- [ ] **Step 3: Verify outputs**

For each `~/shorts/<slug>/clip_NN.mp4`:
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -show_entries format=duration -of default=nw=1 ~/shorts/<slug>/clip_01.mp4
ffmpeg -i ~/shorts/<slug>/clip_01.mp4 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=summary -f null - 2>&1 | grep -E "Input Integrated"
```
Expected: `width=1080 height=1920 r_frame_rate=30/1`, duration ≤ 60, `Input Integrated` within about ±1.5 LU of -14.
Open each clip: cuts start/end on word boundaries, captions in sync after silence cuts, no caption over the face, yellow clip is yellow, "keep pauses" clip has no jump cuts.

- [ ] **Step 4: Cache reuse check**

Run `/yt-shorts prep` then `/yt-shorts clip` on the same URL. Expected: `source: cached`, `words: cached`, no re-download or re-transcribe.

- [ ] **Step 5: Token check**

Run `/cost` (or check the session usage) after step 2. Expected: under 30K tokens for the whole video. If over, find which file Claude read that it should not have and tighten SKILL.md wording.

- [ ] **Step 6: Record findings**

Append a `## Verified 2026-MM-DD` section at the end of `docs/superpowers/specs/2026-11-01-yt-shorts-skill-design.md` listing the test video, clip count, token count, loudness, and any fixes made. Commit:
```bash
git add -A && git commit -m "docs: record end-to-end verification results"
```

- [ ] **Step 7: Build the handoff zip**

```bash
cd ~ && zip -r yt-shorts.zip yt-shorts -x "yt-shorts/.venv/*" "yt-shorts/workspace/*" "yt-shorts/.git/*" "yt-shorts/config.json" "*/__pycache__/*" "*/.pytest_cache/*"
```
Expected: zip under 1 MB, contains SKILL.md, README.md, config.example.json, scripts/, tests/, docs/.
