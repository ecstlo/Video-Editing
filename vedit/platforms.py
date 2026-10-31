"""Export presets for each social platform.

Durations are the limits for a normal upload as of 2025-2026. Platforms change
these often, so they only trigger a warning. Nothing is blocked.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    width: int
    height: int
    max_seconds: int | None
    fps: int = 30
    video_bitrate_cap: str = "12M"
    notes: str = ""

    @property
    def aspect_label(self) -> str:
        from math import gcd

        g = gcd(self.width, self.height)
        return f"{self.width // g}:{self.height // g}"


PLATFORMS: dict[str, Platform] = {
    p.key: p
    for p in [
        Platform("tiktok", "TikTok", 1080, 1920, 600, notes="Keep text out of the bottom ~20% and right edge (UI overlays)."),
        Platform("reels", "Instagram Reels", 1080, 1920, 180, notes="Cover crop shows the center 1080x1440 in the grid."),
        Platform("shorts", "YouTube Shorts", 1080, 1920, 180),
        Platform("facebook", "Facebook Reels", 1080, 1920, 90),
        Platform("x", "X / Twitter", 1080, 1920, 140, notes="Free accounts: 2:20 max."),
        Platform("linkedin", "LinkedIn (vertical)", 1080, 1920, 600),
        Platform("youtube", "YouTube (landscape)", 1920, 1080, None, video_bitrate_cap="16M"),
        Platform("instagram_feed", "Instagram Feed (4:5)", 1080, 1350, 3600),
        Platform("square", "Square (1:1)", 1080, 1080, None),
    ]
}

# Handy groups for "post everywhere" exports.
GROUPS: dict[str, list[str]] = {
    "vertical": ["tiktok", "reels", "shorts", "facebook", "x", "linkedin"],
    "all": list(PLATFORMS.keys()),
    "realestate": ["reels", "tiktok", "shorts", "facebook", "youtube", "instagram_feed"],
}


def resolve(names: list[str]) -> list[Platform]:
    out: list[Platform] = []
    for n in names:
        n = n.strip().lower()
        keys = GROUPS.get(n, [n])
        for k in keys:
            if k not in PLATFORMS:
                raise ValueError(f"Unknown platform '{k}'. Choose from: {', '.join(list(PLATFORMS) + list(GROUPS))}")
            if PLATFORMS[k] not in out:
                out.append(PLATFORMS[k])
    return out
