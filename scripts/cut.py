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
    later = [w["s"] for w in words if w["s"] >= we["e"]]
    if later:
        e = min(e, min(later))
    return round(s, 3), round(e, 3)


def crop_geometry(iw: int, ih: int) -> tuple[int, int]:
    """Largest 9:16 window inside the source, as (crop_w, crop_h), both even."""
    if ih * 9 / 16 <= iw:
        return int(ih * 9 / 16) // 2 * 2, ih
    return iw // 2 * 2, int(iw * 16 / 9) // 2 * 2


def detect_face(source: Path, times: list[float], iw: int, ih: int, crop_w: int, n: int,
                work_dir: Path, log: Path) -> tuple[int, str, int | None, int | None]:
    """Sample a frame at each time in `times` and Haar-detect the largest face (small boxes ignored).

    Returns (crop_x, mode, face_bottom_src, face_top_src): crop x centers the median face,
    face_bottom_src / face_top_src are the lowest bottom edge / highest top edge across frames in
    source pixels. Falls back to (center, "center", None, None).
    """
    center = (iw - crop_w) // 2
    frames = [work_dir / f"clip_{n:02d}_face_{k}.jpg" for k in range(len(times))]
    lines: list[str] = []
    try:
        import cv2  # venv only
        clf = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        min_side = ih // 6
        boxes = []
        for t, frame in zip(times, frames):
            frame.unlink(missing_ok=True)
            run([tool_path("ffmpeg"), "-y", "-hide_banner", "-ss", f"{t:.3f}", "-i", source,
                 "-frames:v", "1", "-q:v", "3", frame])
            img = cv2.imread(str(frame)) if frame.exists() else None
            if img is None:
                lines.append(f"t={t:.2f}: none (no frame)")
                continue
            gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
            faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_side, min_side))
            if len(faces) == 0:
                lines.append(f"t={t:.2f}: none")
                continue
            fx, fy, fw, fh = (int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
            boxes.append((fx, fy, fw, fh))
            lines.append(f"t={t:.2f}: face ({fx},{fy},{fw},{fh})")
        if not boxes:
            lines.append("decision: no face found; centered")
            return center, "center", None, None
        cxs = sorted(bx + bw / 2 for bx, _by, bw, _bh in boxes)
        mid = len(cxs) // 2
        cx = cxs[mid] if len(cxs) % 2 else (cxs[mid - 1] + cxs[mid]) / 2
        x = int(max(0, min(iw - crop_w, cx - crop_w / 2)))
        face_bottom_src = max(by + bh for _bx, by, _bw, bh in boxes)
        face_top_src = min(by for _bx, by, _bw, _bh in boxes)
        lines.append(f"decision: face in {len(boxes)}/{len(times)} frames; median x={cx:.0f}; "
                     f"crop x={x}; face_top_src={face_top_src}; face_bottom_src={face_bottom_src}")
        return x, "face", face_bottom_src, face_top_src
    except Exception as e:
        lines.append(f"face detect failed: {type(e).__name__}: {e}; centered")
        return center, "center", None, None
    finally:
        for frame in frames:
            frame.unlink(missing_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("".join(ln + "\n" for ln in lines))


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
        over = dur - (MAX_DUR - ENCODE_MARGIN)
        raise RuntimeError(f"clip is {over:.1f}s over the 60s limit after tightening ({dur:.1f}s); "
                           f"shorten start/end")
    warn = f"short clip ({dur:.1f}s)" if dur < MIN_DUR else ""

    crop_w, crop_h = crop_geometry(info["width"], info["height"])
    crop_y = (info["height"] - crop_h) // 2
    center = (info["width"] - crop_w) // 2
    face_bottom = face_top = None
    if cfg.get("crop_x_offset") is not None:
        x = int(max(0, min(info["width"] - crop_w, center + int(cfg["crop_x_offset"]))))
        mode = "config"
    else:
        face_log = clip_dir / f"clip_{n:02d}_face.log"
        face_log.unlink(missing_ok=True)
        times = [start + (end - start) * f for f in (0.25, 0.5, 0.75)]
        x, mode, face_bottom_src, face_top_src = detect_face(src, times, info["width"], info["height"], crop_w, n,
                                                             clip_dir, face_log)
        if face_bottom_src is not None:
            face_bottom = round((face_bottom_src - crop_y) * 1920 / crop_h)
            face_top = round((face_top_src - crop_y) * 1920 / crop_h)

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
    return {"raw": out, "keep_ranges": ranges, "dur": dur, "crop": mode, "warn": warn, "start": start, "end": end,
            "face_bottom": face_bottom, "face_top": face_top}


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
    print(f"dur:   {res['dur']}s  crop={res['crop']}  face_bottom={res['face_bottom']}  {res['warn']}".rstrip())


if __name__ == "__main__":
    main()
