# yt-shorts — YouTube long video → vertical shorts

Runs inside Claude Code. Scripts handle download, transcription, cutting and subtitles; Claude picks the moments with you.

**Not a developer? Read [SPIRO-START.md](SPIRO-START.md) instead.** It has a one-message install you paste into Claude Code, and a double-click installer (`install.ps1`) as a fallback. The steps below are the manual version.

## Install (Windows)

1. Install Git for Windows: https://git-scm.com/download/win (defaults are fine).
2. Install Claude Code: use the Claude desktop app's **Code** tab, or follow the install guide at https://docs.anthropic.com/en/docs/claude-code. Sign in with your Claude account (Pro plan works).
3. Open PowerShell and run these four lines, one at a time:
   ```
   winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
   winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
   winget install yt-dlp.yt-dlp --accept-source-agreements --accept-package-agreements
   winget install DenoLand.Deno --accept-source-agreements --accept-package-agreements
   ```
   (Any ffmpeg build works; subtitles do not need libass. Deno lets yt-dlp read YouTube's player code.)
   If winget is missing or fails: install Python 3.12 from https://www.python.org/downloads/windows/ with **Add python.exe to PATH** ticked, and download the ffmpeg zip from https://www.gyan.dev/ffmpeg/builds/, unzip it, and add its `bin` folder to PATH.
   Then fully quit Claude Code (or the desktop app) and start it again so it sees the new PATH.
4. Unzip this folder to `%USERPROFILE%\.claude\skills\yt-shorts` (so `SKILL.md` sits directly inside `yt-shorts`).
5. Start Claude Code and run `/yt-shorts setup`. First run downloads the speech model (~480 MB) and takes a few minutes. Give it your channel URL when asked.
6. Use it:
   - Before bed: `/yt-shorts prep https://youtube.com/watch?v=...` (or just `/yt-shorts prep` for your latest upload). Transcription is slow on an older PC; leave it running.
   - Next morning: `/yt-shorts clip`. Pick the clips you like, then find them in a folder named after the video inside `%USERPROFILE%\shorts`.
7. Overnight run: plug in the PC and set Windows Sleep to **Never** (Settings > System > Power) while it transcribes, or the PC falls asleep and the job stops.

## Install (macOS)

1. `brew install ffmpeg yt-dlp deno`
2. Clone or unzip to `~/.claude/skills/yt-shorts`, then `/yt-shorts setup` in Claude Code.
3. Homebrew's python3 may be newer than the wheels available for faster-whisper. If setup fails on pip, create the venv with Python 3.12 first: `uv venv --seed --python 3.12 .venv` (install uv from https://docs.astral.sh/uv/) and rerun setup with `.venv/bin/python scripts/setup.py`.

## Settings (`config.json`)

| key | default | meaning |
|---|---|---|
| `channel_url` | "" | Your channel; used when no URL is given |
| `output_dir` | `~/shorts` | Where finished clips go |
| `whisper_model` | `small.en` | `medium.en` = better, ~3x slower |
| `subtitle_color` | `white` | or `yellow` |
| `subtitle_font_file` | null | Path to a bold .ttf; null = Arial Black/Arial Bold/Impact from the OS |
| `subtitle_uppercase` | true | ALL CAPS captions |
| `crop_x_offset` | null | Pixels left/right of center to crop; null = auto face detect |
| `remove_silence` | true | Cut pauses longer than `gap_threshold` |
| `gap_threshold` / `gap_keep` | 0.6 / 0.25 | Pause length that gets cut, and how much stays |
| `max_candidates` | 25 | How many segments Claude gets to choose from |

## Troubleshooting

- `ERROR: ... Sign in to confirm` → age-restricted video. Close Firefox and tell Claude: "rerun fetch with the same URL and --cookies-from-browser firefox" (Chrome/Edge cookies usually fail on Windows).
- `ERROR: ... install deno` → run `winget install DenoLand.Deno --accept-source-agreements --accept-package-agreements`, fully quit and restart Claude Code, try again.
- `ERROR: Unable to extract` → YouTube changed; run `yt-dlp -U`.
- `Captions out of sync` → tell Claude "keep pauses in clip N" (disables silence removal for that clip) and rerun.
- `Setup says python >= 3.10 required` → install Python 3.12 (winget on Windows, `uv`/Homebrew on Mac) and rerun.

## For the person packaging this

Build the zip from git, never by zipping the working folder (it contains `config.json`, `.venv` and `workspace`):
`git archive --format=zip --prefix=yt-shorts/ -o yt-shorts.zip HEAD`
