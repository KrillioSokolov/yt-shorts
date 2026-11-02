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
    # words 0.5 s long at 1 s spacing (0.5 s gaps, kept); one 5.5 s silence 7.5-13.0 (dropped)
    words = [{"w": f"w{i}", "s": float(t), "e": t + 0.5} for i, t in enumerate([1, 2, 3, 4, 5, 6, 7])]
    words += [{"w": f"v{i}", "s": float(t), "e": t + 0.5} for i, t in enumerate([13, 14, 15, 16, 17])]
    cfg = common.load_config()
    cfg["crop_x_offset"] = None
    clip = {"n": 1, "start": 0.9, "end": 18.0}
    res = cut.cut_clip(src, clip, words, cfg, tmp_path)
    assert res["raw"].exists()
    assert res["crop"] in ("face", "center")
    assert (res["start"], res["end"]) == (1.0, 17.9)   # snapped: word start 1.0, word end 17.5 + 0.4 pad
    assert res["keep_ranges"] == [[1.0, 7.625], [12.875, 17.9]]
    assert res["dur"] == pytest.approx(11.65)
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
