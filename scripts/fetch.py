"""Download a YouTube video plus metadata into workspace/<slug>/.

Usage:
    python scripts/fetch.py [URL] [--cookies-from-browser chrome|edge|firefox] [--force]
Without URL: the latest upload of config.json "channel_url".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SOURCE_EXTS, WORKSPACE, die, load_config, run, save_json, slugify, tool_path, workspace_dir  # noqa: E402

COMMENT_ARGS = "youtube:max_comments=30,all,0,0;comment_sort=top"
FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"
DENO_HINT = " | hint: install deno (winget install DenoLand.Deno / brew install deno), restart Claude Code, retry"


TAB_SEGMENTS = {"videos", "streams", "shorts", "featured", "live", "playlists"}


def channel_videos_url(channel_url: str) -> str:
    url = channel_url.rstrip("/")
    if "list=" in url:
        return url
    path = urlsplit(url).path
    if any(seg in TAB_SEGMENTS for seg in path.split("/")):
        return url
    return url + "/videos"


def latest_video_url(channel_url: str, base: list[str]) -> str:
    url = channel_videos_url(channel_url)
    p = run(base + ["--flat-playlist", "--playlist-items", "1", "--print", "id", url],
            log_path=WORKSPACE / "fetch_channel.log")
    ids = p.stdout.strip().splitlines()
    if not ids:
        die("could not find the latest video for channel_url")
    return f"https://www.youtube.com/watch?v={ids[0]}"


def fetch_info(url: str, base: list[str], log: Path) -> dict:
    p = run(base + ["--no-playlist", "--dump-single-json", "--skip-download", "--write-comments",
                    "--extractor-args", COMMENT_ARGS, url], log_path=log)
    return json.loads(p.stdout)


def error_line(msg: str) -> str:
    lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
    last = lines[-1] if lines else "unknown error"
    last = re.sub(r"^\s*error:\s*", "", last, flags=re.I)
    low = last.lower()
    # yt-dlp's JS-runtime warnings come on earlier lines, so search the whole message
    if any(k in msg.lower() for k in ("javascript runtime", "js runtime", "jsc", "n challenge",
                                      "challenge solving", "requested format is not available")):
        return last + DENO_HINT
    if any(k in low for k in ("unable to extract", "http error 403", "nsig")):
        return last + " | hint: YouTube changed something; run: yt-dlp -U"
    if re.search(r"sign in|age[- ]restrict|confirm your age|private video|cookies|members-only", low):
        return last + " | hint: rerun with the same URL and --cookies-from-browser firefox (chrome/edge often fail on Windows)"
    return last


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

    base = [tool_path("yt-dlp")]
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
        vid = info["id"]
        title = info.get("title") or vid
        slug = f"{slugify(title)}-{vid}"
        wdir = workspace_dir(slug)
        tmp_log.replace(wdir / "logs" / "fetch_info.log")

        src = existing_source(wdir)
        if src and (wdir / "meta.json").exists() and not args.force:
            status = "cached"
        else:
            for old in wdir.glob("source.*"):
                if old.suffix.lower() in SOURCE_EXTS:
                    old.unlink()
            run(base + ["--no-playlist", "-f", FORMAT, "-S", "ext:mp4:m4a", "--merge-output-format", "mp4",
                        "-o", str(wdir / "source.%(ext)s"), url], log_path=wdir / "logs" / "fetch_download.log")
            src = existing_source(wdir)
            if src is None:
                die("download finished but no source.* file was produced")
            status = "downloaded"

        comments = sorted(info.get("comments") or [], key=lambda c: c.get("like_count") or 0, reverse=True)[:30]
        chapters = [{"title": c.get("title") or "", "start": c["start_time"], "end": c["end_time"]}
                    for c in (info.get("chapters") or [])
                    if c.get("start_time") is not None and c.get("end_time") is not None]
        meta = {
            "id": vid,
            "url": info.get("webpage_url") or url,
            "title": title,
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "chapters": chapters,
            "comments": [c["text"] for c in comments if c.get("text")],
            "source": src.name,
        }
    except KeyError as e:
        die(error_line(f"yt-dlp output missing field {e}"))
    except (RuntimeError, ValueError, OSError) as e:
        die(error_line(str(e)))

    save_json(wdir / "meta.json", meta)

    print(f"title:    {meta['title']}")
    print(f"duration: {fmt_duration(meta['duration'])}")
    print(f"slug:     {slug}")
    print(f"comments: {len(meta['comments'])}  chapters: {len(meta['chapters'])}")
    print(f"source:   {status} ({src.name})")


if __name__ == "__main__":
    main()
