"""Thin helpers around the ffmpeg / ffprobe command-line tools."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VERBOSE = os.environ.get("VEDIT_VERBOSE") == "1"


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(
                f"'{tool}' was not found on PATH. Install FFmpeg first "
                "(macOS: `brew install ffmpeg`, Windows: `winget install ffmpeg`, "
                "Ubuntu: `sudo apt install ffmpeg`)."
            )


def run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run ffmpeg with sane defaults. `args` excludes the leading 'ffmpeg'."""
    require_ffmpeg()
    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "info" if VERBOSE else "error", *args]
    if VERBOSE:
        print("+", " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed:\n  {' '.join(cmd)}\n{proc.stderr[-4000:]}")
    return proc


def run_stderr(args: list[str]) -> str:
    """Run ffmpeg and return stderr (used by analysis filters like silencedetect)."""
    require_ffmpeg()
    cmd = ["ffmpeg", "-hide_banner", "-nostats", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed:\n  {' '.join(cmd)}\n{proc.stderr[-4000:]}")
    return proc.stderr


@dataclass
class MediaInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0


def probe(path: str | Path) -> MediaInfo:
    require_ffmpeg()
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = 0.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        num, den = v["avg_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    width, height = (int(v.get("width", 0)), int(v.get("height", 0))) if v else (0, 0)
    # Respect phone rotation metadata so portrait phone footage is treated as portrait.
    if v:
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int(v.get("tags", {}).get("rotate", rot))
        if abs(rot) % 180 == 90:
            width, height = height, width
    return MediaInfo(
        path=Path(path),
        duration=float(data.get("format", {}).get("duration", 0.0)),
        width=width,
        height=height,
        fps=fps,
        has_audio=a is not None,
        has_video=v is not None,
    )


# Encoding settings that every social platform accepts.
def video_codec_args(crf: int = 20, preset: str = "medium") -> list[str]:
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def audio_codec_args(bitrate: str = "192k") -> list[str]:
    return ["-c:a", "aac", "-b:a", bitrate, "-ar", "48000"]


def find_font(bold: bool = True) -> str:
    """Locate a usable .ttf/.otf for drawtext."""
    env = os.environ.get("VEDIT_FONT")
    if env and Path(env).exists():
        return env
    if shutil.which("fc-match"):
        pattern = "sans:bold" if bold else "sans"
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout.strip()
        if out and Path(out).exists():
            return out
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FFmpegError("No font found. Set VEDIT_FONT=/path/to/font.ttf or add 'font' to brand.json.")


def escape_filter_path(p: str | Path) -> str:
    """Escape a file path for use inside an ffmpeg filtergraph option."""
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", "\u2019")
        .replace(",", r"\,")
    )
