"""Build phrase subtitles for one cut clip and burn them with ffmpeg.

Captions are rendered as transparent PNG bands with Pillow and composited with ffmpeg's
core `overlay` filter, so no libass/drawtext build of ffmpeg is required.

Debug usage:
    python scripts/subtitle.py <slug> <n>     # needs clip_NN_raw.mp4 + clip_NN_keep_ranges.json
Normally called by run_clips.py through subtitle_clip().
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, die, ensure_venv, load_config, load_json, run, save_json, tool_path  # noqa: E402

MAX_WORDS = 5
MAX_CHARS = 22
CHUNK_GAP = 0.5
TAIL = 0.15
PUNCT = ".?!,"
COLORS = {"white": (255, 255, 255, 255), "yellow": (255, 255, 0, 255)}

FRAME_W, FRAME_H = 1080, 1920
FONT_SIZE = 72
MIN_FONT_SIZE = 40
OUTLINE = 4
SIDE_MARGIN = 60
BAND_H = FONT_SIZE * 2
BAND_Y = 1360 - BAND_H        # bottom edge at 1360 px = 70 % of the frame height

FONT_CANDIDATES = {
    "darwin": ["/System/Library/Fonts/Supplemental/Arial Black.ttf",
               "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/System/Library/Fonts/Supplemental/Impact.ttf"],
    "win32": [r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\impact.ttf"],
    "linux": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
}


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
        if len(cur) >= max_words or w["w"][-1:] in tuple(PUNCT) or (nxt is not None and nxt["s"] - w["e"] > gap):
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


def find_font(cfg: dict) -> Path | None:
    """A bold TTF to draw with: config override, else a platform default, else None (Pillow default font)."""
    override = cfg.get("subtitle_font_file")
    if override:
        p = Path(override).expanduser()
        if p.exists():
            return p
    key = "win32" if sys.platform.startswith("win") else ("darwin" if sys.platform == "darwin" else "linux")
    for candidate in FONT_CANDIDATES[key]:
        if Path(candidate).exists():
            return Path(candidate)
    return None


def _font(font_path: Path | None, size: int):
    from PIL import ImageFont  # venv only
    if font_path is not None:
        return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default(size=size)


def render_chunk_png(text: str, font_path: Path | None, color: tuple, out_path: Path) -> int:
    """Render one caption line, centered on a transparent 1080 x BAND_H band, outlined in black.

    Shrinks the font (down to MIN_FONT_SIZE) until the line fits inside the side margins.
    Returns the band height.
    """
    from PIL import Image, ImageDraw  # venv only
    img = Image.new("RGBA", (FRAME_W, BAND_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = FONT_SIZE
    while True:
        font = _font(font_path, size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=OUTLINE)
        width, height = right - left, bottom - top
        if width <= FRAME_W - 2 * SIDE_MARGIN or size <= MIN_FONT_SIZE or font_path is None:
            break
        size -= 4
    x = (FRAME_W - width) // 2 - left
    y = (BAND_H - height) // 2 - top
    draw.text((x, y), text, font=font, fill=color, stroke_width=OUTLINE, stroke_fill=(0, 0, 0, 255))
    img.save(out_path)
    return BAND_H


def build_overlay_filter(chunks: list[dict], y: int) -> str:
    """Chain one overlay per chunk: input i+1 is chunk i's PNG, shown only during [s, e]."""
    parts = []
    prev = "[0:v]"
    for i, c in enumerate(chunks, 1):
        parts.append(f"{prev}[{i}:v]overlay=0:{y}:enable='between(t,{c['s']:.3f},{c['e']:.3f})'[v{i}]")
        prev = f"[v{i}]"
    parts.append(f"{prev}format=yuv420p[vout]")
    return ";".join(parts)


def subtitle_clip(n: int, words: list[dict], keep_ranges: list[list[float]], cfg: dict,
                  clip_dir: Path, color: str | None = None) -> tuple[Path, int]:
    """Render captions for clip n and burn them into clip_NN_raw.mp4 -> clip_NN.mp4."""
    color = color or cfg["subtitle_color"]
    if color not in COLORS:
        raise RuntimeError(f"unknown subtitle_color {color!r}; use white or yellow")
    uppercase = cfg.get("subtitle_uppercase", True)
    chunks = chunk_words(words_in_clip(words, keep_ranges))
    for c in chunks:
        c["text"] = c["text"].upper() if uppercase else c["text"]
    save_json(clip_dir / f"clip_{n:02d}_subs.json", chunks)

    raw_name, out_name = f"clip_{n:02d}_raw.mp4", f"clip_{n:02d}.mp4"
    if not chunks:
        shutil.copy2(clip_dir / raw_name, clip_dir / out_name)
        return clip_dir / out_name, 0

    png_dir = clip_dir / f"clip_{n:02d}_subs"
    shutil.rmtree(png_dir, ignore_errors=True)
    png_dir.mkdir()
    font_path = find_font(cfg)
    inputs: list[str] = []
    for i, c in enumerate(chunks, 1):
        rel = Path(png_dir.name) / f"{i:03d}.png"
        render_chunk_png(c["text"], font_path, COLORS[color], clip_dir / rel)
        inputs += ["-i", str(rel)]

    # Relative names + cwd keep the command free of drive letters and spaces on Windows.
    run([tool_path("ffmpeg"), "-y", "-hide_banner", "-i", raw_name, *inputs,
         "-filter_complex", build_overlay_filter(chunks, BAND_Y),
         "-map", "[vout]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
         "-movflags", "+faststart", out_name],
        log_path=clip_dir / f"clip_{n:02d}_sub.log", cwd=clip_dir)
    shutil.rmtree(png_dir, ignore_errors=True)
    return clip_dir / out_name, len(chunks)


def main() -> None:
    ensure_venv()
    if len(sys.argv) != 3:
        print("usage: subtitle.py <slug> <n>")
        sys.exit(2)
    slug, n = sys.argv[1], int(sys.argv[2])
    wdir = WORKSPACE / slug
    clip_dir = wdir / "clips"
    ranges_path = clip_dir / f"clip_{n:02d}_keep_ranges.json"
    if not ranges_path.exists():
        die(f"{ranges_path.name} missing; run cut.py {slug} {n} first")
    approved = load_json(wdir / "approved.json")
    final, count = subtitle_clip(n, load_json(wdir / "words.json"), load_json(ranges_path), load_config(),
                                 clip_dir, approved.get("subtitle_color"))
    print(f"final: {final}")
    print(f"subs:  {count} chunks")


if __name__ == "__main__":
    main()
