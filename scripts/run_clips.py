"""Render every approved clip: cut -> subtitles -> caption txt -> copy to output_dir -> report.json

Usage:
    python scripts/run_clips.py [slug] [--only N ...]   (slug must come before --only)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, die, ensure_venv, load_config, load_json, resolve_slug, save_json, source_path  # noqa: E402
from cut import cut_clip  # noqa: E402
from subtitle import subtitle_clip  # noqa: E402


def caption_text(clip: dict) -> str:
    return f"{clip['title']}\n\n{clip.get('description', '')}\n{' '.join(clip.get('hashtags', []))}\n"


def short_note(e: Exception) -> str:
    lines = [ln for ln in str(e).strip().splitlines() if ln.strip()]
    if not lines:
        return type(e).__name__
    note = lines[0]
    if len(lines) > 1:
        note += " … " + lines[-1]
    return note[:300]


def render_all(slug: str, cfg: dict, only: list[int] | None) -> dict:
    wdir = WORKSPACE / slug
    approved_path = wdir / "approved.json"
    if not approved_path.exists():
        die("approved.json missing; approve clips first")
    if not (wdir / "words.json").exists():
        die("words.json missing; run transcribe.py first")
    approved = load_json(approved_path)
    clips = approved.get("clips") if isinstance(approved, dict) else None
    if not isinstance(clips, list):
        die("approved.json: 'clips' must be a list")
    for i, c in enumerate(clips):
        if (not isinstance(c, dict) or not isinstance(c.get("n"), int) or isinstance(c.get("n"), bool)
                or not str(c.get("title") or "").strip()):
            die(f"approved.json: clip {i} is missing 'n' or 'title'")
    known = {c["n"] for c in clips}
    for n in only or []:
        if n not in known:
            die(f"clip {n} not in approved.json")
    words = load_json(wdir / "words.json")
    src = source_path(slug)
    clip_dir = wdir / "clips"
    clip_dir.mkdir(exist_ok=True)
    out_dir = Path(cfg["output_dir"]).expanduser() / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    color = approved.get("subtitle_color") or cfg["subtitle_color"]

    previous = {}
    report_path = wdir / "report.json"
    if only and report_path.exists():
        previous = {r["n"]: r for r in load_json(report_path)["clips"] if r["n"] in known}

    results: dict[int, dict] = dict(previous)
    for clip in approved["clips"]:
        n = clip["n"]
        if only and n not in only:
            continue
        for stale in (clip_dir / f"clip_{n:02d}.mp4", clip_dir / f"clip_{n:02d}.txt",
                      out_dir / f"clip_{n:02d}.mp4", out_dir / f"clip_{n:02d}.txt"):
            stale.unlink(missing_ok=True)
        try:
            cut = cut_clip(src, clip, words, cfg, clip_dir)
            final, n_chunks = subtitle_clip(n, words, cut["keep_ranges"], cfg, clip_dir, color)
            txt = clip_dir / f"clip_{n:02d}.txt"
            txt.write_text(caption_text(clip), encoding="utf-8")
            shutil.copy2(final, out_dir / final.name)
            shutil.copy2(txt, out_dir / txt.name)
            results[n] = {"n": n, "status": "ok", "title": clip["title"], "dur": cut["dur"],
                          "size_mb": round(final.stat().st_size / 1e6, 1), "crop": cut["crop"],
                          "subs": n_chunks, "note": cut["warn"]}
        except Exception as e:  # one bad clip must not stop the others
            results[n] = {"n": n, "status": "fail", "title": clip.get("title", ""), "dur": None,
                          "size_mb": None, "crop": None, "subs": None, "note": short_note(e)}

    report = {"slug": slug, "output_dir": str(out_dir), "clips": [results[k] for k in sorted(results)]}
    tmp = report_path.with_name("report.json.tmp")
    save_json(tmp, report)
    tmp.replace(report_path)
    return report


def main() -> None:
    ensure_venv()
    try:
        ap = argparse.ArgumentParser(usage="run_clips.py [slug] [--only N ...]")
        ap.add_argument("slug", nargs="?", help="workspace slug; must come FIRST: run_clips.py [slug] [--only N ...]")
        ap.add_argument("--only", type=int, nargs="+", help="clip numbers to (re)render")
        args = ap.parse_args()
        cfg = load_config()
        slug = resolve_slug(args.slug)
        report = render_all(slug, cfg, args.only or None)
        for r in report["clips"]:
            if r["status"] == "ok":
                print(f"clip_{r['n']:02d}  ok    {r['dur']:5.1f}s  {r['size_mb']}MB  crop={r['crop']}  subs={r['subs']}  {r['note']}".rstrip())
            else:
                print(f"clip_{r['n']:02d}  FAIL  {r['note'] or 'unknown error'}")
        print(f"output:   {report['output_dir']}")
    except Exception as e:
        die(f"run_clips failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
