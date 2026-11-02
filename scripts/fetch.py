"""Download a YouTube video plus metadata into workspace/<slug>/.

Usage:
    python scripts/fetch.py [URL] [--cookies-from-browser chrome|edge|firefox] [--force]
Without URL: the latest upload of config.json "channel_url".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SOURCE_EXTS, WORKSPACE, die, load_config, run, save_json, slugify, tool_path, workspace_dir  # noqa: E402

COMMENT_ARGS = "youtube:max_comments=30,all,0,0;comment_sort=top"
FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"


def latest_video_url(channel_url: str, base: list[str]) -> str:
    url = channel_url.rstrip("/")
    if "list=" not in url and not url.endswith("/videos"):
        url += "/videos"
    p = run(base + ["--flat-playlist", "--playlist-items", "1", "--print", "id", url])
    ids = p.stdout.strip().splitlines()
    if not ids:
        die("could not find the latest video for channel_url")
    return f"https://www.youtube.com/watch?v={ids[0]}"


def fetch_info(url: str, base: list[str], log: Path) -> dict:
    p = run(base + ["--no-playlist", "--dump-single-json", "--skip-download", "--write-comments",
                    "--extractor-args", COMMENT_ARGS, url], log_path=log)
    return json.loads(p.stdout)


def classify_error(msg: str) -> str:
    low = msg.lower()
    if "sign in" in low or "age" in low or "private" in low or "cookies" in low:
        return msg + "\nHint: rerun with --cookies-from-browser chrome (or edge / firefox)"
    if "unable to extract" in low or "403" in low or "nsig" in low:
        return msg + "\nHint: YouTube changed something; update with: yt-dlp -U"
    return msg


def existing_source(wdir: Path) -> Path | None:
    for p in sorted(wdir.glob("source.*")):
        if p.suffix.lower() in SOURCE_EXTS:
            return p
    return None


def fmt_duration(seconds) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--cookies-from-browser")
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    args = ap.parse_args()
    cfg = load_config()

    base = [tool_path("yt-dlp"), "--no-warnings"]
    if args.cookies_from_browser:
        base += ["--cookies-from-browser", args.cookies_from_browser]

    WORKSPACE.mkdir(exist_ok=True)
    tmp_log = WORKSPACE / "fetch_info.log"
    try:
        if args.url:
            url = args.url
        elif cfg["channel_url"]:
            url = latest_video_url(cfg["channel_url"], base)
        else:
            die("no URL given and channel_url is empty in config.json")
        info = fetch_info(url, base, tmp_log)
        slug = f"{slugify(info['title'])}-{info['id']}"
        wdir = workspace_dir(slug)
        tmp_log.replace(wdir / "logs" / "fetch_info.log")

        src = existing_source(wdir)
        if src and not args.force:
            status = "cached"
        else:
            run(base + ["--no-playlist", "-f", FORMAT, "-S", "ext:mp4:m4a", "--merge-output-format", "mp4",
                        "-o", str(wdir / "source.%(ext)s"), url], log_path=wdir / "logs" / "fetch_download.log")
            src = existing_source(wdir)
            if src is None:
                die("download finished but no source.* file was produced")
            status = "downloaded"
    except RuntimeError as e:
        die(classify_error(str(e)))

    comments = sorted(info.get("comments") or [], key=lambda c: c.get("like_count") or 0, reverse=True)[:30]
    meta = {
        "id": info["id"],
        "url": url,
        "title": info["title"],
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "chapters": [{"title": c["title"], "start": c["start_time"], "end": c["end_time"]}
                     for c in (info.get("chapters") or [])],
        "comments": [c["text"] for c in comments if c.get("text")],
        "source": src.name,
    }
    save_json(wdir / "meta.json", meta)

    print(f"title:    {meta['title']}")
    print(f"duration: {fmt_duration(meta['duration'])}")
    print(f"slug:     {slug}")
    print(f"comments: {len(meta['comments'])}  chapters: {len(meta['chapters'])}")
    print(f"source:   {status} ({src.name})")


if __name__ == "__main__":
    main()
