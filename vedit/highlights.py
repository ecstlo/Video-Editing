"""Find clip-worthy moments in a transcript.

This is a fast keyword-and-pacing heuristic that gives a first shortlist. For better
picks, ask Claude in Claude Code to read `<name>.transcript.txt` and choose clips.
It understands context, humor and story arcs, which a heuristic can't.
"""
from __future__ import annotations

import re

HOOK_WORDS = {
    "secret", "never", "always", "mistake", "mistakes", "biggest", "worst", "best", "crazy", "insane",
    "truth", "nobody", "everyone", "stop", "why", "how", "what", "wrong", "actually", "honestly",
    "million", "thousand", "money", "free", "hack", "trick", "warning", "shocking", "literally",
    "first", "only", "real", "story", "imagine", "listen", "watch", "look", "you", "your",
}
FILLERS = {"um", "uh", "like", "so", "basically", "you know", "kind of", "sort of"}


def _seg_score(text: str) -> float:
    t = text.lower()
    words = re.findall(r"[a-z']+", t)
    if not words:
        return 0.0
    score = sum(1.0 for w in words if w in HOOK_WORDS) / len(words) * 10
    score += 1.5 if "?" in text else 0
    score += 1.0 if "!" in text else 0
    score += 1.0 if re.search(r"\d", text) else 0
    score -= sum(1 for w in words if w in FILLERS) / len(words) * 5
    return score


def find(transcript: dict, min_len: float = 15, max_len: float = 60, top: int = 5) -> list[dict]:
    segs = [s for s in transcript.get("segments", []) if s["text"].strip()]
    candidates = []
    for i in range(len(segs)):
        for j in range(i, len(segs)):
            dur = segs[j]["end"] - segs[i]["start"]
            if dur > max_len:
                break
            if dur < min_len:
                continue
            window = segs[i : j + 1]
            text = " ".join(s["text"] for s in window)
            n_words = len(text.split())
            pace = n_words / dur  # words per second; ~2.5-3.5 is energetic speech
            hook = _seg_score(window[0]["text"]) * 2.0  # the first line matters most
            body = sum(_seg_score(s["text"]) for s in window) / len(window)
            ends_clean = 1.0 if re.search(r"[.!?]$", window[-1]["text"].strip()) else -1.0
            gaps = sum(max(0, window[k + 1]["start"] - window[k]["end"]) for k in range(len(window) - 1))
            score = hook + body + min(pace, 3.5) + ends_clean - gaps * 0.5
            candidates.append({
                "start": round(window[0]["start"], 2),
                "end": round(window[-1]["end"], 2),
                "duration": round(dur, 1),
                "score": round(score, 2),
                "hook": window[0]["text"].strip(),
                "text": text.strip(),
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    picked: list[dict] = []
    for c in candidates:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= top:
            break
    return sorted(picked, key=lambda c: c["start"])
