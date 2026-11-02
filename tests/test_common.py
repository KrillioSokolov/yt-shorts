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
