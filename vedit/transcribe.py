"""Speech-to-text with word timestamps (faster-whisper), plus SRT export.

Transcript JSON format (used by captions + highlights):
{
  "source": "video.mp4",
  "language": "en",
  "segments": [
    {"start": 0.0, "end": 3.2, "text": "Hello there",
     "words": [{"start": 0.0, "end": 0.4, "word": "Hello"}, ...]}
  ]
}
"""
from __future__ import annotations

import json
from pathlib import Path


def transcribe(media: str | Path, model_size: str = "small", language: str | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Transcription needs faster-whisper. Install it with:  pip install -e '.[transcribe]'"
        ) from e

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, info = model.transcribe(
        str(media), language=language, word_timestamps=True, vad_filter=True
    )
    out_segments = []
    for seg in segments:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
            for w in (seg.words or [])
            if w.word.strip()
        ]
        out_segments.append(
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words}
        )
    return {"source": str(media), "language": info.language, "segments": out_segments}


def save(transcript: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def all_words(transcript: dict) -> list[dict]:
    words: list[dict] = []
    for seg in transcript.get("segments", []):
        if seg.get("words"):
            words.extend(seg["words"])
        else:  # fall back to spreading segment text evenly
            toks = seg["text"].split()
            if not toks:
                continue
            step = (seg["end"] - seg["start"]) / len(toks)
            for i, t in enumerate(toks):
                words.append({"start": seg["start"] + i * step, "end": seg["start"] + (i + 1) * step, "word": t})
    return words


def window(transcript: dict, start: float, end: float) -> dict:
    """Return a transcript containing only [start, end], re-timed so `start` becomes 0."""
    segs = []
    for seg in transcript.get("segments", []):
        if seg["end"] <= start or seg["start"] >= end:
            continue
        words = [
            {"start": max(0.0, w["start"] - start), "end": min(end, w["end"]) - start, "word": w["word"]}
            for w in seg.get("words", [])
            if w["end"] > start and w["start"] < end
        ]
        segs.append(
            {
                "start": max(0.0, seg["start"] - start),
                "end": min(end, seg["end"]) - start,
                "text": " ".join(w["word"] for w in words) if words else seg["text"],
                "words": words,
            }
        )
    return {**transcript, "segments": segs}


def _ts(t: float, sep: str = ",") -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(transcript: dict, max_words: int = 8) -> str:
    """Plain SRT (for uploading as a captions file on YouTube/LinkedIn/Facebook)."""
    words = all_words(transcript)
    lines, idx = [], 1
    for i in range(0, len(words), max_words):
        chunk = words[i : i + max_words]
        lines.append(f"{idx}\n{_ts(chunk[0]['start'])} --> {_ts(chunk[-1]['end'])}\n{' '.join(w['word'] for w in chunk)}\n")
        idx += 1
    return "\n".join(lines)


def to_text(transcript: dict) -> str:
    """Readable, timestamped transcript (handy for asking Claude to pick clips)."""
    return "\n".join(f"[{_ts(s['start'], '.')[:-4]}-{_ts(s['end'], '.')[:-4]}] {s['text']}" for s in transcript["segments"])
