"""
PNG OG image rendering via Pillow (pure Python, no cairo dep).

We generate matching raster versions of the SVG OG images so Facebook,
Telegram, and older clients that don't render SVG link previews get the
same visual. Same dimensions (1200×630), same brand language.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


W, H = 1200, 630


def _gradient_bg() -> Image.Image:
    """#020917 → #161b22 diagonal gradient with a warm orange glow at top-right."""
    base = Image.new("RGB", (W, H), (2, 9, 23))
    # Diagonal gradient
    grad = Image.new("L", (W, H))
    gd = grad.load()
    for y in range(H):
        for x in range(W):
            t = (x / W + y / H) / 2
            gd[x, y] = int(22 * t)
    overlay = Image.new("RGB", (W, H), (22, 27, 34))
    base = Image.composite(overlay, base, grad)

    # Radial orange glow at upper-right
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = glow.load()
    cx, cy = int(W * 0.85), int(H * 0.15)
    max_r = int(W * 0.7)
    for y in range(H):
        for x in range(W):
            dx = x - cx; dy = y - cy
            d = (dx * dx + dy * dy) ** 0.5
            if d >= max_r:
                continue
            alpha = int(56 * (1 - d / max_r))  # max alpha 56/255 ≈ 0.22
            if alpha <= 0:
                continue
            gd[x, y] = (255, 86, 0, alpha)
    return Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")


def _load_font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont:
    """Best-effort font loading. Falls back gracefully on each platform."""
    candidates_serif = [
        "Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ]
    candidates_mono = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ]
    candidates_sans = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "Arial.ttf",
    ]
    pool = candidates_serif if serif else candidates_sans
    for path in pool:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_brand_row(d: ImageDraw.ImageDraw, label: str):
    # Orange + cyan dots
    d.ellipse((80, 70, 96, 86), fill=(255, 86, 0))
    d.ellipse((104, 70, 120, 86), fill=(77, 208, 200))
    mono = _load_font(14)
    d.text((132, 72), label.upper(), font=mono, fill=(139, 148, 158))


def _draw_accent_rail(d: ImageDraw.ImageDraw):
    # 6px orange rail down the left edge
    d.rectangle((0, 0, 6, H), fill=(255, 86, 0))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip() if cur else w
        bbox = font.getbbox(trial)
        if bbox[2] - bbox[0] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def homepage_og_png() -> bytes:
    img = _gradient_bg().convert("RGB")
    d = ImageDraw.Draw(img)
    _draw_accent_rail(d)
    _draw_brand_row(d, "IntellCluster")

    serif = _load_font(84, serif=True)
    d.text((80, 180), "Multi-model AI", font=serif, fill=(230, 237, 243))
    d.text((80, 275), "intelligence.", font=serif, fill=(230, 237, 243))

    sans = _load_font(26)
    d.text((80, 440), "Phronesis ranks your options.", font=sans, fill=(139, 148, 158))
    d.text((80, 480), "Synthesis runs deep multi-model research.", font=sans, fill=(139, 148, 158))

    mono = _load_font(14)
    d.text((80, H - 40), "INTELLCLUSTER.COM  ·  TWO TOOLS, ONE ECOSYSTEM",
           font=mono, fill=(72, 79, 88))
    return _to_png_bytes(img)


def compare_og_png(title: str, options: list[str], category: str = "") -> bytes:
    img = _gradient_bg().convert("RGB")
    d = ImageDraw.Draw(img)
    _draw_accent_rail(d)
    label = f"IntellCluster  ·  Compare{('  ·  ' + category.upper()) if category else ''}"
    _draw_brand_row(d, label)

    # Title — up to 3 lines
    serif = _load_font(58, serif=True)
    lines = _wrap(title, serif, W - 160)[:3]
    y = 170
    for line in lines:
        d.text((80, y), line, font=serif, fill=(230, 237, 243))
        y += 72

    # Option pills
    pill_y = 480
    pill_x = 80
    sans = _load_font(22)
    for opt in options[:4]:
        label_opt = opt[:34]
        bbox = sans.getbbox(label_opt)
        tw = bbox[2] - bbox[0]
        pill_w = max(140, tw + 48)
        d.rounded_rectangle(
            (pill_x, pill_y, pill_x + pill_w, pill_y + 54),
            radius=14, fill=(28, 33, 41), outline=(48, 54, 61), width=1,
        )
        d.text((pill_x + 24, pill_y + 14), label_opt, font=sans, fill=(230, 237, 243))
        pill_x += pill_w + 14
        if pill_x > W - 140:
            break

    mono = _load_font(14)
    d.text((80, H - 40), "INTELLCLUSTER.COM  ·  MULTI-MODEL AI INTELLIGENCE",
           font=mono, fill=(72, 79, 88))
    return _to_png_bytes(img)


def decision_og_png(question: str, winner: str, confidence: int | None = None, agree: bool = False) -> bytes:
    """Per-decision OG card — great for social sharing of a Phronesis result."""
    img = _gradient_bg().convert("RGB")
    d = ImageDraw.Draw(img)
    _draw_accent_rail(d)
    _draw_brand_row(d, "IntellCluster  ·  Phronesis Verdict")

    # Question (muted, small, wrapped)
    sans = _load_font(20)
    mono = _load_font(14)

    q_lines = _wrap(question, sans, W - 160)[:2]
    y = 150
    for line in q_lines:
        d.text((80, y), line, font=sans, fill=(139, 148, 158))
        y += 28

    # Winner (huge serif)
    serif = _load_font(76, serif=True)
    w_lines = _wrap(winner, serif, W - 160)[:2]
    y = 250
    for line in w_lines:
        d.text((80, y), line, font=serif, fill=(255, 86, 0))
        y += 88

    # Confidence chip + agreement chip
    chip_y = 500
    chip_x = 80
    if confidence is not None:
        chip_text = f"{confidence}% CONFIDENCE"
        bbox = mono.getbbox(chip_text); tw = bbox[2] - bbox[0]
        d.rounded_rectangle(
            (chip_x, chip_y, chip_x + tw + 28, chip_y + 32),
            radius=6, fill=(255, 86, 0, 30), outline=(255, 86, 0), width=1,
        )
        d.text((chip_x + 14, chip_y + 9), chip_text, font=mono, fill=(255, 86, 0))
        chip_x += tw + 40

    agree_text = "UNANIMOUS  ·  3 ANALYSTS" if agree else "SPLIT  ·  3 ANALYSTS"
    bbox = mono.getbbox(agree_text); tw = bbox[2] - bbox[0]
    color = (63, 185, 80) if agree else (210, 153, 34)
    d.rounded_rectangle(
        (chip_x, chip_y, chip_x + tw + 28, chip_y + 32),
        radius=6, outline=color, width=1,
    )
    d.text((chip_x + 14, chip_y + 9), agree_text, font=mono, fill=color)

    d.text((80, H - 40), "INTELLCLUSTER.COM  ·  BLIND JURY PROTOCOL",
           font=mono, fill=(72, 79, 88))
    return _to_png_bytes(img)
