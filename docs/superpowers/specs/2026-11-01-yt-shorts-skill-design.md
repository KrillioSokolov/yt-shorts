# yt-shorts skill — design

Date: 2026-11-01
Owner: Kiryll (builds + tests on Mac), end user: Spiro (Windows, older PC, Claude Pro $20, Claude Code via desktop app Code tab or CLI).

## Goal

A Claude Code skill that turns a long YouTube talking-head video into vertical (1080x1920) shorts up to 60 s, with burned-in white or yellow phrase subtitles, dead air removed, saved to a local folder. Token-frugal: scripts do all heavy work; Claude reads only compact JSON and makes one approval round with Spiro.

## Fixed decisions

| Topic | Decision |
|---|---|
| Runtime | Claude Code (desktop Code tab or CLI). Claude.ai chat mode is out of scope (no local disk/network). |
| OS | Scripts cross-platform (Mac for testing, Windows for Spiro). Pure Python 3.10+, pathlib, no bash. |
| Input | YouTube URL given by Spiro, or latest upload of `config.channel_url` when no URL given. |
| Video type | One person, talking head, static camera, English. |
| Transcription | `faster-whisper` locally, always (approach B). Default model `small.en`, int8 CPU. Slow on old PC is acceptable (run overnight via `prep`). |
| Topic scoring | Claude scores pre-chunked candidates with a fixed rubric plus audience hints (top YouTube comments, chapters) pulled by yt-dlp. No vidIQ. |
| Approval | In-chat multi-select of 6-10 candidates; Spiro can rename titles and nudge times in chat. One round. |
| Subtitles | 3-5 word phrase chunks, one line, bold sans, white (default) or yellow, black outline, no box, ~70% frame height. ASS burned by ffmpeg. |
| Crop | 9:16 center crop, horizontal offset from one-shot OpenCV Haar face detect at clip midpoint; fallback center; `config.crop_x_offset` overrides. |
| Dead space | Collapse word gaps > 0.6 s to 0.25 s via ffmpeg trim+concat; captions remapped through the same keep-ranges. |
| Audio | `loudnorm` to -14 LUFS in the cut pass. No denoising. |
| Output | `<output_dir>/<slug>/clip_NN.mp4` + `clip_NN.txt` (title, description, 3 hashtags) + `report.json`. Manual upload. |
| Limits | Reject clip > 60 s after tightening; warn < 15 s. |

## Skill layout

```
yt-shorts/
  SKILL.md              # Claude workflow, ~150 lines, includes rubric + token rules
  README.md             # 6-step install for Spiro
  config.json           # created by setup.py from config.example.json
  config.example.json
  scripts/
    common.py           # paths, config load, venv-python resolution, run_ffmpeg(), short logging
    setup.py            # dependency check, venv, pip, model prefetch, config init, status table
    fetch.py            # yt-dlp: video 1080p mp4, info.json, top comments, chapters -> meta.json
    transcribe.py       # faster-whisper -> words.json (word timestamps), transcript.txt
    candidates.py       # transcript -> candidates.json (<= 25 windows, compact)
    cut.py              # one clip: keep-ranges, face-aware crop, trim+concat, loudnorm -> raw mp4 + keep_ranges.json
    subtitle.py         # one clip: words slice -> remapped ASS -> burn -> final mp4
    run_clips.py        # approved.json -> cut + subtitle per clip -> report.json, caption txt
  workspace/<slug>/     # gitignored per-video artifacts and logs/
  .venv/                # gitignored
```

Dev repo: `~/yt-shorts` (this repo), symlinked to `~/.claude/skills/yt-shorts` for testing. Handoff: zip without `.venv`, `workspace`, `.git`.

## Workflow

Two entry modes, both via `/yt-shorts`:

- `prep [url]` — steps 1-2 only. Zero Claude judgment. Spiro runs it before bed.
- `clip [url]` — steps 1-5. If prep output exists for that video, skips 1-2.
- `setup` — one-time dependency install.

Steps:

1. **fetch.py** `[url]` → downloads best mp4 ≤1080p to `workspace/<slug>/source.mp4`, writes `meta.json` (title, duration, upload date, chapters, top ~30 comments by likes, text only). Prints 5 lines: title, duration, slug, comments found, chapters found.
2. **transcribe.py** `<slug>` → faster-whisper `small.en`, `word_timestamps=True`, VAD filter on. Writes `words.json` (`[{w, s, e}]`) and `transcript.txt`. Prints word count and elapsed time. Claude never reads these files.
3. **candidates.py** `<slug>` → writes `candidates.json`. Prints count. Claude reads this file (~6-10K tokens).
4. **Claude scores** (rubric below), proposes 6-10 titles, AskUserQuestion multi-select. Spiro picks and may adjust ("clip 3 start 2 s earlier", "yellow subtitles", "keep pauses in clip 2"). Claude writes `approved.json`.
5. **run_clips.py** `<slug>` → for each approved clip: cut.py then subtitle.py. Writes `report.json`. Claude reads report.json only, relays folder path and clip list.

### candidates.py algorithm

- Sentences = split transcript at Whisper punctuation `.?!` or word gap > 0.7 s.
- Windows = contiguous sentence runs with raw duration 20-58 s. Every sentence may start a window; grow until the limit; also emit a shorter sub-window when a sentence ends with `?` or an exclamation inside the run. Overlaps allowed. Cap 25 windows, preferring diverse starts (drop windows whose start is within 5 s of a kept one).
- Tightened duration = raw minus collapsed gaps (same rule as cut.py).
- Signals per window: `comment_hits` (count of top-comment keywords ≥5 chars appearing in window text, stopwords removed), `chapter` (title if window midpoint is inside a chapter), `has_question`, `pace` (words/sec vs video median, as ratio).
- Output item: `{id, start, end, dur_raw, dur_tight, opener (first 15 words), gist (first + last sentence), signals}`.

### Claude rubric (lives in SKILL.md)

Score each candidate 1-5 on: Hook (opener stands alone), Self-contained (no dangling references), Payoff (ends on takeaway/punchline), Audience signal (comment_hits, chapter), Emotion/stakes (opinion, story, number, contrast). Sum; drop windows overlapping a higher-scored one by > 50 %. Keep top 6-10. For each: title ≤ 60 chars (curiosity or claim), one-line why, 1-line description, 3 hashtags. Prefer `dur_tight` 25-50 s.

### approved.json

```json
{"slug": "...", "subtitle_color": "white", "clips": [
  {"n": 1, "start": 123.4, "end": 171.9, "title": "...", "description": "...", "hashtags": ["#a","#b","#c"], "remove_silence": true}
]}
```

### cut.py

1. Snap `start` to the start of the nearest word, `end` to the end of the nearest word + 0.4 s pad.
2. Keep-ranges: walk words in range; gap > `gap_threshold` (0.6) → keep `gap_keep/2` (0.125) on each side, drop the middle. Save `keep_ranges.json` (`[[src_start, src_end], ...]`).
3. Face detect: extract one frame at range midpoint (ffmpeg → jpg), OpenCV Haar frontal face. Largest face center x → crop x = clamp(face_x − crop_w/2, 0, iw − crop_w). No face → centered. `config.crop_x_offset` (pixels from center) overrides when set.
4. One ffmpeg pass: for each keep-range `[0:v]trim=a:b,setpts=PTS-STARTPTS[vN]; [0:a]atrim=a:b,asetpts=PTS-STARTPTS[aN]`, `concat`, then `crop=ih*9/16:ih:X:0, scale=1080:1920, fps=30`, audio `loudnorm=I=-14:TP=-1.5:LRA=11`. `libx264 -preset veryfast -crf 20`, `aac 160k`, `+faststart`. Accurate seek (filters, not `-ss` input seek). Output `clip_NN_raw.mp4`.
5. Fail if tightened duration > 60 s (message includes how many seconds over). Warn if < 15 s.

### subtitle.py

1. Load words in range and `keep_ranges.json`; map each word time through the ranges (cumulative offsets). Cuts only happen between words, so no word is dropped.
2. Chunk: accumulate words until 5 words, or a word ending in `.?!,`, or next gap > 0.5 s, or line length > 22 chars; minimum 1 word. Chunk shown from its first word start to last word end (+0.15 s, clipped at next chunk start).
3. ASS: PlayRes 1080x1920, font `Arial Black` fallback `Arial`, size 72, Bold, PrimaryColour white `&H00FFFFFF` or yellow `&H0000FFFF`, OutlineColour black, Outline 4, Shadow 0, BorderStyle 1, Alignment 2 (bottom-center), MarginV 560 (≈ 70 % height). Text uppercased unless `config.subtitle_uppercase` false.
4. Burn: `ffmpeg -i clip_NN_raw.mp4 -vf ass=clip_NN.ass -c:a copy clip_NN.mp4`, run with `cwd` = clip folder and relative paths (avoids Windows drive-colon escaping).
5. Keeps `clip_NN_raw.mp4` so a subtitle restyle does not recut.

### run_clips.py

Loops `approved.json`; per clip writes `clip_NN.txt` (title, blank line, description, hashtags) and appends to `report.json` `{n, status: ok|fail, dur, size_mb, crop: face|center|config, note}`. Prints one line per clip. Full ffmpeg/whisper output goes to `workspace/<slug>/logs/`.

## setup.py

- Detect OS. Check `python >= 3.10`, `ffmpeg`, `ffprobe`, `yt-dlp` on PATH. Missing → print exact command (Mac `brew install ffmpeg yt-dlp`; Windows `winget install Gyan.FFmpeg yt-dlp.yt-dlp`) and exit 1. No system installs performed.
- Create `.venv` next to the skill, `pip install faster-whisper opencv-python-headless`. All scripts are invoked through that venv's python; SKILL.md states the path for both OS (`.venv/bin/python` vs `.venv\Scripts\python.exe`); `common.py` re-execs itself under the venv when run with system python.
- Prefetch Whisper model from `config.whisper_model` (default `small.en`, ~480 MB).
- Copy `config.example.json` → `config.json` if absent. Claude asks Spiro for channel URL once and writes it.
- Print ≤ 8-line status table.

### config.json

```json
{"channel_url": "", "output_dir": "~/shorts", "whisper_model": "small.en",
 "subtitle_color": "white", "subtitle_uppercase": true, "crop_x_offset": null,
 "remove_silence": true, "gap_threshold": 0.6, "gap_keep": 0.25, "max_candidates": 25}
```

## Error handling

Scripts exit non-zero with a one-line reason on the last stdout line; Claude relays it and stops.

- Age-restricted / private → "Needs browser cookies: rerun fetch.py with --cookies-from-browser chrome (or edge)". fetch.py passes the flag through.
- No speech / empty words.json → stop before candidates.
- Face detect fails → center crop, `crop: center` in report.
- Clip > 60 s after tightening → `fail` with seconds over; Claude asks Spiro to shorten.
- ffmpeg non-zero → report note = last 5 stderr lines.
- yt-dlp outdated (common YouTube breakage) → fetch.py suggests `yt-dlp -U`.

## Token discipline (SKILL.md rules)

- Never read `words.json`, `transcript.txt`, `meta.json`, `source.*`, logs. Read only `candidates.json`, `report.json`, and script stdout.
- Scripts print ≤ 10 lines.
- One approval round per video; no re-reading candidates unless Spiro asks.
- Target < 30K tokens per video end to end.

## Testing (on Kiryll's Mac before handoff)

1. Fresh clone → `setup.py` succeeds, status table correct.
2. Full `clip <url>` on a public English talking-head video (~10-20 min): candidates sensible, cuts land on word boundaries, no mid-word audio, captions in sync after silence removal, output 1080x1920 30 fps, loudness ≈ -14 LUFS, every clip ≤ 60 s.
3. `prep` then `clip` split run reuses artifacts, no re-download or re-transcribe.
4. Slug with spaces/unicode in title; ass burn path handling works via cwd trick.
5. Yellow subtitles via config; `crop_x_offset` override; `remove_silence: false` per clip.
6. Token count for one full run < 30K (check session usage).
7. Windows smoke test by Spiro: setup + one video; fix path issues if any.

## Handoff

Zip `yt-shorts/` excluding `.venv`, `workspace`, `.git`. README: (1) install Git for Windows, (2) install Claude Code (desktop app Code tab, or the npm global install from the official docs), (3) `winget install Gyan.FFmpeg yt-dlp.yt-dlp Python.Python.3.12`, (4) unzip to `%USERPROFILE%\.claude\skills\yt-shorts`, (5) in Claude Code run `/yt-shorts setup`, (6) `/yt-shorts prep <url>` at night, `/yt-shorts clip` in the morning.

## Out of scope (v1)

Auto-upload, multi-speaker split-screen, b-roll/motion graphics, karaoke word highlighting, denoising, cloud transcription.

## Amendment 2026-11-01: subtitle rendering without libass

Homebrew's current ffmpeg formula (9.x) ships no libass, so the `ass`, `subtitles` and `drawtext` filters are unavailable on the dev Mac, and the skill must not depend on a particular ffmpeg build. Subtitles are therefore rendered as transparent PNG bands with Pillow (bold TTF from the OS: Arial Black / Arial Bold / Impact on macOS and Windows, DejaVu/Liberation Bold on Linux, `config.subtitle_font_file` override, Pillow default font as last resort) and composited by ffmpeg's core `overlay` filter, one overlay per chunk gated by `enable='between(t,s,e)'`. Look is unchanged: one line, uppercase, white or yellow fill, 4 px black outline, band bottom at 70 % of frame height, long lines shrink to fit inside 60 px side margins. Artifacts per clip: `clip_NN_subs.json` (chunk list) replaces `clip_NN.ass`; PNGs are deleted after a successful burn. `config.subtitle_font` is replaced by `config.subtitle_font_file` (null = auto). `setup.py` installs `Pillow>=10.1`.
