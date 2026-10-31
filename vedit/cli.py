"""vedit command-line interface.  Run `vedit -h` or `vedit <command> -h`."""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
import tempfile
from pathlib import Path

from . import brand as brand_mod
from . import captions, edit, highlights, platforms, realestate, transcribe
from . import ffmpeg as ff


def _out_dir(args) -> Path:
    d = Path(args.out_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcript_path(media: Path) -> Path:
    return media.with_suffix(".transcript.json")


def _get_transcript(media: Path, explicit: str | None, model: str, auto: bool = True) -> dict | None:
    p = Path(explicit) if explicit else _transcript_path(media)
    if p.exists():
        return transcribe.load(p)
    if not auto:
        return None
    try:
        print(f"Transcribing {media.name} (first run downloads the speech model)...", file=sys.stderr)
        t = transcribe.transcribe(media, model_size=model)
    except RuntimeError as e:
        print(f"! {e}\n  Continuing without captions.", file=sys.stderr)
        return None
    transcribe.save(t, p)
    p.with_suffix("").with_suffix(".srt").write_text(transcribe.to_srt(t), encoding="utf-8")
    p.with_suffix("").with_suffix(".txt").write_text(transcribe.to_text(t), encoding="utf-8")
    return t


def _parse_time(s: str | None) -> float | None:
    """Accepts 75, 75.5, 1:15, 01:01:15.5"""
    if s is None:
        return None
    parts = [float(x) for x in str(s).split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def render_for_platforms(src: Path, name: str, args, start: float | None, end: float | None,
                         transcript: dict | None, hook: str | None) -> list[Path]:
    brand = brand_mod.load(args.brand)
    targets = platforms.resolve(args.platforms.split(","))
    out_dir = _out_dir(args)
    rendered: dict[tuple[int, int], Path] = {}
    outputs: list[Path] = []
    info = ff.probe(src)
    s = start or 0.0
    e = end if end is not None else info.duration
    length = (e - s) / args.speed

    with tempfile.TemporaryDirectory() as td:
        for p in targets:
            dest = out_dir / f"{name}_{p.key}.mp4"
            key = (p.width, p.height)
            if key in rendered:  # same size as one we already made: reuse it
                shutil.copyfile(rendered[key], dest)
            else:
                ass = None
                if transcript and args.captions != "none":
                    win = transcribe.window(transcript, s, e)
                    if args.speed != 1.0:
                        for seg in win["segments"]:
                            seg["start"] /= args.speed
                            seg["end"] /= args.speed
                            for w in seg["words"]:
                                w["start"] /= args.speed
                                w["end"] /= args.speed
                    ass = Path(td) / f"{p.width}x{p.height}.ass"
                    captions.write_ass(ass, win, p.width, p.height, style=args.captions, font=brand.caption_font,
                                       text_color=brand.primary_color, highlight_color=brand.accent_color,
                                       position=args.caption_pos)
                opts = edit.RenderOptions(
                    start=start, end=end, mode=args.mode, focus=args.focus, ass_path=str(ass) if ass else None,
                    hook=hook, hook_seconds=args.hook_seconds, watermark=not args.no_brand,
                    music=args.music, music_volume=args.music_volume, speed=args.speed, fade=args.fade,
                )
                edit.render(src, dest, p, brand, opts)
                rendered[key] = dest
            warn = f"  (! over {p.name}'s {p.max_seconds}s limit)" if p.max_seconds and length > p.max_seconds else ""
            print(f"  -> {dest}{warn}")
            outputs.append(dest)
    return outputs


# ------------------------------------------------------------------ commands

def cmd_info(args):
    i = ff.probe(args.file)
    print(json.dumps({"file": str(i.path), "duration": round(i.duration, 2), "width": i.width, "height": i.height,
                      "fps": round(i.fps, 2), "audio": i.has_audio, "aspect": round(i.aspect, 3)}, indent=2))


def cmd_transcribe(args):
    media = Path(args.file)
    t = transcribe.transcribe(media, model_size=args.model, language=args.language)
    base = media.with_suffix("")
    transcribe.save(t, base.with_suffix(".transcript.json"))
    base.with_suffix(".srt").write_text(transcribe.to_srt(t), encoding="utf-8")
    base.with_suffix(".transcript.txt").write_text(transcribe.to_text(t), encoding="utf-8")
    print(f"Wrote {base}.transcript.json, {base}.transcript.txt, {base}.srt")


def cmd_highlights(args):
    t = transcribe.load(args.transcript)
    picks = highlights.find(t, args.min, args.max, args.top)
    print(json.dumps(picks, indent=2, ensure_ascii=False))
    if args.save:
        Path(args.save).write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_clip(args):
    src = Path(args.file)
    start, end = _parse_time(args.start), _parse_time(args.end)
    transcript = None
    if args.captions != "none":
        transcript = _get_transcript(src, args.transcript, args.model)
    name = args.name or f"{src.stem}_{int(start or 0)}s"
    print(f"Rendering {name}:")
    render_for_platforms(src, name, args, start, end, transcript, args.hook)


def cmd_auto(args):
    src = Path(args.file)
    transcript = _get_transcript(src, args.transcript, args.model)
    if not transcript:
        sys.exit("auto needs a transcript. Install faster-whisper: pip install -e '.[transcribe]'")
    picks = highlights.find(transcript, args.min, args.max, args.top)
    if not picks:
        sys.exit("No clips found. Try a smaller --min or a larger --max.")
    manifest = []
    for n, c in enumerate(picks, 1):
        name = f"{src.stem}_clip{n}"
        print(f"[{n}/{len(picks)}] {c['start']}s-{c['end']}s  score={c['score']}  \"{c['hook'][:70]}\"")
        outs = render_for_platforms(src, name, args, c["start"], c["end"], transcript,
                                    c["hook"] if args.auto_hook else None)
        manifest.append({**c, "files": [str(o) for o in outs]})
    mf = _out_dir(args) / f"{src.stem}_clips.json"
    mf.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest: {mf}")


def cmd_silence(args):
    out, before, after = edit.remove_silence(args.file, args.output, args.threshold, args.min_silence, args.pad)
    print(f"{out}: {before:.1f}s -> {after:.1f}s (removed {before - after:.1f}s)")


def cmd_concat(args):
    p = platforms.resolve([args.platform])[0]
    print(edit.concat(args.files, args.output, p, transition=args.transition, tdur=args.duration, mode=args.mode))


def cmd_thumb(args):
    print(edit.thumbnail(args.file, args.output, _parse_time(args.at)))


def cmd_sheet(args):
    print(edit.contact_sheet(args.file, args.output, args.every, args.cols))


def cmd_stabilize(args):
    print(edit.stabilize(args.file, args.output, args.smoothing))


def cmd_grade(args):
    print(edit.color_grade(args.file, args.output, args.look))


def _collect_photos(items: list[str]) -> list[Path]:
    out: list[Path] = []
    for it in items:
        p = Path(it)
        if p.is_dir():
            out += sorted(x for x in p.iterdir() if x.suffix.lower() in realestate.IMAGE_EXTS)
        else:
            out += sorted(Path(x) for x in glob.glob(it)) or [p]
    return out


def cmd_listing(args):
    photos = _collect_photos(args.photos)
    brand = brand_mod.load(args.brand)
    labels = [x.strip() for x in args.labels.split(",")] if args.labels else None
    out_dir = _out_dir(args)
    for p in platforms.resolve(args.platforms.split(",")):
        dest = out_dir / f"{args.name}_{p.key}.mp4"
        realestate.listing_video(photos, dest, p, brand, address=args.address, price=args.price,
                                 details=args.details, labels=labels, seconds_per_photo=args.seconds,
                                 transition=args.transition, music=args.music, status=args.status,
                                 end_card_seconds=args.end_card)
        print(f"  -> {dest}")


def cmd_tour(args):
    brand = brand_mod.load(args.brand)
    out_dir = _out_dir(args)
    for p in platforms.resolve(args.platforms.split(",")):
        dest = out_dir / f"{args.name}_{p.key}.mp4"
        realestate.tour_video(args.clips, dest, p, brand, address=args.address, price=args.price,
                              music=args.music, keep_audio=args.keep_audio, transition=args.transition,
                              end_card_seconds=args.end_card)
        print(f"  -> {dest}")


def cmd_endcard(args):
    brand = brand_mod.load(args.brand)
    p = platforms.resolve([args.platform])[0]
    print(realestate.end_card(brand, p, args.output, args.seconds, args.headline))


def cmd_brand_init(args):
    b = brand_mod.Brand(name="My Brand", handle="@yourhandle")
    if args.realestate:
        b = brand_mod.Brand(name="Jane Doe Realty", handle="@janedoerealty", logo_position="top-right",
                            agent_name="Jane Doe", title="REALTOR | Your Brokerage", phone="(555) 123-4567",
                            email="jane@example.com", website="janedoerealty.com", license="License #00000000",
                            accent_color="#C9A227", background_color="#0F1B2D")
    print(brand_mod.save(b, args.path))


def cmd_platforms(args):
    for p in platforms.PLATFORMS.values():
        lim = f"{p.max_seconds}s" if p.max_seconds else "-"
        print(f"{p.key:15} {p.name:24} {p.width}x{p.height} ({p.aspect_label:>5})  max {lim:>6}  {p.notes}")
    print("\nGroups: " + ", ".join(f"{k}={'+'.join(v)}" for k, v in platforms.GROUPS.items()))


# ------------------------------------------------------------------ parser

def _add_render_flags(sp):
    sp.add_argument("--platforms", default="vertical", help="comma list or group: vertical, all, realestate, tiktok,reels,...")
    sp.add_argument("--captions", default="viral", choices=["viral", "clean", "minimal", "none"])
    sp.add_argument("--caption-pos", type=float, default=None, help="viral caption height 0-1 (default 0.68)")
    sp.add_argument("--mode", default="auto", choices=["auto", "crop", "blur", "pad"], help="how to fit into the frame")
    sp.add_argument("--focus", type=float, default=0.5, help="crop mode: 0=keep left, 0.5=center, 1=keep right")
    sp.add_argument("--brand", help="brand JSON (logo, colors, handle)")
    sp.add_argument("--no-brand", action="store_true", help="skip logo/handle watermark")
    sp.add_argument("--music", help="background music file")
    sp.add_argument("--music-volume", type=float, default=0.12)
    sp.add_argument("--speed", type=float, default=1.0, help="e.g. 1.1 for slightly faster pacing")
    sp.add_argument("--fade", type=float, default=0.0)
    sp.add_argument("--hook-seconds", type=float, default=None, help="show hook text only for N seconds")
    sp.add_argument("--transcript", help="existing transcript JSON (default: <video>.transcript.json)")
    sp.add_argument("--model", default="small", help="whisper model: tiny, base, small, medium, large-v3")
    sp.add_argument("--out-dir", default="output")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vedit", description="Video editing toolkit for social clips and real estate.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("info", help="show duration, size, fps")
    sp.add_argument("file"); sp.set_defaults(fn=cmd_info)

    sp = sub.add_parser("platforms", help="list export presets"); sp.set_defaults(fn=cmd_platforms)

    sp = sub.add_parser("transcribe", help="speech-to-text with word timings (+ .srt and .txt)")
    sp.add_argument("file"); sp.add_argument("--model", default="small"); sp.add_argument("--language")
    sp.set_defaults(fn=cmd_transcribe)

    sp = sub.add_parser("highlights", help="suggest clip-worthy moments from a transcript")
    sp.add_argument("transcript"); sp.add_argument("--min", type=float, default=15); sp.add_argument("--max", type=float, default=60)
    sp.add_argument("--top", type=int, default=5); sp.add_argument("--save")
    sp.set_defaults(fn=cmd_highlights)

    sp = sub.add_parser("clip", help="cut a moment and export it for each platform with captions")
    sp.add_argument("file"); sp.add_argument("--start"); sp.add_argument("--end")
    sp.add_argument("--hook", help="headline text at the top, e.g. 'He did NOT expect this'")
    sp.add_argument("--name"); _add_render_flags(sp); sp.set_defaults(fn=cmd_clip)

    sp = sub.add_parser("auto", help="transcribe, find the best moments and export them all")
    sp.add_argument("file"); sp.add_argument("--top", type=int, default=3)
    sp.add_argument("--min", type=float, default=15); sp.add_argument("--max", type=float, default=60)
    sp.add_argument("--auto-hook", action="store_true", help="use each clip's first line as hook text")
    _add_render_flags(sp); sp.set_defaults(fn=cmd_auto)

    sp = sub.add_parser("silence", help="remove dead air / pauses")
    sp.add_argument("file"); sp.add_argument("-o", "--output", required=True)
    sp.add_argument("--threshold", type=float, default=-35, help="dB; lower = only cut quieter parts")
    sp.add_argument("--min-silence", type=float, default=0.5); sp.add_argument("--pad", type=float, default=0.12)
    sp.set_defaults(fn=cmd_silence)

    sp = sub.add_parser("concat", help="join clips with transitions")
    sp.add_argument("files", nargs="+"); sp.add_argument("-o", "--output", required=True)
    sp.add_argument("--platform", default="tiktok"); sp.add_argument("--transition", default="fade")
    sp.add_argument("--duration", type=float, default=0.5); sp.add_argument("--mode", default="auto")
    sp.set_defaults(fn=cmd_concat)

    sp = sub.add_parser("thumb", help="export a single frame")
    sp.add_argument("file"); sp.add_argument("-o", "--output", required=True); sp.add_argument("--at")
    sp.set_defaults(fn=cmd_thumb)

    sp = sub.add_parser("sheet", help="grid of frames, to review a video at a glance")
    sp.add_argument("file"); sp.add_argument("-o", "--output", required=True)
    sp.add_argument("--every", type=float, default=5.0); sp.add_argument("--cols", type=int, default=5)
    sp.set_defaults(fn=cmd_sheet)

    sp = sub.add_parser("stabilize", help="smooth out shaky handheld footage")
    sp.add_argument("file"); sp.add_argument("-o", "--output", required=True); sp.add_argument("--smoothing", type=int, default=15)
    sp.set_defaults(fn=cmd_stabilize)

    sp = sub.add_parser("grade", help="quick color looks: bright, punchy, warm, cinematic")
    sp.add_argument("file"); sp.add_argument("-o", "--output", required=True); sp.add_argument("--look", default="bright")
    sp.set_defaults(fn=cmd_grade)

    sp = sub.add_parser("listing", help="real estate: photos -> listing video")
    sp.add_argument("photos", nargs="+", help="folder(s), files or globs (sorted by name)")
    sp.add_argument("--address", default=""); sp.add_argument("--price", default=""); sp.add_argument("--details", default="")
    sp.add_argument("--status", default="", help="banner, e.g. 'Just Listed', 'Open House Sat 1-4'")
    sp.add_argument("--labels", help="comma list of room labels for photos 2, 3, 4...")
    sp.add_argument("--seconds", type=float, default=3.0); sp.add_argument("--transition", default="fade")
    sp.add_argument("--music"); sp.add_argument("--brand"); sp.add_argument("--end-card", type=float, default=4.0)
    sp.add_argument("--platforms", default="reels"); sp.add_argument("--name", default="listing")
    sp.add_argument("--out-dir", default="output"); sp.set_defaults(fn=cmd_listing)

    sp = sub.add_parser("tour", help="real estate: walkthrough clips -> branded property tour")
    sp.add_argument("clips", nargs="+"); sp.add_argument("--address", default=""); sp.add_argument("--price", default="")
    sp.add_argument("--music"); sp.add_argument("--keep-audio", action="store_true", help="keep your narration")
    sp.add_argument("--transition", default="fade"); sp.add_argument("--brand"); sp.add_argument("--end-card", type=float, default=4.0)
    sp.add_argument("--platforms", default="reels"); sp.add_argument("--name", default="tour")
    sp.add_argument("--out-dir", default="output"); sp.set_defaults(fn=cmd_tour)

    sp = sub.add_parser("endcard", help="render a branded contact card")
    sp.add_argument("--brand", required=True); sp.add_argument("-o", "--output", required=True)
    sp.add_argument("--platform", default="reels"); sp.add_argument("--seconds", type=float, default=4.0)
    sp.add_argument("--headline", default="Schedule a private showing"); sp.set_defaults(fn=cmd_endcard)

    sp = sub.add_parser("brand-init", help="create a brand kit JSON to fill in")
    sp.add_argument("path"); sp.add_argument("--realestate", action="store_true"); sp.set_defaults(fn=cmd_brand_init)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except (ff.FFmpegError, ValueError, RuntimeError, FileNotFoundError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
