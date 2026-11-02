import shutil
import subprocess
from pathlib import Path

import pytest

import common
import subtitle

HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")

RANGES = [[10.0, 12.0], [15.0, 18.0]]  # 3s gap dropped (12-15)


def mk(words_with_times):
    return [{"w": w, "s": s, "e": e} for w, s, e in words_with_times]



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


def test_chunk_words_breaks_on_punctuation_count_gap_and_length():
    words = mk([("Hi", 0, 0.2), ("there,", 0.3, 0.5), ("how", 0.6, 0.8), ("are", 0.9, 1.0), ("you", 1.1, 1.3),
                ("doing", 1.4, 1.6), ("ok", 1.7, 1.9), ("friend", 2.0, 2.2), ("yes", 3.5, 3.7),
                ("supercalifragilistic", 3.8, 4.5), ("expialidocious", 4.6, 5.0)])
    chunks = subtitle.chunk_words(words)
    texts = [c["text"] for c in chunks]
    assert texts == ["Hi there,", "how are you doing ok", "friend", "yes",
                     "supercalifragilistic", "expialidocious"]
    # "Hi there," = punctuation break; 5-word cap; gap > 0.5 s before "yes"; 22-char cap twice
    for a, b in zip(chunks, chunks[1:]):
        assert a["e"] <= b["s"] + 1e-6
    assert chunks[-1]["e"] == pytest.approx(5.0 + 0.15)


def test_find_font_prefers_override(tmp_path):
    fake = tmp_path / "x.ttf"
    fake.write_bytes(b"0")
    assert subtitle.find_font({"subtitle_font_file": str(fake)}) == fake
    # no override: returns a Path that exists or None, never a missing path
    found = subtitle.find_font({})
    assert found is None or found.exists()


def test_render_chunk_png_draws_centered_text(tmp_path):
    from PIL import Image
    out = tmp_path / "c.png"
    band_h = subtitle.render_chunk_png("HELLO WORLD", subtitle.find_font({}), subtitle.COLORS["yellow"], out)
    img = Image.open(out)
    assert img.mode == "RGBA" and img.size == (1080, band_h)
    px = img.load()
    opaque = [(x, y) for y in range(0, band_h, 4) for x in range(0, 1080, 4) if px[x, y][3] > 0]
    assert opaque, "nothing drawn"
    xs = [x for x, _ in opaque]
    assert min(xs) > 40 and max(xs) < 1040            # fits inside the frame with margins
    assert abs((min(xs) + max(xs)) / 2 - 540) < 40     # horizontally centered
    assert any(px[x, y][:3] == (255, 255, 0) for x, y in opaque)   # yellow fill present
    assert any(px[x, y][:3] == (0, 0, 0) for x, y in opaque)       # black outline present


def test_render_chunk_png_shrinks_long_text_to_fit(tmp_path):
    from PIL import Image
    out = tmp_path / "long.png"
    subtitle.render_chunk_png("WWWWWWWWWWWWWWWWWWWWWW", subtitle.find_font({}), subtitle.COLORS["white"], out)
    img = Image.open(out)
    px = img.load()
    xs = [x for y in range(0, img.size[1], 4) for x in range(0, 1080, 2) if px[x, y][3] > 0]
    assert min(xs) >= 60 and max(xs) <= 1020


def test_build_overlay_filter_chains_inputs():
    chunks = [{"text": "A", "s": 0.0, "e": 1.2}, {"text": "B", "s": 1.5, "e": 2.0}]
    f = subtitle.build_overlay_filter(chunks, y=1300)
    assert f.startswith("[0:v][1:v]overlay=0:1300:enable='between(t,0.000,1.200)'[v1];")
    assert "[v1][2:v]overlay=0:1300:enable='between(t,1.500,2.000)'[v2];" in f
    assert f.endswith("[v2]format=yuv420p[vout]")


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
    subs = common.load_json(tmp_path / "clip_03_subs.json")
    assert subs[0]["text"] == "HELLO WORLD." and subs[0]["s"] == pytest.approx(0.2)
    assert not (tmp_path / "clip_03_subs").exists()       # PNGs cleaned up
    info = common.ffprobe_info(final)
    assert (info["width"], info["height"]) == (1080, 1920)
    # the caption band must contain non-black pixels at t=0.5 s
    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(final), "-frames:v", "1", str(frame)], check=True)
    from PIL import Image
    img = Image.open(frame).convert("RGB")
    px = img.load()
    assert any(px[x, y] != (0, 0, 0) for y in range(1250, 1450, 5) for x in range(300, 780, 5))
