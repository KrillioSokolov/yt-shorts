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
    subs = json.loads((wdir / "clips" / "clip_01_subs.json").read_text())
    assert subs and subs[0]["text"].isupper()
    saved = json.loads((wdir / "report.json").read_text())
    assert saved["output_dir"] == str(out_dir)
    assert len(saved["clips"]) == 2
