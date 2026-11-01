"""Faceless explainer videos: voiceover + a sequence of scene images (+ optional title image
and headline), with slow Ken Burns zooms and word-by-word captions.

Vertical layout (top to bottom):
  title image  ->  colored headline strip  ->  scene image (changes with the voiceover)  ->  captions
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import captions as cap
from . import ffmpeg as ff
from .platforms import Platform


@dataclass
class Scene:
    image: Path
    start: float  # seconds into the voiceover when this scene appears


def _fit_font_size(text: str, font: str, max_width: int, max_size: int) -> int:
    """Largest font size (<= max_size) at which `text` fits in max_width pixels."""
    try:
        from PIL import ImageFont
    except ImportError:  # rough fallback: average glyph is ~0.6 em wide
        return min(max_size, int(max_width / (0.6 * max(1, len(text)))))
    size = max_size
    while size > 20:
        f = ImageFont.truetype(font, size)
        left, _, right, _ = f.getbbox(text)
        if right - left <= max_width:
            return size
        size -= 2
    return size


def parse_headline(headline: str) -> list[tuple[str, bool]]:
    """'WHY BILLIONAIRES BUY WATCHES,|[NOT CARS]' -> [(line, is_accent), ...].
    '|' separates lines; a line wrapped in [brackets] uses the accent (second) color."""
    out = []
    for line in headline.split("|"):
        line = line.strip()
        accent = line.startswith("[") and line.endswith("]")
        out.append((line.strip("[]").strip(), accent))
    return [x for x in out if x[0]]


def build(audio: str | Path, scenes: list[Scene], out: str | Path, platform: Platform,
          title_image: str | Path | None = None, headline: str | None = None,
          strip_color: str = "#FFD400", headline_color: str = "#111111", headline_accent: str = "#E3201B",
          background: str = "#0E0E0E", transcript: dict | None = None, caption_color: str = "#FFD400",
          caption_highlight: str = "#FFFFFF", caption_pos: float = 0.86, font: str | None = None,
          zoom: float = 0.10, music: str | None = None, music_volume: float = 0.10) -> Path:
    W, H, fps = platform.width, platform.height, platform.fps
    font = font or ff.find_font()
    total = ff.probe(audio).duration
    scenes = sorted(scenes, key=lambda s: s.start)
    if not scenes:
        raise ValueError("Need at least one scene image.")
    scenes[0] = Scene(scenes[0].image, 0.0)

    # ---- layout
    y = 0
    title_h = int(H * 0.26) if title_image else 0
    lines = parse_headline(headline) if headline else []
    pad = int(H * 0.018)
    line_specs = []  # (text, accent, size, y)
    strip_y = max(0, title_h - int(H * 0.015))
    if lines:
        ly = strip_y + pad
        for i, (text, accent) in enumerate(lines):
            size = _fit_font_size(text, font, int(W * 0.92), int(H * (0.058 if accent else 0.045)))
            line_specs.append((text, accent, size, ly))
            ly += int(size * 1.18)
        strip_h = ly - strip_y + pad
    else:
        strip_h = 0
    scene_y = (strip_y + strip_h + int(H * 0.012)) if (title_image or lines) else int(H * 0.2)
    scene_w = W
    scene_h = int(W * 3 / 4) // 2 * 2  # 4:3 box, the usual shape for illustrations
    if scene_y + scene_h > int(H * caption_pos) - int(H * 0.03):
        scene_h = (int(H * caption_pos) - int(H * 0.03) - scene_y) // 2 * 2

    # Captions sit centered in the space under the scene so they never cover it.
    cap_y = min(caption_pos, (scene_y + scene_h + H) / 2 / H)

    args: list[str] = ["-f", "lavfi", "-i", f"color=c=0x{background.lstrip('#')}:s={W}x{H}:r={fps}:d={total:.3f}"]
    g: list[str] = []
    idx = 1
    # ---- scenes with slow zoom, concatenated
    labels = []
    for i, sc in enumerate(scenes):
        end = scenes[i + 1].start if i + 1 < len(scenes) else total
        dur = max(0.2, end - sc.start)
        frames = max(1, round(dur * fps))
        args += ["-i", str(sc.image)]
        zin = f"z='1+{zoom}*on/{frames}'" if i % 2 == 0 else f"z='{1 + zoom}-{zoom}*on/{frames}'"
        g.append(
            f"[{idx}:v]scale={scene_w * 2}:{scene_h * 2}:force_original_aspect_ratio=increase,"
            f"crop={scene_w * 2}:{scene_h * 2},"
            f"zoompan={zin}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={scene_w}x{scene_h}:fps={fps},"
            f"setsar=1,format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[s{i}]"
        )
        labels.append(f"[s{i}]")
        idx += 1
    g.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[scenes]")

    cur = "0:v"
    if title_image:
        args += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(title_image)]
        g.append(f"[{idx}:v]scale={W}:{title_h}:force_original_aspect_ratio=increase,crop={W}:{title_h},"
                 f"fps={fps},setsar=1[title]")
        g.append(f"[{cur}][title]overlay=0:0:shortest=1[b1]")
        cur = "b1"
        idx += 1
    g.append(f"[{cur}][scenes]overlay=0:{scene_y}:eof_action=repeat[b2]")
    cur = "b2"

    post: list[str] = []
    if lines:
        post.append(f"drawbox=x=0:y={strip_y}:w={W}:h={strip_h}:color=0x{strip_color.lstrip('#')}@1:t=fill")
        for text, accent, size, ly in line_specs:
            color = headline_accent if accent else headline_color
            post.append(
                f"drawtext=fontfile='{ff.escape_filter_path(font)}':expansion=none:"
                f"text='{ff.escape_drawtext(text)}':fontsize={size}:fontcolor=0x{color.lstrip('#')}:"
                f"x=(w-tw)/2:y={ly}"
            )

    with tempfile.TemporaryDirectory() as td:
        if transcript:
            ass = Path(td) / "captions.ass"
            cap.write_ass(ass, transcript, W, H, style="viral", text_color=caption_color,
                          highlight_color=caption_highlight, position=cap_y, words_per_chunk=2, size_scale=0.75)
            post.append(f"subtitles='{ff.escape_filter_path(ass)}'")
        post.append("format=yuv420p")
        g.append(f"[{cur}]{','.join(post)}[v]")

        args += ["-i", str(audio)]
        a_idx = idx
        idx += 1
        g.append(f"[{a_idx}:a]aresample=48000,loudnorm=I=-14:TP=-1.5:LRA=11[voice]")
        alabel = "voice"
        if music:
            args += ["-stream_loop", "-1", "-i", str(music)]
            g.append(f"[{idx}:a]atrim=0:{total:.3f},aresample=48000,volume={music_volume},"
                     f"afade=t=out:st={max(0, total - 2):.3f}:d=2[mus]")
            g.append("[voice]asplit=2[vo][key];[mus][key]sidechaincompress=threshold=0.03:ratio=8[duck];"
                     "[vo][duck]amix=inputs=2:duration=first:normalize=0[mix]")
            alabel = "mix"

        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.run([*args, "-filter_complex", ";".join(g), "-map", "[v]", "-map", f"[{alabel}]",
                "-t", f"{total:.3f}", *ff.video_codec_args(), *ff.audio_codec_args(), str(out)])
    return out
