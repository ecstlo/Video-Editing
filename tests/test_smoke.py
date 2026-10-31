"""Smoke tests: pure-Python logic always; real renders when ffmpeg is installed."""
import shutil
import subprocess

import pytest

from vedit import captions, highlights, platforms, transcribe
from vedit.brand import Brand

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _transcript():
    text = ("Here is the biggest mistake people make. Why does nobody talk about this? "
            "You need to get approved first. Honestly it saves you thousands of dollars.")
    t, segs, cur = 0.2, [], []
    for w in text.split():
        cur.append({"start": t, "end": t + 0.3, "word": w})
        t += 0.4
        if w.endswith((".", "?")):
            segs.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["word"] for x in cur), "words": cur})
            cur = []
    return {"source": "x.mp4", "language": "en", "segments": segs}


def test_platform_groups():
    vert = platforms.resolve(["vertical"])
    assert all(p.height > p.width for p in vert)
    with pytest.raises(ValueError):
        platforms.resolve(["myspace"])


def test_window_retimes():
    w = transcribe.window(_transcript(), 2.0, 5.0)
    assert w["segments"]
    assert all(0 <= x["start"] <= 3.0 for s in w["segments"] for x in s["words"])


def test_captions_and_srt():
    ass = captions.build_ass(_transcript(), 1080, 1920, style="viral")
    assert "Dialogue:" in ass and "BIGGEST" in ass
    assert "-->" in transcribe.to_srt(_transcript())


def test_highlights():
    picks = highlights.find(_transcript(), min_len=2, max_len=6, top=2)
    assert picks and all(2 <= p["duration"] <= 6 for p in picks)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_render_clip(tmp_path):
    from vedit import edit, ffmpeg as ff

    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6",
                    "-f", "lavfi", "-i", "sine=d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
                   check=True)
    ass = captions.write_ass(tmp_path / "c.ass", transcribe.window(_transcript(), 1, 5), 1080, 1920)
    out = edit.render(src, tmp_path / "out.mp4", platforms.PLATFORMS["tiktok"], Brand(handle="@test"),
                      edit.RenderOptions(start=1, end=5, ass_path=str(ass), hook="Test hook"))
    info = ff.probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert abs(info.duration - 4) < 0.2
