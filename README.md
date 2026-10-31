# vedit: a video editor you drive with Claude

A scriptable video editor built on **FFmpeg** and **Whisper** for two jobs:

1. **Social clips.** Find the best moments in a long video, cut them, reframe to vertical, add animated
   TikTok-style captions and a hook headline, then export a correctly sized file for every platform.
2. **Real estate.** Turn listing photos into animated listing videos, or walkthrough clips into
   branded property tours with price and address overlays, music, and an agent contact end card.

Everything runs locally and is free. You can run the commands yourself, but the intended way to use it is to open this
folder in **Claude Code** and describe what you want in plain English. `CLAUDE.md` tells Claude how to use the toolkit.

---

## Setup (one time)

1. **Install FFmpeg**
   - macOS: `brew install ffmpeg`
   - Windows: `winget install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
2. **Install Python 3.10+**, then from this folder run:
   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e '.[transcribe]'
   ```
   The `[transcribe]` extra installs faster-whisper for captions. The speech model downloads automatically on first use.
3. **Fill in your brand kits** in `brands/viral.json` and `brands/realestate.json`: logo path, handle, colors,
   and contact details. Put logos and music in `assets/`.
4. Put source videos and photos in `footage/`. Renders go to `output/`. Neither folder is committed to git.

## Talking to Claude (recommended)

Open this folder in Claude Code and ask things like:

- *"Find the 3 best 30–45s moments in footage/podcast.mp4 and export them for all vertical platforms with viral captions."*
- *"Clip 12:05–12:48 from footage/interview.mp4, crop on the person on the left, hook text: 'He wasn't ready for this'."*
- *"Make a Just Listed reel from footage/123-main/ photos: $849,000, 123 Main St, 3 bd | 2 ba | 1,800 sqft, label the rooms."*
- *"Stabilize my walkthrough clips, brighten them, and make a property tour for Reels and YouTube with music."*

Claude reads the transcript to pick moments with real hooks and payoffs, which beats the keyword heuristic. It
renders the clips, then checks the output by looking at frames before handing it to you.

## Command reference

```bash
vedit platforms                                   # list export sizes / limits
vedit info footage/video.mp4

# --- Social clips
vedit transcribe footage/video.mp4               # -> .transcript.json / .transcript.txt / .srt
vedit highlights footage/video.transcript.json --min 20 --max 50 --top 5
vedit clip footage/video.mp4 --start 1:02 --end 1:41 --hook "Wait for it" \
     --brand brands/viral.json --platforms vertical
vedit auto footage/video.mp4 --top 3 --brand brands/viral.json --platforms vertical   # end-to-end
vedit silence footage/talking.mp4 -o footage/talking_tight.mp4                         # jump cuts

# --- Real estate
vedit listing footage/123-main/ --price '$849,000' --address '123 Main St, Austin TX' \
     --details '3 bd | 2 ba | 1,800 sqft' --status 'Just Listed' \
     --labels 'Kitchen,Living Room,Primary Suite,Backyard' \
     --brand brands/realestate.json --music assets/music.mp3 --platforms realestate
vedit stabilize footage/walk1.mp4 -o footage/walk1_stab.mp4
vedit grade footage/walk1_stab.mp4 -o footage/walk1_final.mp4 --look bright
vedit tour footage/walk*_final.mp4 --price '$849,000' --address '123 Main St' \
     --brand brands/realestate.json --music assets/music.mp3 --platforms reels,youtube
vedit endcard --brand brands/realestate.json -o output/endcard.mp4

# --- Utilities
vedit concat a.mp4 b.mp4 c.mp4 -o joined.mp4 --platform reels --transition slideleft
vedit thumb video.mp4 -o cover.jpg --at 0:12
vedit sheet video.mp4 -o sheet.jpg --every 10      # frame grid to review a video quickly
```

Useful `clip`/`auto` flags:

| Flag | What it does |
|---|---|
| `--platforms` | `vertical` (TikTok, Reels, Shorts, FB, X, LinkedIn), `all`, `realestate`, or a list like `tiktok,youtube` |
| `--captions` | `viral` (big words with the current word highlighted), `clean`, `minimal`, `none` |
| `--mode` | `auto`, `crop` (fill the frame), `blur` (whole frame over a blurred background), `pad` |
| `--focus` | with `crop`: `0` keeps the left side, `0.5` the center, `1` the right side |
| `--hook`, `--hook-seconds` | headline at the top of the video |
| `--music`, `--music-volume` | background track, ducked automatically under speech |
| `--speed 1.1` | slightly faster pacing |

Vertical platforms share one size, so the clip is rendered once and copied for each platform.
Audio is normalized to -14 LUFS, the loudness most platforms target.

## Posting to every platform

This toolkit makes the files. It does not upload them, because every platform needs its own approved developer app
to post through its API. Practical options:
- Upload manually, or use a scheduler (Buffer, Later, Metricool, Repurpose.io) and point it at `output/`.
- Ask Claude to write the caption, hashtags and title for each clip from its transcript.

## Before you post someone else's content

Reposting clips of other people's videos without permission can get you copyright strikes, demonetized or banned,
even with credit given. Lower-risk approaches:
- Get permission or a license (many creators welcome clippers, and some run paid clipping programs).
- Clip content you own, or content explicitly licensed for reuse.
- Add real commentary or transformation, not just captions. This helps but is not a guaranteed fair-use defense.

## Real estate compliance reminders

Check your state's advertising rules. Many require your brokerage name and license number on ads; set `license` and
`title` in `brands/realestate.json`, and they appear on the end card. Only use music you're licensed to use
(platform libraries or royalty-free tracks).
