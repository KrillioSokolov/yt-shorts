---
name: yt-shorts
description: Turn a long YouTube talking-head video into vertical 9:16 shorts (max 60 s) with silence removed and white/yellow phrase subtitles burned in. Use when the user asks to clip, cut, repurpose, or make shorts/reels from a YouTube video or from their latest upload. Modes: setup, prep [url], clip [url].
---

# yt-shorts

Scripts do all heavy work. You read only `candidates.json`, `report.json`, and script stdout.
NEVER read or cat: `words.json`, `transcript.txt`, `meta.json`, `source.*`, anything in `logs/`, `clip_NN_subs.json`, or anything under `workspace/<slug>/clips/` except what run_clips.py prints.
Every script prints at most 10 lines. A last line starting with `ERROR:` means stop, relay it verbatim, and suggest the hint it contains.

## Paths

- SKILL = the folder containing this file.
- Venv python (VENV_PY, use for every script except setup.py):
  - macOS/Linux: `SKILL/.venv/bin/python`
  - Windows: `SKILL\.venv\Scripts\python.exe`
- Scripts auto-switch to the skill venv when launched with another python, but prefer the venv python directly so setup errors are visible.
- Workspace: `SKILL/workspace/<slug>/` (slug is printed by fetch.py).
- Output: `output_dir/<slug>/clip_NN.mp4` + `clip_NN.txt` (output_dir from config.json, default `~/shorts`).

## Modes (parse from the arguments; no argument = `clip`)

### setup
1. Run `python3 SKILL/scripts/setup.py` with the SYSTEM python. On this Mac the system `python3` is 3.9; use `/opt/homebrew/bin/python3` or the venv python. On Spiro's Windows use `python`. First run takes 2-5 minutes (model download).
2. Relay the status table. If it ends with `ERROR:` listing missing tools, show the install command and stop.
3. If `channel_url` shows `(not set ...)`, ask the user for their YouTube channel URL and write it into `SKILL/config.json` under `"channel_url"`.

### prep [url]
1. `VENV_PY SKILL/scripts/fetch.py [url]` (omit url to use the latest upload of channel_url). It prints `title:`, `duration:`, `slug:`, `comments:  chapters:`, `source:`. Relay them. Note the slug.
2. `VENV_PY SKILL/scripts/transcribe.py <slug>`. Slow on CPU (about 0.3-1.0x the video length). Run it in the background if the tool allows and tell the user they can leave; progress is in `workspace/<slug>/logs/transcribe.log` (do not read it yourself). Prints `words:`, `audio:`, `elapsed:`, `model:`; relay them.

### clip [url]
1. Run prep steps 1-2 (both are cached: they return instantly when already done).
2. `VENV_PY SKILL/scripts/candidates.py <slug>` (prints `candidates:` count and `file:` path).
3. Read `SKILL/workspace/<slug>/candidates.json`. Score every candidate with the rubric below. It also carries a `score` (comment-keyword density + question bonus - distance from 40 s). Use it as a weak prior only; your rubric decides.
4. Present the top 6-10 with AskUserQuestion (multiSelect: true). Option label: `#<id> <title> (<dur_tight>s)`. Description: one-line why + the opener. Mention they can ask for time nudges, title changes, yellow subtitles, or keeping pauses.
5. Apply requested adjustments (e.g. "clip 3 start 2s earlier" -> start -= 2; "keep pauses in 2" -> `"remove_silence": false`).
6. Write `SKILL/workspace/<slug>/approved.json` (schema below). Numbering `n` starts at 1 in the order chosen.
7. `VENV_PY SKILL/scripts/run_clips.py <slug>` (slug first; optional `--only <n> [<n> ...]`). Lines look like `clip_01  ok     38.2s  4.1MB  crop=face  subs=14` or `clip_02  FAIL  <reason>`, then `output:   <dir>`. Relay them verbatim.
8. If a line says `FAIL ... over the 60s limit`: propose a tighter start or end for that clip, confirm with the user, update approved.json, rerun with `--only <n>`.
9. Finish with: output folder path, list of `clip_NN.mp4` with titles, reminder that `clip_NN.txt` holds the caption.

## Scoring rubric (score each 1-5, sum)

1. Hook: would the `opener` keep a stranger watching with zero context?
2. Self-contained: no "as I said", "this", "that thing" pointing outside the window.
3. Payoff: `gist` ends on a conclusion, punchline, or clear takeaway.
4. Audience signal: `comment_hits` >= 2 or a matching `chapter`.
5. Emotion/stakes: opinion, story, number, contrast, or `has_question`.

Drop a candidate that overlaps a higher-scored one by more than half its length. Prefer `dur_tight` 25-50 s. Reject anything with `dur_tight` > 60.
For each kept candidate write: title (max 60 chars, curiosity or bold claim, no clickbait lies), one-line why, one-line description, 3 hashtags.

## approved.json

```json
{
  "slug": "<slug>",
  "subtitle_color": "white",
  "clips": [
    {"n": 1, "start": 123.4, "end": 171.9, "title": "Why I quit ML for SWE",
     "description": "The one reason that changed everything.", "hashtags": ["#career", "#softwareengineer", "#shorts"],
     "remove_silence": true}
  ]
}
```

`start`/`end` are source-video seconds (from candidates.json, plus any user nudges). `subtitle_color` is `white` or `yellow`. `remove_silence` is optional (default from config).

## Errors you will see

- `ERROR: ... | hint: rerun with --cookies-from-browser chrome` -> rerun fetch.py with that flag.
- `ERROR: ... | hint: ... yt-dlp -U` -> tell the user to run `yt-dlp -U` in a terminal, then retry.
- `ERROR: transcription failed: ...` -> relay; the log is `workspace/<slug>/logs/transcribe.log` (the user may open it, you do not).
- `clip_NN  FAIL  clip is X.Xs over the 60s limit` -> shorten and rerun with `--only NN`.
- `ERROR: existing .venv uses python < 3.10` -> tell the user to delete the `.venv` folder and rerun setup.

## Token rules

- Read only `candidates.json` (once) and script stdout. Read `report.json` only when a FAIL line needs its full note.
- One approval round per video unless the user asks for more.
- Do not open video files, logs, transcripts, or word lists. Do not summarize the whole video.
- Target under 30K tokens per video end to end.
