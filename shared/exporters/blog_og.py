"""
Per-article OG hero card.

Reuses the core gradient background and font loader from og_png.py so every
surface — homepage / compare / template / decision / article — shares the
same visual language. The per-article card differs in three ways:

  1. The accent rail color keys off `tool_focus` so Phronesis posts show the
     orange rail and Synthesis posts show the sky-blue rail (matching the
     split we already use in the app nav).
  2. We surface up to four `hero_keywords` as outline chips along the bottom,
     so the social card acts as a keyword-rich preview.
  3. A small uppercase kicker ("FIELD NOTE · {CATEGORY}") sits above the
     title, framing the piece as editorial content instead of a landing page.
"""

from __future__ import annotations

from PIL import ImageDraw

from .og_png import (
    _gradient_bg,
    _load_font,
    _to_png_bytes,
    _wrap,
    W,
    H,
)


_ACCENTS = {
    "phronesis": (255, 86, 0),
    "synthesis": (56, 189, 248),
    "both":      (255, 86, 0),
}


def _brand_row(d: ImageDraw.ImageDraw, tool_focus: str):
    # Two-dot brand mark: orange (Phronesis) + sky (Synthesis).
    d.ellipse((80, 70, 96, 86), fill=(255, 86, 0))
    d.ellipse((104, 70, 120, 86), fill=(56, 189, 248))
    mono = _load_font(14)
    label = "INTELLCLUSTER  ·  FIELD NOTES"
    if tool_focus == "phronesis":
        label = "INTELLCLUSTER  ·  PHRONESIS NOTES"
    elif tool_focus == "synthesis":
        label = "INTELLCLUSTER  ·  SYNTHESIS NOTES"
    d.text((132, 72), label, font=mono, fill=(139, 148, 158))


def _accent_rail(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]):
    d.rectangle((0, 0, 6, H), fill=accent)


def _kicker(d: ImageDraw.ImageDraw, text: str, accent: tuple[int, int, int]):
    mono = _load_font(13)
    label = text.strip().upper()
    bbox = mono.getbbox(label)
    tw = bbox[2] - bbox[0]
    d.rounded_rectangle(
        (80, 150, 80 + tw + 26, 150 + 30),
        radius=4, outline=accent, width=1,
    )
    d.text((80 + 13, 150 + 9), label, font=mono, fill=accent)


def _keyword_chips(d: ImageDraw.ImageDraw, keywords: list[str], accent: tuple[int, int, int]):
    if not keywords:
        return
    mono = _load_font(14)
    x = 80
    y = H - 110
    for kw in keywords[:4]:
        label = kw.strip().upper()[:28]
        if not label:
            continue
        bbox = mono.getbbox(label)
        tw = bbox[2] - bbox[0]
        pill_w = tw + 28
        if x + pill_w > W - 80:
            break
        d.rounded_rectangle(
            (x, y, x + pill_w, y + 32),
            radius=6, outline=accent, width=1,
        )
        d.text((x + 14, y + 9), label, font=mono, fill=accent)
        x += pill_w + 12


def blog_hero_og_png(
    title: str,
    tool_focus: str = "both",
    hero_keywords: list[str] | None = None,
    hero_tag: str = "FIELD NOTE",
) -> bytes:
    accent = _ACCENTS.get(tool_focus, _ACCENTS["both"])

    img = _gradient_bg().convert("RGB")
    d = ImageDraw.Draw(img)

    _accent_rail(d, accent)
    _brand_row(d, tool_focus)
    _kicker(d, f"FIELD NOTE  ·  {hero_tag}", accent)

    # Title — large serif, up to four lines.
    serif = _load_font(56, serif=True)
    lines = _wrap(title, serif, W - 160)[:4]
    y = 220
    for line in lines:
        d.text((80, y), line, font=serif, fill=(230, 237, 243))
        y += 66

    _keyword_chips(d, hero_keywords or [], accent)

    mono = _load_font(14)
    d.text((80, H - 40), "INTELLCLUSTER.COM/BLOG", font=mono, fill=(72, 79, 88))
    return _to_png_bytes(img)
