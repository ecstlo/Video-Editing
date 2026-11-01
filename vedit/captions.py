"""Styled, animated captions rendered with libass (.ass subtitle files).

Styles:
  viral   - big bold centered words, 1-3 at a time, current word highlighted (TikTok/Reels look)
  clean   - two-line lower-third subtitles, professional (real estate, interviews)
  minimal - small white text with a soft shadow at the bottom
"""
from __future__ import annotations

from pathlib import Path

from .transcribe import all_words


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color(hex_rgb: str, alpha: str = "00") -> str:
    """'#RRGGBB' -> ASS '&HAABBGGRR'."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


PROFANITY = ("fuck", "shit", "bitch", "cunt", "dick", "pussy", "motherfuck", "asshole", "nigga", "nigger")


def censor_word(word: str) -> str:
    """'fucking' -> 'f***ing'. Keeps the first letter so the caption still reads naturally."""
    import re

    def repl(m: re.Match) -> str:
        w = m.group(0)
        return w[0] + "*" * (len(w) - 1)

    pattern = "|".join(sorted(PROFANITY, key=len, reverse=True))
    out = re.sub(rf"(?i)({pattern})", repl, word)
    return out


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


STYLES = {
    # name: (font_size_ratio_of_height, bold, outline, shadow, alignment, margin_v_ratio, uppercase, words_per_chunk)
    "viral": dict(size=0.062, bold=1, outline=5, shadow=0, align=5, margin_v=0.0, upper=True, chunk=3),
    "clean": dict(size=0.042, bold=1, outline=2, shadow=1, align=2, margin_v=0.08, upper=False, chunk=7),
    "minimal": dict(size=0.034, bold=0, outline=1, shadow=2, align=2, margin_v=0.06, upper=False, chunk=8),
}


def build_ass(
    transcript: dict,
    width: int,
    height: int,
    style: str = "viral",
    font: str = "Inter",
    text_color: str = "#FFFFFF",
    highlight_color: str = "#FFE600",
    outline_color: str = "#000000",
    position: float | None = None,
    censor: bool = False,
    words_per_chunk: int | None = None,
    size_scale: float = 1.0,
) -> str:
    """Create an .ass subtitle document. `position` (0-1) overrides vertical placement
    for the viral style (0.5 = middle, 0.7 = lower third)."""
    if style not in STYLES:
        raise ValueError(f"Unknown caption style '{style}'. Choose: {', '.join(STYLES)}")
    st = STYLES[style]
    size = int(height * st["size"]) if width < height else int(height * st["size"] * 1.25)
    size = int(size * size_scale)
    margin_v = int(height * st["margin_v"])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},{size},{_ass_color(text_color)},{_ass_color(highlight_color)},{_ass_color(outline_color)},&H80000000,{-1 if st['bold'] else 0},0,0,0,100,100,0,0,1,{st['outline']},{st['shadow']},{st['align']},{int(width*0.08)},{int(width*0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    words = all_words(transcript)
    if censor:
        words = [{**w, "word": censor_word(w["word"])} for w in words]
    events: list[str] = []
    n = words_per_chunk or st["chunk"]
    pos_tag = ""
    if style == "viral":
        y = int(height * (position if position is not None else 0.68))
        pos_tag = f"\\an5\\pos({width // 2},{y})"

    for i in range(0, len(words), n):
        chunk = words[i : i + n]
        start = chunk[0]["start"]
        # Hold the caption until the next chunk starts (avoids flicker), max +0.6s.
        nxt = words[i + n]["start"] if i + n < len(words) else chunk[-1]["end"] + 0.4
        end = min(max(chunk[-1]["end"], start + 0.25), nxt if nxt - chunk[-1]["end"] < 0.6 else chunk[-1]["end"] + 0.3)
        toks = [_escape(w["word"].upper() if st["upper"] else w["word"]) for w in chunk]

        if style == "viral":
            # One event per word so the active word lights up, with a little pop-in.
            for j, w in enumerate(chunk):
                w_start = w["start"] if j else start
                w_end = chunk[j + 1]["start"] if j + 1 < len(chunk) else end
                if w_end <= w_start:
                    continue
                parts = []
                for k, t in enumerate(toks):
                    if k == j:
                        parts.append(f"{{\\c{_ass_color(highlight_color)}\\fscx110\\fscy110}}{t}{{\\c{_ass_color(text_color)}\\fscx100\\fscy100}}")
                    else:
                        parts.append(t)
                pop = "\\fscx85\\fscy85\\t(0,80,\\fscx100\\fscy100)" if j == 0 else ""
                events.append(
                    f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Main,,0,0,0,,{{{pos_tag}{pop}}}{' '.join(parts)}"
                )
        else:
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{' '.join(toks)}")
    return header + "\n".join(events) + "\n"


def write_ass(path: str | Path, *args, **kwargs) -> Path:
    path = Path(path)
    path.write_text(build_ass(*args, **kwargs), encoding="utf-8")
    return path
