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
