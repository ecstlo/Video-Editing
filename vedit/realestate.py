"""Real-estate helpers: listing slideshows from photos, branded end cards, and
property tours stitched from walkthrough clips."""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import ffmpeg as ff
from .brand import Brand
from .edit import RenderOptions, _drawtext, concat, render, text_block_filters
from .platforms import Platform

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff"}


def _hex(c: str) -> str:
    return "0x" + c.lstrip("#")


def end_card(brand: Brand, platform: Platform, out: str | Path, seconds: float = 4.0,
             headline: str = "Schedule a private showing") -> Path:
    """A solid brand-color card with logo + agent contact details."""
    W, H = platform.width, platform.height
    font = brand.font or ff.find_font()
    args = ["-f", "lavfi", "-i", f"color=c={_hex(brand.background_color)}:s={W}x{H}:r={platform.fps}:d={seconds}",
            "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo"]
    g, cur = [], "0:v"
    portrait = H > W
    y = 0.30 if portrait else 0.18
    if brand.logo:
        args += ["-i", brand.logo]
        lw = int(W * (0.45 if portrait else 0.22))
        g.append(f"[2:v]scale={lw}:-1[logo]")
        g.append(f"[{cur}][logo]overlay=(W-w)/2:H*{0.12 if portrait else 0.08}[bg]")
        cur = "bg"
        y = 0.40 if portrait else 0.42
    filters = text_block_filters(headline, font, W, H, y_frac=y, size_frac=0.055, boxcolor="black@0")
    line_size = int(min(W, H) * (0.042 if portrait else 0.034))
    yy = int(H * (y + (0.12 if portrait else 0.16)))
    for i, line in enumerate(brand.contact_lines):
        size = int(line_size * (1.25 if i == 0 else 0.9))
        filters.append(_drawtext(line, font, size, color=brand.primary_color, y=str(yy), box=False))
        yy += int(size * 1.6)
    filters.append(f"fade=t=in:st=0:d=0.4,format=yuv420p")
    g.append(f"[{cur}]{','.join(filters)}[v]")
    ff.run([*args, "-filter_complex", ";".join(g), "-map", "[v]", "-map", "1:a", "-t", str(seconds),
            *ff.video_codec_args(), *ff.audio_codec_args(), str(out)])
    return Path(out)


def _photo_clip_graph(i: int, photo: Path, W: int, H: int, D: float, fps: int, motion: int) -> tuple[list[str], str]:
    """Returns (input args, filter fragment producing [p{i}])."""
    frames = int(D * fps)
    try:
        info = ff.probe(photo)
        p_aspect = info.width / info.height if info.height else 1.5
    except ff.FFmpegError:
        p_aspect = 1.5
    target = W / H
    if p_aspect > target * 1.3:
        # Wide photo in a taller frame: slow pan across it so nothing important is lost.
        sh = int(H * 1.04) // 2 * 2
        direction = f"(iw-ow)*t/{D}" if motion % 2 == 0 else f"(iw-ow)*(1-t/{D})"
        frag = (f"[{i}:v]scale=-2:{sh},crop={W}:{H}:x='{direction}':y=(ih-oh)/2,"
                f"fps={fps},setsar=1,format=yuv420p,trim=duration={D},setpts=PTS-STARTPTS[p{i}]")
        return ["-loop", "1", "-framerate", str(fps), "-t", f"{D}", "-i", str(photo)], frag
    # Similar aspect: Ken Burns zoom in / out on an oversampled image (reduces jitter).
    zooms = [
        f"z='1+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        f"z='1.12-0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        f"z='1.1':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'",
        f"z='1.1':x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'",
    ]
    frag = (f"[{i}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
            f"zoompan={zooms[motion % len(zooms)]}:d={frames}:s={W}x{H}:fps={fps},"
            f"setsar=1,format=yuv420p,trim=duration={D},setpts=PTS-STARTPTS[p{i}]")
    return ["-i", str(photo)], frag


def listing_video(photos: list[str | Path], out: str | Path, platform: Platform, brand: Brand,
                  address: str = "", price: str = "", details: str = "", labels: list[str] | None = None,
                  seconds_per_photo: float = 3.0, transition: str = "fade", tdur: float = 0.6,
                  music: str | None = None, music_volume: float = 0.6, end_card_seconds: float = 4.0,
                  status: str = "") -> Path:
    """Photos -> animated listing video with title, room labels, music and an agent end card."""
    photos = [Path(p) for p in photos]
    if not photos:
        raise ValueError("No photos given.")
    W, H, fps = platform.width, platform.height, platform.fps
    D = seconds_per_photo
    font = brand.font or ff.find_font()
    labels = labels or []

    with tempfile.TemporaryDirectory() as td:
        card = end_card(brand, platform, Path(td) / "end.mp4", end_card_seconds) if end_card_seconds > 0 else None
        args: list[str] = []
        g: list[str] = []
        for i, p in enumerate(photos):
            a, frag = _photo_clip_graph(i, p, W, H, D, fps, i)
            args += a
            g.append(frag)
        n = len(photos)

        # Text overlays on each photo segment (before transitions so they move with the slide).
        for i in range(n):
            f: list[str] = []
            if i == 0:
                portrait = H > W
                if status:
                    f += text_block_filters(status.upper(), font, W, H, y_frac=0.08 if portrait else 0.06,
                                            size_frac=0.04, boxcolor=brand.accent_color + "@0.9", color="black", border=0)
                block_y = 0.62
                if price:
                    f += text_block_filters(price, font, W, H, y_frac=block_y, size_frac=0.07)
                    block_y += 0.075 if portrait else 0.11
                if address:
                    f += text_block_filters(address, font, W, H, y_frac=block_y, size_frac=0.042)
                    block_y += 0.05 if portrait else 0.08
                if details:
                    f += text_block_filters(details, font, W, H, y_frac=block_y, size_frac=0.036)
            elif i - 1 < len(labels) and labels[i - 1]:
                f += text_block_filters(labels[i - 1], font, W, H, y_frac=0.80 if H > W else 0.82, size_frac=0.04,
                                        enable=f"between(t,0.3,{D - 0.3})")
            if f:
                g.append(f"[p{i}]{','.join(f)}[t{i}]")
            else:
                g.append(f"[p{i}]null[t{i}]")

        clips = [f"t{i}" for i in range(n)]
        durs = [D] * n
        if card:
            args += ["-i", str(card)]
            ci = n
            g.append(f"[{ci}:v]fps={fps},format=yuv420p,setsar=1[t{ci}]")
            clips.append(f"t{ci}")
            durs.append(end_card_seconds)

        if transition == "none" or len(clips) == 1:
            g.append("".join(f"[{c}]" for c in clips) + f"concat=n={len(clips)}:v=1:a=0[vout]")
            total = sum(durs)
        else:
            offset, prev = 0.0, clips[0]
            for k in range(1, len(clips)):
                offset += durs[k - 1] - tdur
                lab = "vout" if k == len(clips) - 1 else f"x{k}"
                g.append(f"[{prev}][{clips[k]}]xfade=transition={transition}:duration={tdur}:offset={offset:.3f}[{lab}]")
                prev = lab
            total = sum(durs) - tdur * (len(clips) - 1)

        if brand.logo and card:
            # Small logo watermark on the photo section (end card already shows it big).
            li = len(clips)
            args += ["-i", brand.logo]
            lw = int(W * brand.logo_scale)
            m = int(W * 0.04)
            g.append(f"[{li}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.85[lg]")
            photo_end = total - end_card_seconds
            g.append(f"[vout][lg]overlay=W-w-{m}:{m}:enable='lt(t,{photo_end:.2f})'[vfinal]")
            vlabel = "vfinal"
        else:
            vlabel = "vout"

        music = music or brand.music
        amap: list[str] = []
        if music:
            mi = args.count("-i")
            args += ["-stream_loop", "-1", "-i", music]
            g.append(f"[{mi}:a]atrim=0:{total:.3f},aresample=48000,volume={music_volume},"
                     f"afade=t=in:st=0:d=1,afade=t=out:st={max(0, total - 2.5):.3f}:d=2.5[aout]")
            amap = ["-map", "[aout]", *ff.audio_codec_args()]

        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.run([*args, "-filter_complex", ";".join(g), "-map", f"[{vlabel}]", *amap,
                "-t", f"{total:.3f}", *ff.video_codec_args(), "-r", str(fps), str(out)])
    return out


def tour_video(clips: list[str | Path], out: str | Path, platform: Platform, brand: Brand,
               address: str = "", price: str = "", music: str | None = None, music_volume: float = 0.35,
               keep_audio: bool = False, transition: str = "fade", end_card_seconds: float = 4.0) -> Path:
    """Walkthrough clips -> one branded property tour (title overlay, music, end card)."""
    out = Path(out)
    with tempfile.TemporaryDirectory() as td:
        joined = concat(clips, Path(td) / "joined.mp4", platform, transition=transition)
        hook = " | ".join(x for x in [price, address] if x) or None
        opts = RenderOptions(hook=hook, hook_seconds=4.0, music=music or brand.music,
                             music_volume=music_volume if keep_audio else max(music_volume, 0.6), duck=keep_audio,
                             loudnorm=True, fade=0.4)
        body = Path(td) / "body.mp4"
        if not keep_audio:
            silent = Path(td) / "silent.mp4"
            ff.run(["-i", str(joined), "-c:v", "copy", "-af", "volume=0", *ff.audio_codec_args(), str(silent)])
            joined = silent
            opts.loudnorm = False
        render(joined, body, platform, brand, opts)
        if end_card_seconds > 0:
            card = end_card(brand, platform, Path(td) / "end.mp4", end_card_seconds)
            concat([body, card], out, platform, transition="fade", tdur=0.5)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            body.replace(out)
    return out
