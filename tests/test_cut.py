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
    assert cut.crop_geometry(1080, 2400) == (1080, 1920)
    assert cut.crop_geometry(720, 1280) == (720, 1280)


def test_snap_end_pad_stops_before_next_word():
    words = [{"w": "a", "s": 1.0, "e": 1.4}, {"w": "b", "s": 1.6, "e": 2.0}]
    assert cut.snap_to_words(words, 0.9, 1.4) == (1.0, 1.6)


def test_snap_end_pad_stops_at_touching_next_word():
    words = [{"w": "a", "s": 1.0, "e": 1.4}, {"w": "b", "s": 1.4, "e": 1.9}]
    assert cut.snap_to_words(words, 0.9, 1.4) == (1.0, 1.4)


def test_build_filter_single_range():
    f = cut.build_filter([[10.0, 20.0]], offset=9.5, crop_w=606, crop_h=1080, x=657, y=0)
    assert "trim=start=0.500:end=10.500" in f
    assert "atrim=start=0.500:end=10.500" in f
    assert "concat=n=1:v=1:a=1" in f
    assert "crop=606:1080:657:0,scale=1080:1920,fps=30" in f
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in f


def test_build_filter_two_ranges_chains_inputs():
    f = cut.build_filter([[0, 1], [2, 3]], offset=0, crop_w=404, crop_h=720, x=438, y=0)
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
    assert res["crop"] == "center"          # synthetic test pattern has no face
    assert res["face_bottom"] is None and res["face_top"] is None
    assert not list(tmp_path.glob("clip_01_face_*.jpg"))   # probe frames cleaned up
    assert (res["start"], res["end"]) == (1.0, 17.9)   # snapped: word start 1.0, word end 17.5 + 0.4 pad
    assert res["keep_ranges"] == [[1.0, 7.625], [12.875, 17.9]]
    assert res["dur"] == pytest.approx(11.65)
    info = common.ffprobe_info(res["raw"])
    assert (info["width"], info["height"]) == (1080, 1920)
    assert abs(info["duration"] - res["dur"]) < 0.5
    assert (tmp_path / "clip_01_keep_ranges.json").exists()


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_cut_clip_config_offset_skips_detection(tmp_path):
    src = make_video(tmp_path / "source.mp4", 6)
    words = [{"w": f"w{i}", "s": float(t), "e": t + 0.5} for i, t in enumerate([1, 2, 3, 4])]
    cfg = common.load_config()
    cfg["crop_x_offset"] = 40
    res = cut.cut_clip(src, {"n": 1, "start": 1.0, "end": 4.5}, words, cfg, tmp_path)
    assert res["crop"] == "config"
    assert res["face_bottom"] is None
    assert not list(tmp_path.glob("clip_01_face_*.jpg"))
    assert not (tmp_path / "clip_01_face.log").exists()


REAL_SRC = Path("/Users/skaix/yt-shorts/workspace/most-self-respecting-men-will-be-single-lXUjgq6MiCg/source.mp4")


@pytest.mark.skipif(not REAL_SRC.exists() or not HAS_FFMPEG, reason="real workspace video not present")
def test_detect_face_on_real_frame(tmp_path):
    x, mode, face_bottom_src, face_top_src = cut.detect_face(REAL_SRC, [300.0, 400.0, 550.0], 1920, 1080, 606,
                                                             99, tmp_path, tmp_path / "face.log")
    assert mode == "face"
    assert 500 <= x <= 800
    assert 700 <= face_bottom_src <= 1000
    assert 150 <= face_top_src <= 500
    assert not list(tmp_path.glob("clip_99_face_*.jpg"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_cut_clip_rejects_over_60s(tmp_path):
    src = make_video(tmp_path / "source.mp4", 75)
    words = [{"w": "a", "s": 0.5, "e": 0.8}, {"w": "b", "s": 70.0, "e": 70.3}]
    cfg = common.load_config()
    cfg["remove_silence"] = False
    with pytest.raises(RuntimeError, match="60s limit") as ei:
        cut.cut_clip(src, {"n": 2, "start": 0.5, "end": 70.3}, words, cfg, tmp_path)
    assert "clip is 10.3s over" in str(ei.value)   # 70.2 s (0.5 .. 70.7) - 59.9 s budget
    assert not (tmp_path / "clip_02_raw.mp4").exists()
