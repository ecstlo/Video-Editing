"""Core editing operations. Each one is a single ffmpeg pass where possible, so
quality is only lost once."""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg as ff
from .brand import Brand
from .platforms import Platform

# ---------------------------------------------------------------- reframing

def reframe_graph(inp: str, out: str, W: int, H: int, mode: str, src_aspect: float, focus: float = 0.5,
                  zoom: float = 1.0) -> str:
    """Filtergraph fragment turning [inp] into a WxH frame at [out].

    modes: crop (fill frame, cut sides, `focus` 0=left..1=right),
           blur (fit whole frame over a blurred copy, the classic repost look),
           pad  (fit with black bars), auto (crop if aspect is close, else blur)
    zoom (blur mode): enlarge the sharp foreground, trimming its sides (1.3 = 30% bigger)
    """
    target = W / H
    if mode == "auto":
        mode = "crop" if abs(src_aspect - target) / target < 0.15 else "blur"
    if mode == "crop":
        return (
            f"[{inp}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x=(iw-ow)*{focus}:y=(ih-oh)/2,setsar=1[{out}]"
        )
    if mode == "pad":
        return (
            f"[{inp}]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{out}]"
        )
    if mode == "blur":
        bw, bh = max(2, W // 8 // 2 * 2), max(2, H // 8 // 2 * 2)
        return (
            f"[{inp}]split=2[{out}_bg][{out}_fg];"
            f"[{out}_bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"gblur=sigma=6,eq=brightness=-0.12:saturation=1.1,scale={W}:{H}[{out}_bgb];"
            f"[{out}_fg]scale={W}:{H}:force_original_aspect_ratio=decrease"
            + (f",scale=iw*{zoom}:-2,crop=min(iw\\,{W}):min(ih\\,{H}):(iw-ow)*{focus}:(ih-oh)/2" if zoom != 1.0 else "")
            + f"[{out}_fgs];"
            f"[{out}_bgb][{out}_fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]"
        )
    raise ValueError(f"Unknown reframe mode '{mode}' (crop|blur|pad|auto)")


_LOGO_POS = {
    "top-left": "{m}:{m}",
    "top-right": "W-w-{m}:{m}",
    "bottom-left": "{m}:H-h-{m}",
    "bottom-right": "W-w-{m}:H-h-{m}",
}


def _drawtext(text: str, font: str, size: int, color: str = "white", x: str = "(w-tw)/2", y: str = "h*0.12",
              box: bool = True, enable: str | None = None, boxcolor: str = "black@0.55", border: int = 3) -> str:
    parts = [
        f"fontfile='{ff.escape_filter_path(font)}'",
        "expansion=none",  # treat % literally (e.g. "5% rule")
        f"text='{ff.escape_drawtext(text)}'",
        f"fontsize={size}",
        f"fontcolor={color}",
        f"x={x}",
        f"y={y}",
        f"borderw={border}",
        "bordercolor=black@0.8",
    ]
    if box:
        parts += ["box=1", f"boxcolor={boxcolor}", f"boxborderw={max(8, size // 3)}"]
    if enable:
        parts.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(parts)


def _wrap(text: str, max_chars: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def text_block_filters(text: str, font: str, W: int, H: int, y_frac: float, size_frac: float = 0.045,
                       enable: str | None = None, color: str = "white", boxcolor: str = "black@0.55",
                       border: int = 3) -> list[str]:
    """Centered, word-wrapped multi-line text (one drawtext per line)."""
    size = int(min(W, H) * size_frac * (1.0 if H > W else 0.8))
    max_chars = max(10, int(W / (size * 0.55)))
    lines = _wrap(text, max_chars)
    line_h = int(size * 1.45)
    return [
        _drawtext(line, font, size, color=color, y=f"{int(H * y_frac) + i * line_h}", enable=enable, boxcolor=boxcolor,
                  border=border)
        for i, line in enumerate(lines)
    ]


# ---------------------------------------------------------------- render

@dataclass
class RenderOptions:
    start: float | None = None
    end: float | None = None
    mode: str = "auto"
    focus: float = 0.5
    zoom: float = 1.0
    ass_path: str | None = None
    hook: str | None = None           # big headline text at the top of the video
    hook_seconds: float | None = None # None = whole clip
    cta: str | None = None            # e.g. "Follow for Part 2" - replaces the hook at the end
    cta_seconds: float = 4.0          # how long the call to action shows at the end
    watermark: bool = True            # show brand logo/handle
    music: str | None = None
    music_volume: float = 0.15
    duck: bool = True                 # lower music while someone is talking
    loudnorm: bool = True
    speed: float = 1.0
    crf: int = 20
    fps: int | None = None
    fade: float = 0.0                 # fade in/out seconds


def render(src: str | Path, out: str | Path, platform: Platform, brand: Brand | None = None,
           opts: RenderOptions | None = None) -> Path:
    """Trim, reframe, caption, brand, mix music and encode for one platform, in one pass."""
    brand = brand or Brand()
    opts = opts or RenderOptions()
    info = ff.probe(src)
    W, H = platform.width, platform.height
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = []
    if opts.start is not None:
        args += ["-ss", f"{opts.start:.3f}"]
    if opts.end is not None:
        args += ["-to", f"{opts.end:.3f}"]
    args += ["-i", str(src)]
    clip_len = (opts.end if opts.end is not None else info.duration) - (opts.start or 0.0)
    clip_len /= opts.speed

    inputs = 1
    logo_idx = music_idx = None
    if opts.watermark and brand.logo:
        args += ["-i", brand.logo]
        logo_idx = inputs
        inputs += 1
    if opts.music:
        args += ["-stream_loop", "-1", "-i", opts.music]
        music_idx = inputs
        inputs += 1

    g: list[str] = []
    vchain = "0:v"
    if opts.speed != 1.0:
        g.append(f"[0:v]setpts=PTS/{opts.speed}[vs]")
        vchain = "vs"
    g.append(reframe_graph(vchain, "vr", W, H, opts.mode, info.aspect or 1, opts.focus, opts.zoom))
    cur = "vr"

    post: list[str] = []
    fps = opts.fps or platform.fps
    post.append(f"fps={fps}")
    if opts.ass_path:
        fontsdir = f":fontsdir='{ff.escape_filter_path(Path(brand.font).parent)}'" if brand.font else ""
        post.append(f"subtitles='{ff.escape_filter_path(opts.ass_path)}'{fontsdir}")
    font = brand.font or ff.find_font()
    cta_start = max(0.0, clip_len - opts.cta_seconds) if opts.cta else None
    if opts.hook:
        hook_end = min(x for x in (opts.hook_seconds, cta_start) if x is not None) \
            if (opts.hook_seconds or cta_start is not None) else None
        enable = f"lt(t,{hook_end:.3f})" if hook_end is not None else None
        # TikTok-style headline: black text on a white box.
        post += text_block_filters(opts.hook, font, W, H, y_frac=0.12 if H > W else 0.06, size_frac=0.066,
                                   enable=enable, color="black", boxcolor="white@0.95", border=0)
    if opts.cta:
        # Call to action in the brand accent color, swapped in where the hook was.
        post += text_block_filters(opts.cta, font, W, H, y_frac=0.12 if H > W else 0.06, size_frac=0.07,
                                   enable=f"gte(t,{cta_start:.3f})", color="black",
                                   boxcolor=brand.accent_color + "@0.97", border=0)
    if opts.watermark and brand.handle and not brand.logo:
        size = int(min(W, H) * 0.032)
        post.append(_drawtext(brand.handle, font, size, color="white@0.85", x="(w-tw)/2", y="h*0.80", box=False))
    if opts.fade > 0:
        post.append(f"fade=t=in:st=0:d={opts.fade}")
        post.append(f"fade=t=out:st={max(0, clip_len - opts.fade):.3f}:d={opts.fade}")
    post.append("format=yuv420p")
    g.append(f"[{cur}]{','.join(post)}[vp]")
    cur = "vp"

    if logo_idx is not None:
        lw = int(W * brand.logo_scale)
        m = int(W * 0.04)
        pos = _LOGO_POS.get(brand.logo_position, _LOGO_POS["top-right"]).format(m=m)
        g.append(f"[{logo_idx}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.9[logo]")
        g.append(f"[{cur}][logo]overlay={pos}:format=auto[vl]")
        cur = "vl"

    # ---- audio
    acur = None
    if info.has_audio:
        achain = ["aresample=48000"]
        if opts.speed != 1.0:
            achain.append(_atempo(opts.speed))
        if opts.loudnorm:
            achain.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        if opts.fade > 0:
            achain.append(f"afade=t=in:st=0:d={opts.fade}")
            achain.append(f"afade=t=out:st={max(0, clip_len - opts.fade):.3f}:d={opts.fade}")
        g.append(f"[0:a]{','.join(achain)}[av]")
        acur = "av"
    if music_idx is not None:
        mf = [f"atrim=0:{clip_len:.3f}", "aresample=48000", f"volume={opts.music_volume}",
              f"afade=t=out:st={max(0, clip_len - 1.5):.3f}:d=1.5"]
        g.append(f"[{music_idx}:a]{','.join(mf)}[mus]")
        if acur:
            if opts.duck:
                g.append(f"[{acur}]asplit=2[voice][key]")
                g.append("[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
                g.append("[voice][duck]amix=inputs=2:duration=first:normalize=0[am]")
            else:
                g.append(f"[{acur}][mus]amix=inputs=2:duration=first:normalize=0[am]")
            acur = "am"
        else:
            acur = "mus"

    args += ["-filter_complex", ";".join(g), "-map", f"[{cur}]"]
    if acur:
        args += ["-map", f"[{acur}]", *ff.audio_codec_args()]
    args += ["-t", f"{clip_len:.3f}", *ff.video_codec_args(crf=opts.crf),
             "-maxrate", platform.video_bitrate_cap, "-bufsize", "24M", str(out)]
    ff.run(args)
    return out


def _atempo(speed: float) -> str:
    # atempo accepts 0.5-2.0 per instance; chain for bigger changes.
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


# ---------------------------------------------------------------- simple ops

def cut(src: str | Path, out: str | Path, start: float, end: float, copy: bool = False) -> Path:
    """Trim a section. copy=True is instant but snaps to keyframes."""
    args = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src)]
    args += ["-c", "copy"] if copy else [*ff.video_codec_args(crf=18), *ff.audio_codec_args()]
    ff.run([*args, str(out)])
    return Path(out)


def detect_silence(src: str | Path, threshold_db: float = -35, min_silence: float = 0.5) -> list[tuple[float, float]]:
    err = ff.run_stderr(["-i", str(src), "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    dur = ff.probe(src).duration
    if len(ends) < len(starts):
        ends.append(dur)
    return [(max(0.0, s), e) for s, e in zip(starts, ends)]


def remove_silence(src: str | Path, out: str | Path, threshold_db: float = -35, min_silence: float = 0.5,
                   pad: float = 0.12) -> tuple[Path, float, float]:
    """Cut out dead air ("jump cuts"). Returns (path, old_duration, new_duration)."""
    info = ff.probe(src)
    silences = detect_silence(src, threshold_db, min_silence)
    keep, cursor = [], 0.0
    for s, e in silences:
        s2, e2 = s + pad, e - pad
        if s2 > cursor:
            keep.append((cursor, s2))
        cursor = max(cursor, e2)
    if cursor < info.duration:
        keep.append((cursor, info.duration))
    keep = [(a, b) for a, b in keep if b - a > 0.05]
    if not keep:
        raise ValueError("Everything was detected as silence. Try a lower --threshold, e.g. -45.")
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    new_dur = sum(b - a for a, b in keep)
    graph = (f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
             f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]")
    script = None
    if len(graph) < 20000:
        fc = ["-filter_complex", graph]
    else:  # very long videos: pass the graph via a file to dodge command-line limits
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(graph)
            script = f.name
        fc = ["-filter_complex_script", script]
    ff.run(["-i", str(src), *fc, "-map", "[v]", "-map", "[a]",
            *ff.video_codec_args(crf=18), *ff.audio_codec_args(), str(out)])
    if script:
        Path(script).unlink(missing_ok=True)
    return Path(out), info.duration, new_dur


def concat(inputs: list[str | Path], out: str | Path, platform: Platform, transition: str = "fade",
           tdur: float = 0.5, mode: str = "auto") -> Path:
    """Join clips into one video at the platform's size, with optional transitions
    (any xfade name: fade, slideleft, wipeleft, circleopen, dissolve, ... or 'none')."""
    W, H, fps = platform.width, platform.height, platform.fps
    infos = [ff.probe(p) for p in inputs]
    args: list[str] = []
    g: list[str] = []
    for i, (p, info) in enumerate(zip(inputs, infos)):
        args += ["-i", str(p)]
    for i, info in enumerate(infos):
        g.append(reframe_graph(f"{i}:v", f"r{i}", W, H, mode, info.aspect or 1))
        g.append(f"[r{i}]fps={fps},format=yuv420p,settb=AVTB[v{i}]")
        if info.has_audio:
            g.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            g.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{info.duration:.3f}[a{i}]")
    n = len(inputs)
    if transition == "none" or n == 1:
        g.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
    else:
        offset, vprev, aprev = 0.0, "v0", "a0"
        for i in range(1, n):
            offset += infos[i - 1].duration - tdur
            g.append(f"[{vprev}][v{i}]xfade=transition={transition}:duration={tdur}:offset={offset:.3f}[vx{i}]")
            g.append(f"[{aprev}][a{i}]acrossfade=d={tdur}[ax{i}]")
            vprev, aprev = f"vx{i}", f"ax{i}"
        g.append(f"[{vprev}]null[v];[{aprev}]anull[a]")
    ff.run([*args, "-filter_complex", ";".join(g), "-map", "[v]", "-map", "[a]",
            *ff.video_codec_args(), *ff.audio_codec_args(), str(out)])
    return Path(out)


def thumbnail(src: str | Path, out: str | Path, at: float | None = None) -> Path:
    """Grab a frame (defaults to 1/3 in) as a JPG, for covers or for Claude to look at."""
    t = at if at is not None else ff.probe(src).duration / 3
    ff.run(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)])
    return Path(out)


def contact_sheet(src: str | Path, out: str | Path, every: float = 5.0, cols: int = 5) -> Path:
    """A grid of frames every N seconds, so you (or Claude) can see the whole video at a glance."""
    dur = ff.probe(src).duration
    n = max(1, int(dur // every))
    rows = (n + cols - 1) // cols
    vf = (f"fps=1/{every},scale=384:-2,drawtext=fontfile='{ff.escape_filter_path(ff.find_font())}':"
          f"text='%{{pts\\:hms}}':x=6:y=6:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6,"
          f"tile={cols}x{rows}")
    ff.run(["-i", str(src), "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)])
    return Path(out)


def stabilize(src: str | Path, out: str | Path, smoothing: int = 15) -> Path:
    """Two-pass stabilization for shaky handheld walkthroughs (needs ffmpeg with vid.stab)."""
    with tempfile.TemporaryDirectory() as td:
        trf = Path(td) / "transforms.trf"
        ff.run(["-i", str(src), "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result='{ff.escape_filter_path(trf)}'",
                "-f", "null", "-"])
        ff.run(["-i", str(src), "-vf",
                f"vidstabtransform=input='{ff.escape_filter_path(trf)}':smoothing={smoothing}:zoom=3,unsharp=5:5:0.8:3:3:0.4",
                *ff.video_codec_args(crf=18), "-c:a", "copy", str(out)])
    return Path(out)


def color_grade(src: str | Path, out: str | Path, look: str = "bright") -> Path:
    """Quick looks. 'bright' is the airy listing-photo look; 'punchy' suits social clips."""
    looks = {
        "bright": "eq=brightness=0.04:contrast=1.06:saturation=1.12:gamma=1.05,unsharp=5:5:0.5",
        "punchy": "eq=contrast=1.15:saturation=1.3,unsharp=5:5:0.7",
        "warm": "colorbalance=rs=0.06:gs=0.02:bs=-0.06,eq=saturation=1.1",
        "cinematic": "eq=contrast=1.1:saturation=0.9,colorbalance=rs=-0.03:bs=0.05:rh=0.05:bh=-0.04",
    }
    if look not in looks:
        raise ValueError(f"Unknown look '{look}'. Choose: {', '.join(looks)}")
    ff.run(["-i", str(src), "-vf", looks[look], *ff.video_codec_args(crf=18), "-c:a", "copy", str(out)])
    return Path(out)
