"""Brand kit: logo, colors, fonts and contact info reused across every video.

Keep one brand file per project, e.g. brands/viral.json and brands/realestate.json.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Brand:
    name: str = ""
    handle: str = ""                 # @yourhandle, shown as a watermark
    logo: str | None = None          # path to PNG (transparent background works best)
    logo_position: str = "top-right" # top-left | top-right | bottom-left | bottom-right
    logo_scale: float = 0.16         # logo width as a fraction of video width
    font: str | None = None          # path to .ttf/.otf; auto-detected if empty
    caption_font: str = "Inter"      # font *family name* used for burned-in captions
    primary_color: str = "#FFFFFF"
    accent_color: str = "#FFE600"    # highlighted caption word
    background_color: str = "#111111"
    # Real-estate / contact details for end cards
    agent_name: str = ""
    title: str = ""                  # e.g. "REALTOR(R) | Keller Williams"
    phone: str = ""
    email: str = ""
    website: str = ""
    license: str = ""                # e.g. "DRE #01234567". Many states require it on ads.
    music: str | None = None         # default background music track
    extra: dict = field(default_factory=dict)

    @property
    def contact_lines(self) -> list[str]:
        return [x for x in [self.agent_name, self.title, self.phone, self.email, self.website, self.license] if x]


def load(path: str | Path | None) -> Brand:
    if not path:
        return Brand()
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    known = {k: v for k, v in data.items() if k in Brand.__dataclass_fields__}
    brand = Brand(**known)
    # Resolve relative asset paths against the brand file's folder.
    for attr in ("logo", "font", "music"):
        val = getattr(brand, attr)
        if val and not Path(val).is_absolute():
            setattr(brand, attr, str((p.parent / val).resolve()))
    return brand


def save(brand: Brand, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(brand), indent=2), encoding="utf-8")
    return p
