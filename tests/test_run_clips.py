import json
import shutil
import subprocess
from pathlib import Path

import pytest

import common
import run_clips

HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def test_caption_text_layout():
    txt = run_clips.caption_text({"title": "T", "description": "D", "hashtags": ["#a", "#b", "#c"]})
    assert txt == "T\n\nD\n#a #b #c\n"


needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
SLUG = "demo-abc"


def make_workspace(tmp_path, monkeypatch, seconds=75):
    ws = tmp_path / "workspace"
    wdir = ws / SLUG
    (wdir / "logs").mkdir(parents=True)
    monkeypatch.setattr(common, "WORKSPACE", ws)
    monkeypatch.setattr(run_clips, "WORKSPACE", ws)
    src = wdir / "source.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    common.save_json(wdir / "meta.json", {"title": "Demo", "source": "source.mp4", "duration": seconds})
    words = [{"w": f"w{i}.", "s": 1.0 + i, "e": 1.4 + i} for i in range(70)]  # words 1.0 .. 70.4 s
    common.save_json(wdir / "words.json", words)
    write_approved(wdir, [
        {"n": 1, "start": 1.0, "end": 20.0, "title": "First", "description": "d1", "hashtags": ["#x", "#y", "#z"]},
        {"n": 2, "start": 2.0, "end": 70.4, "title": "Too long", "description": "d2", "hashtags": []},
    ])
    cfg = common.load_config()
    cfg["output_dir"] = str(tmp_path / "out")
    cfg["remove_silence"] = False
    return wdir, cfg, tmp_path / "out" / SLUG


def write_approved(wdir, clips):
    common.save_json(wdir / "approved.json", {"slug": SLUG, "subtitle_color": "yellow", "clips": clips})


@needs_ffmpeg
def test_render_all_writes_outputs_and_report(tmp_path, monkeypatch):
    wdir, cfg, out_dir = make_workspace(tmp_path, monkeypatch)

    report = run_clips.render_all(SLUG, cfg, only=None)

    by_n = {r["n"]: r for r in report["clips"]}
    assert by_n[1]["status"] == "ok"
    assert by_n[2]["status"] == "fail" and "60s limit" in by_n[2]["note"]
    assert (out_dir / "clip_01.mp4").exists()
    assert (out_dir / "clip_01.txt").read_text() == "First\n\nd1\n#x #y #z\n"
    subs = json.loads((wdir / "clips" / "clip_01_subs.json").read_text())
    assert subs["chunks"] and subs["chunks"][0]["text"].isupper()
    saved = json.loads((wdir / "report.json").read_text())
    assert saved["output_dir"] == str(out_dir)
    assert len(saved["clips"]) == 2


def test_render_all_dies_without_words_json(tmp_path, monkeypatch, capsys):
    wdir = tmp_path / "workspace" / SLUG
    wdir.mkdir(parents=True)
    monkeypatch.setattr(run_clips, "WORKSPACE", tmp_path / "workspace")
    write_approved(wdir, [{"n": 1, "start": 1.0, "end": 5.0, "title": "T"}])
    with pytest.raises(SystemExit):
        run_clips.render_all(SLUG, {"output_dir": str(tmp_path / "out"), "subtitle_color": "yellow"}, only=None)
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("ERROR: words.json missing")


def test_only_unknown_clip_dies(tmp_path, monkeypatch, capsys):
    wdir = tmp_path / "workspace" / SLUG
    wdir.mkdir(parents=True)
    monkeypatch.setattr(run_clips, "WORKSPACE", tmp_path / "workspace")
    write_approved(wdir, [{"n": 1, "start": 1.0, "end": 5.0, "title": "T"}])
    common.save_json(wdir / "words.json", [])
    with pytest.raises(SystemExit):
        run_clips.render_all(SLUG, {"output_dir": str(tmp_path / "out"), "subtitle_color": "yellow"}, only=[9])
    assert capsys.readouterr().out.strip().splitlines()[-1] == "ERROR: clip 9 not in approved.json"


@needs_ffmpeg
def test_only_rerun_merges_and_drops_removed_rows(tmp_path, monkeypatch):
    wdir, cfg, out_dir = make_workspace(tmp_path, monkeypatch)
    report = run_clips.render_all(SLUG, cfg, only=None)
    fail = next(r for r in report["clips"] if r["n"] == 2)
    assert fail["status"] == "fail"
    for k in ("dur", "size_mb", "crop", "subs"):
        assert k in fail and fail[k] is None

    approved = json.loads((wdir / "approved.json").read_text())
    write_approved(wdir, approved["clips"][:1])
    report = run_clips.render_all(SLUG, cfg, only=[1])
    assert [(r["n"], r["status"]) for r in report["clips"]] == [(1, "ok")]


@needs_ffmpeg
def test_failed_rerun_removes_stale_outputs(tmp_path, monkeypatch):
    wdir, cfg, out_dir = make_workspace(tmp_path, monkeypatch)
    report = run_clips.render_all(SLUG, cfg, only=[1])
    assert report["clips"][0]["status"] == "ok"
    assert (out_dir / "clip_01.mp4").exists() and (out_dir / "clip_01.txt").exists()

    approved = json.loads((wdir / "approved.json").read_text())
    approved["clips"][0]["end"] = 70.4
    write_approved(wdir, approved["clips"])
    report = run_clips.render_all(SLUG, cfg, only=[1])
    assert report["clips"][0]["status"] == "fail"
    assert not (out_dir / "clip_01.mp4").exists()
    assert not (out_dir / "clip_01.txt").exists()


@needs_ffmpeg
def test_locked_output_file_fails_only_that_clip(tmp_path, monkeypatch):
    wdir, cfg, out_dir = make_workspace(tmp_path, monkeypatch)
    approved = json.loads((wdir / "approved.json").read_text())
    approved["clips"][1].update(start=22.0, end=30.4)   # make clip 2 renderable
    write_approved(wdir, approved["clips"])
    real_unlink = Path.unlink

    def locked(self, *a, **kw):
        if self.name == "clip_01.mp4":
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", locked)
    report = run_clips.render_all(SLUG, cfg, only=None)
    by_n = {r["n"]: r for r in report["clips"]}
    assert by_n[1]["status"] == "fail"
    assert by_n[1]["note"] == ("output file is open in another program (close the video player) "
                               "and rerun --only 1")
    assert by_n[2]["status"] == "ok"
    assert (out_dir / "clip_02.mp4").exists()


@pytest.mark.parametrize("bad", [{"start": "1"}, {"end": None}, {"start": 5.0, "end": 5.0}, {"start": True}])
def test_approved_needs_numeric_start_before_end(tmp_path, monkeypatch, capsys, bad):
    wdir = tmp_path / "workspace" / SLUG
    wdir.mkdir(parents=True)
    monkeypatch.setattr(run_clips, "WORKSPACE", tmp_path / "workspace")
    write_approved(wdir, [{"n": 3, "start": 1.0, "end": 5.0, "title": "T", **bad}])
    common.save_json(wdir / "words.json", [])
    with pytest.raises(SystemExit):
        run_clips.render_all(SLUG, {"output_dir": str(tmp_path / "out"), "subtitle_color": "yellow"}, only=None)
    assert capsys.readouterr().out.strip().splitlines()[-1] == "ERROR: approved.json: clip 3 needs numeric start < end"
