"""Cut one approved clip: snap to words, drop silences, face-aware 9:16 crop, loudness normalize.

Debug usage:
    python scripts/cut.py <slug> <n>      # renders clip n from approved.json into workspace/<slug>/clips/
Normally called by run_clips.py through cut_clip().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (WORKSPACE, die, compute_keep_ranges, ensure_venv, ffprobe_info, load_config, load_json,  # noqa: E402
                    ranges_duration, run, save_json, source_path, tool_path)

MAX_DUR = 60.0
MIN_DUR = 15.0
END_PAD = 0.4
ENCODE_MARGIN = 0.1  # keep output safely under the 60 s limit
SEEK_LEAD = 0.5  # seconds before the clip start for the input seek


def snap_to_words(words: list[dict], start: float, end: float, pad: float = END_PAD) -> tuple[float, float]:
    """Snap start to the nearest word start and end to the nearest word end (plus pad)."""
    s = min(words, key=lambda w: abs(w["s"] - start))["s"]
    we = min(words, key=lambda w: abs(w["e"] - end))
    e = we["e"] + pad
    later = [w["s"] for w in words if w["s"] > we["e"]]
    if later:
        e = min(e, min(later))
    return round(s, 3), round(e, 3)


def crop_geometry(iw: int, ih: int) -> tuple[int, int]:
    """Largest 9:16 window inside the source, as (crop_w, crop_h), both even."""
    if ih * 9 / 16 <= iw:
        return int(ih * 9 / 16) // 2 * 2, ih
    return iw // 2 * 2, int(iw * 16 / 9) // 2 * 2


def detect_face_x(source: Path, t: float, iw: int, ih: int, crop_w: int, work_dir: Path, log: Path, n: int) -> tuple[int, str]:
    """Pick the crop x so the largest detected face is centered. Falls back to a centered crop."""
    center = (iw - crop_w) // 2
    frame = work_dir / f"clip_{n:02d}_face.jpg"
    frame.unlink(missing_ok=True)
    try:
        run([tool_path("ffmpeg"), "-y", "-hide_banner", "-ss", f"{t:.3f}", "-i", source,
             "-frames:v", "1", "-q:v", "3", frame], log_path=log)
        if not frame.exists():
            return center, "center"
        import cv2  # venv only
        img = cv2.imread(str(frame))
        if img is None:
            return center, "center"
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clf = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(ih // 12, ih // 12))
        if len(faces) == 0:
            with open(log, "a") as f:
                f.write("no face found; centered\n")
            return center, "center"
        x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
        cx = x + w / 2
        x = int(max(0, min(iw - crop_w, cx - crop_w / 2)))
        with open(log, "a") as f:
            f.write(f"face at x={cx:.0f}; crop x={x}\n")
        return x, "face"
    except Exception as e:
        with open(log, "a") as f:
            f.write(f"face detect failed: {type(e).__name__}: {e}\n")
        return center, "center"
    finally:
        frame.unlink(missing_ok=True)


def build_filter(keep_ranges: list[list[float]], offset: float, crop_w: int, crop_h: int, x: int, y: int) -> str:
    """ffmpeg filter_complex: trim each keep range (relative to the input seek), concat, crop, scale, loudnorm."""
    parts, inputs = [], ""
    for i, (a, b) in enumerate(keep_ranges):
        a, b = a - offset, b - offset
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        inputs += f"[v{i}][a{i}]"
    parts.append(f"{inputs}concat=n={len(keep_ranges)}:v=1:a=1[vc][ac]")
    parts.append(f"[vc]crop={crop_w}:{crop_h}:{x}:{y},scale=1080:1920,fps=30,format=yuv420p[vout]")
    parts.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    return ";".join(parts)


def cut_clip(src: Path, clip: dict, words: list[dict], cfg: dict, clip_dir: Path) -> dict:
    """Render clip_NN_raw.mp4 for one approved clip. Returns a dict describing the result."""
    n = clip["n"]
    if not words:
        raise RuntimeError(f"clip {n}: no words to snap to")
    info = ffprobe_info(src)
    start, end = snap_to_words(words, clip["start"], clip["end"])
    end = min(end, info["duration"])
    if end <= start:
        raise RuntimeError(f"clip {n}: end {end} is not after start {start}")
    if clip.get("remove_silence", cfg["remove_silence"]):
        ranges = compute_keep_ranges(words, start, end, cfg["gap_threshold"], cfg["gap_keep"])
    else:
        ranges = [[start, end]]
    if not ranges:
        raise RuntimeError(f"clip {n}: no speech inside {start}-{end}")
    dur = ranges_duration(ranges)
    if dur > MAX_DUR - ENCODE_MARGIN:
        raise RuntimeError(f"clip is {dur - MAX_DUR:.1f}s over the 60s limit after tightening ({dur:.1f}s); "
                           f"shorten start/end")
    warn = f"short clip ({dur:.1f}s)" if dur < MIN_DUR else ""

    crop_w, crop_h = crop_geometry(info["width"], info["height"])
    crop_y = (info["height"] - crop_h) // 2
    center = (info["width"] - crop_w) // 2
    if cfg.get("crop_x_offset") is not None:
        x = int(max(0, min(info["width"] - crop_w, center + int(cfg["crop_x_offset"]))))
        mode = "config"
    else:
        x, mode = detect_face_x(src, (start + end) / 2, info["width"], info["height"], crop_w,
                                clip_dir, clip_dir / f"clip_{n:02d}_face.log", n)

    out = clip_dir / f"clip_{n:02d}_raw.mp4"
    seek = max(0.0, start - SEEK_LEAD)
    cmd = [tool_path("ffmpeg"), "-y", "-hide_banner",
           "-ss", f"{seek:.3f}", "-t", f"{end - seek + SEEK_LEAD:.3f}", "-i", src,
           "-filter_complex", build_filter(ranges, seek, crop_w, crop_h, x, crop_y),
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
    clip = next((c for c in approved["clips"] if c["n"] == n), None)
    if clip is None:
        die(f"clip {n} not in approved.json")
    clip_dir = wdir / "clips"
    clip_dir.mkdir(exist_ok=True)
    res = cut_clip(source_path(slug), clip, load_json(wdir / "words.json"), load_config(), clip_dir)
    print(f"raw:   {res['raw']}")
    print(f"dur:   {res['dur']}s  crop={res['crop']}  {res['warn']}".rstrip())


if __name__ == "__main__":
    main()
