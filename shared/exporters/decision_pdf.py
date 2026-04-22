"""
Phronesis decision → PDF.

Keeps the Fin-aligned visual identity: navy bg, orange accent bar on the
winner, Instrument Serif-style (we fall back to Helvetica since reportlab
doesn't have Instrument Serif bundled; the feel is still editorial because
we use large thin weights).
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


BG        = HexColor("#020917")
SURFACE   = HexColor("#0c1628")
BORDER    = Color(1, 1, 1, 0.10)
ACCENT    = HexColor("#FF5600")
TEXT      = HexColor("#ffffff")
TEXT_MUTED = Color(1, 1, 1, 0.60)
TEXT_DIM   = Color(1, 1, 1, 0.35)
GREEN     = HexColor("#3fb950")
RED       = HexColor("#f85149")


def _wrap_text(c: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> list[str]:
    """Naive word-wrap respecting max_width in points."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip() if cur else w
        if c.stringWidth(trial, font, size) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build_decision_pdf(decision: dict) -> bytes:
    """Render a Phronesis decision dict as a PDF. Returns raw bytes."""
    buf = BytesIO()
    W, H = LETTER
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle(f"Phronesis — {decision.get('winner', 'Decision')}")
    c.setAuthor("IntellCluster")
    c.setSubject("Phronesis decision analysis")

    def bg():
        c.setFillColor(BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)

    bg()

    margin = 0.75 * inch
    y = H - margin

    # Brand row
    c.setFillColor(ACCENT)
    c.circle(margin + 3, y + 4, 3, fill=1, stroke=0)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 14, y, "INTELLCLUSTER")
    c.setFillColor(TEXT_DIM)
    c.drawString(margin + 94, y, "·  PHRONESIS  ·  DECISION ANALYSIS")
    y -= 10

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(margin, y, W - margin, y)
    y -= 36

    # Question
    c.setFillColor(TEXT_MUTED)
    c.setFont("Helvetica", 8.5)
    c.drawString(margin, y, "QUESTION")
    y -= 18
    c.setFillColor(TEXT)
    c.setFont("Times-Roman", 18)
    for line in _wrap_text(c, decision.get("question", ""), "Times-Roman", 18, W - 2 * margin):
        c.drawString(margin, y, line)
        y -= 22
    y -= 12

    # Winner block (with orange accent bar)
    winner = decision.get("winner", "")
    why = decision.get("why_winner_won", "")
    conf = decision.get("confidence_score", 0)
    judges = decision.get("judge_count", 3)
    agree = decision.get("judges_agree", False)

    block_h = 120
    c.setFillColor(SURFACE)
    c.rect(margin, y - block_h, W - 2 * margin, block_h, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(margin, y - block_h, 3, block_h, fill=1, stroke=0)

    inner_x = margin + 18
    ty = y - 22
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(inner_x, ty, "BEST OPTION")
    ty -= 20
    c.setFillColor(TEXT)
    c.setFont("Times-Roman", 22)
    c.drawString(inner_x, ty, winner[:80])
    ty -= 18
    if why:
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 10)
        for line in _wrap_text(c, why, "Helvetica", 10, W - 2 * margin - 24)[:2]:
            c.drawString(inner_x, ty, line)
            ty -= 13

    # Confidence chips on the right of the winner block
    chip_y = y - 22
    chip_x = W - margin - 14
    def draw_chip(text: str, color, x_right):
        tw = c.stringWidth(text, "Helvetica-Bold", 8) + 14
        c.setStrokeColor(color)
        c.setFillColor(color, alpha=0.12)
        c.roundRect(x_right - tw, chip_y - 8, tw, 16, 3, fill=1, stroke=1)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x_right - tw + 7, chip_y - 3, text)
        return x_right - tw - 6

    chip_x = draw_chip(f"{int(conf)}% CONFIDENCE", ACCENT, chip_x)
    draw_chip(f"{'UNANIMOUS' if agree else 'SPLIT'} · {judges} ANALYSTS",
              GREEN if agree else HexColor("#d29922"), chip_x)

    y -= block_h + 28

    # Ranked options
    c.setFillColor(TEXT_MUTED)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margin, y, "RANKED OPTIONS")
    y -= 16

    opts = decision.get("ranked_options") or []
    for opt in opts:
        if y < margin + 100:
            c.showPage()
            bg()
            y = H - margin

        rank = opt.get("rank", 0)
        name = opt.get("option", "")
        score = float(opt.get("final_score") or 0)
        strengths = opt.get("strengths") or []
        weaknesses = opt.get("weaknesses") or []

        is_winner = rank == 1
        row_h = 64 + (min(len(strengths) + len(weaknesses), 6) * 11)

        c.setFillColor(SURFACE)
        c.rect(margin, y - row_h, W - 2 * margin, row_h, fill=1, stroke=0)
        if is_winner:
            c.setFillColor(ACCENT)
            c.rect(margin, y - row_h, 2.5, row_h, fill=1, stroke=0)

        # Rank number
        c.setFillColor(ACCENT if is_winner else TEXT_DIM)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin + 16, y - 22, f"{rank:02d}")

        # Name
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(margin + 44, y - 22, name[:65])

        # Score (right-aligned)
        c.setFillColor(ACCENT if is_winner else TEXT_MUTED)
        c.setFont("Helvetica-Bold", 13)
        score_str = f"{score:.1f}"
        c.drawRightString(W - margin - 16, y - 22, score_str)

        # Progress bar
        bar_y = y - 36
        bar_w = W - 2 * margin - 32
        c.setFillColor(Color(1, 1, 1, 0.06))
        c.rect(margin + 16, bar_y, bar_w, 3, fill=1, stroke=0)
        fill_w = bar_w * min(max(score / 10.0, 0), 1)
        c.setFillColor(ACCENT if is_winner else Color(1, 1, 1, 0.20))
        c.rect(margin + 16, bar_y, fill_w, 3, fill=1, stroke=0)

        # Strengths + weaknesses
        bullet_y = bar_y - 14
        for s in strengths[:3]:
            c.setFillColor(GREEN)
            c.circle(margin + 20, bullet_y + 4, 1.6, fill=1, stroke=0)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica", 9)
            for line in _wrap_text(c, s, "Helvetica", 9, W - 2 * margin - 40)[:1]:
                c.drawString(margin + 28, bullet_y, line)
            bullet_y -= 11
        for w in weaknesses[:2]:
            c.setFillColor(RED)
            c.circle(margin + 20, bullet_y + 4, 1.6, fill=1, stroke=0)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica", 9)
            for line in _wrap_text(c, w, "Helvetica", 9, W - 2 * margin - 40)[:1]:
                c.drawString(margin + 28, bullet_y, line)
            bullet_y -= 11

        y -= row_h + 6

    # Footer
    y = margin - 10
    c.setFillColor(TEXT_DIM)
    c.setFont("Helvetica", 7.5)
    run_id = decision.get("run_id", "")
    c.drawString(margin, y, f"INTELLCLUSTER.COM  ·  {run_id}  ·  PHRONESIS DECISION ANALYSIS")

    c.showPage()
    c.save()
    return buf.getvalue()
