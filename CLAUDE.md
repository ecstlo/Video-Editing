# Instructions for Claude: acting as the video editor

The user makes (1) short-form clips for TikTok/Reels/Shorts/FB/X/LinkedIn and (2) real-estate marketing videos.
They describe edits in plain English. You do the editing with the `vedit` CLI (see README.md), or with raw
`ffmpeg` when vedit lacks a feature. If you add a reusable feature, add it to vedit.

## Layout
- `vedit/`: the toolkit (`edit.py` render engine, `captions.py`, `highlights.py`, `realestate.py`, `platforms.py`, `cli.py`)
- `footage/`: source media (gitignored). `output/`: renders (gitignored). `assets/`: logos, music, fonts.
- `brands/viral.json`, `brands/realestate.json`: brand kits. Use the matching one by default.

## Workflow for social clips
1. `vedit info` the file. If there's no `<name>.transcript.json`, run `vedit transcribe`.
2. Pick moments by **reading `<name>.transcript.txt` yourself**. `vedit highlights` is only a rough keyword
   heuristic. Good clips: a strong hook in the first 1-3 seconds, one complete idea or story, a clear payoff, 15-60s,
   starting and ending on sentence boundaries. Start slightly before the first word (~0.2s), end ~0.4s after the last.
3. Write a short hook headline (under 8 words) for each clip unless the user says not to.
4. Render with `vedit clip ... --brand brands/viral.json --platforms vertical` (or what the user asked for).
5. **Verify before reporting**: pull 2-3 frames with
   `ffmpeg -ss <t> -i out.mp4 -frames:v 1 frame.jpg` (or `vedit sheet`) and look at them. Check that the subject
   is in frame (if not, re-render with `--mode crop --focus 0.2/0.8` or `--mode blur`) and captions are readable.
6. Report each file, its time range, and the hook. Offer a caption and hashtags per platform.

## Workflow for real estate
- Photos: `vedit listing <folder> --price --address --details --status --labels --brand brands/realestate.json`.
  Look at the photos first to order them (exterior first, then living, kitchen, primary suite, outdoor) and to
  write accurate room labels. Rename files or pass them in order explicitly.
- Walkthrough video: `vedit stabilize` shaky phone footage, `vedit grade --look bright`, then `vedit tour`.
- Default platforms for real estate: `realestate` group (vertical + YouTube landscape + 4:5 feed).
- Never invent property facts (price, beds/baths, sqft). Ask if they weren't given.

## Rules
- Never overwrite the user's source files. Write to `output/` or new filenames.
- Long renders: tell the user roughly what's happening. Prefer one test render before batch-exporting.
- If a user wants to repost other creators' content, briefly remind them about permission/copyright once, then help.
- Run `python -m pytest -q` after changing vedit code.
