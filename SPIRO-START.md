# yt-shorts: quick start (no tech skills needed)

This turns one of your long YouTube videos into several vertical shorts (under 60 seconds, captions burned in, pauses cut out). Claude picks the moments with you.

## One-time setup (about 15 minutes, mostly waiting)

**Step 1. Get Claude Code.**
Install the Claude desktop app from https://claude.ai/download, sign in with your Claude account, and open the **Code** tab. That is Claude Code.

**Step 2. Install the skill. Pick ONE way.**

*Way A (easiest): let Claude do it.* In Claude Code, paste this whole message and press Enter:

```
Install the yt-shorts skill for me. Download https://github.com/KrillioSokolov/yt-shorts/archive/refs/heads/main.zip,
unzip it so that SKILL.md ends up directly inside ~/.claude/skills/yt-shorts, then run
py -3.12 ~/.claude/skills/yt-shorts/scripts/setup.py and install anything it reports missing with winget
(Git.Git, Python.Python.3.12, Gyan.FFmpeg, yt-dlp.yt-dlp, DenoLand.Deno). I am not a developer:
explain each step in plain words and tell me when I need to click Yes.
```
Click **Yes** whenever Claude asks permission. When it says done, fully quit Claude Code and open it again.

*Way B: the installer file.* Download https://github.com/KrillioSokolov/yt-shorts/archive/refs/heads/main.zip, right-click the zip, **Extract All**. Open the extracted folder, right-click `install.ps1`, choose **Run with PowerShell**, click Yes on prompts, wait for "Done". Then fully quit Claude Code and open it again.

**Step 3. Tell it your channel.** In Claude Code type `/yt-shorts setup`. It will ask for your YouTube channel link once.

## Every time you want shorts

- **Evening** (it is slow on an older PC, let it run): `/yt-shorts prep https://youtube.com/watch?v=...`
  Plug the laptop in and set Windows Sleep to Never for the night.
- **Morning:** `/yt-shorts clip`
  Claude shows you a list of possible moments with titles. Tick the ones you like. You can say things like "make clip 2 start 3 seconds earlier", "yellow captions", or "keep the pauses in clip 4".
- Finished videos land in a folder named after the video inside `C:\Users\<you>\shorts`. Each clip has a `.txt` next to it with a ready title, description and hashtags. Upload by hand to YouTube Shorts, Instagram Reels or TikTok.

## If something goes wrong

- Claude shows a line starting with `ERROR:` → read it, it usually says what to do. Paste it back to Claude and ask "what should I do?".
- "install deno" in the error → in Claude Code say: `run winget install DenoLand.Deno then retry`.
- Captions out of sync on one clip → say "keep pauses in clip N" and rerun.
- A clip is rejected as over 60 seconds → tell Claude to shorten it; it will suggest a new start or end.
- Anything else: send the error text to Kereal.
