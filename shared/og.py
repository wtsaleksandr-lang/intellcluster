"""
Dynamic Open Graph image generator.

Generates 1200x630 SVG OG images per comparison page. SVG is natively supported
by Twitter, LinkedIn, Discord, and Slack link previews (Facebook rasterises it
server-side). No Pillow / imagemagick dependency — pure string template.
"""

from __future__ import annotations

import html
from typing import Iterable


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def compare_og_svg(title: str, options: Iterable[str], category: str = "") -> str:
    """Render a 1200x630 OG image as SVG for a compare page."""
    title = _truncate(title, 110)
    options = list(options)[:4]

    # Split title across 2-3 lines at reasonable break points
    title_lines = _wrap(title, 28, max_lines=3)

    option_pills = []
    x = 80
    y = 520
    for opt in options:
        label = _truncate(opt, 34)
        approx_width = max(140, int(len(label) * 14.5) + 48)
        option_pills.append(
            f'<g transform="translate({x} {y})">'
            f'<rect width="{approx_width}" height="54" rx="14" ry="14" fill="#1c2129" stroke="#30363d" stroke-width="1"/>'
            f'<text x="24" y="35" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', sans-serif" font-size="22" font-weight="500" fill="#e6edf3">{_escape(label)}</text>'
            f'</g>'
        )
        x += approx_width + 14
        if x > 1060:
            break

    title_tspans = "".join(
        f'<tspan x="80" dy="{70 if i > 0 else 0}">{_escape(line)}</tspan>'
        for i, line in enumerate(title_lines)
    )

    category_label = f"INTELLCLUSTER · COMPARE{' · ' + _escape(category.upper()) if category else ''}"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0d1117"/>
      <stop offset="1" stop-color="#161b22"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.85" cy="0.15" r="0.7">
      <stop offset="0" stop-color="#ff6a3d" stop-opacity="0.22"/>
      <stop offset="1" stop-color="#ff6a3d" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect width="1200" height="630" fill="url(#glow)"/>

  <!-- accent rail -->
  <rect x="0" y="0" width="6" height="630" fill="#ff6a3d"/>

  <!-- brand row -->
  <g transform="translate(80 78)">
    <circle cx="8" cy="8" r="8" fill="#ff6a3d"/>
    <circle cx="30" cy="8" r="8" fill="#4dd0e1"/>
    <text x="52" y="13" font-family="JetBrains Mono, ui-monospace, monospace" font-size="14" letter-spacing="2.5" fill="#8b949e">{category_label}</text>
  </g>

  <!-- title -->
  <text x="80" y="200" font-family="Newsreader, Georgia, serif" font-size="58" font-weight="600" fill="#e6edf3" letter-spacing="-0.5">
    {title_tspans}
  </text>

  <!-- option pills -->
  {"".join(option_pills)}

  <!-- footer -->
  <g transform="translate(80 594)">
    <text font-family="JetBrains Mono, ui-monospace, monospace" font-size="13" letter-spacing="1.8" fill="#484f58">INTELLCLUSTER.COM · MULTI-MODEL AI INTELLIGENCE</text>
  </g>
</svg>'''


def _wrap(text: str, width: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if not current:
            current = w
        elif len(current) + 1 + len(w) <= width:
            current += " " + w
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        # Ensure last line ends with ellipsis if we truncated
        last_text_used = " ".join(lines)
        if len(last_text_used) < len(text):
            lines[-1] = lines[-1].rstrip(",.;: ") + "…"
    return lines


def homepage_og_svg() -> str:
    """Default site-wide OG image (for homepage + pages without a per-entity image)."""
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0d1117"/>
      <stop offset="1" stop-color="#161b22"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.85" cy="0.15" r="0.8">
      <stop offset="0" stop-color="#ff6a3d" stop-opacity="0.24"/>
      <stop offset="1" stop-color="#ff6a3d" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect width="1200" height="630" fill="url(#glow)"/>
  <rect x="0" y="0" width="6" height="630" fill="#ff6a3d"/>

  <g transform="translate(80 100)">
    <circle cx="8" cy="8" r="8" fill="#ff6a3d"/>
    <circle cx="30" cy="8" r="8" fill="#4dd0e1"/>
    <text x="52" y="13" font-family="JetBrains Mono, ui-monospace, monospace" font-size="14" letter-spacing="2.5" fill="#8b949e">INTELLCLUSTER</text>
  </g>

  <text x="80" y="240" font-family="Newsreader, Georgia, serif" font-size="80" font-weight="600" fill="#e6edf3" letter-spacing="-1">
    <tspan x="80" dy="0">Multi-model AI</tspan>
    <tspan x="80" dy="90">intelligence.</tspan>
  </text>

  <text x="80" y="460" font-family="-apple-system, BlinkMacSystemFont, sans-serif" font-size="24" fill="#8b949e">
    <tspan x="80" dy="0">Phronesis ranks your options.</tspan>
    <tspan x="80" dy="38">Synthesis runs deep multi-model research.</tspan>
  </text>

  <g transform="translate(80 594)">
    <text font-family="JetBrains Mono, ui-monospace, monospace" font-size="13" letter-spacing="1.8" fill="#484f58">INTELLCLUSTER.COM · TWO TOOLS, ONE ECOSYSTEM</text>
  </g>
</svg>'''
