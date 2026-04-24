"""
Phronesis OS advisory session → PDF.

Same visual language as decision_pdf (Fin-aligned: navy bg, orange accent
bar on the hero, Helvetica fallback for Instrument Serif). Renders a
FinalAdviceReport plus session context into a portable advisory brief.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from phronesis.advisory.types import AdvisorySession


BG         = HexColor("#020917")
SURFACE    = HexColor("#0c1628")
BORDER     = Color(1, 1, 1, 0.10)
ACCENT     = HexColor("#FF5600")
TEXT       = HexColor("#ffffff")
TEXT_MUTED = Color(1, 1, 1, 0.60)
TEXT_DIM   = Color(1, 1, 1, 0.35)
GREEN      = HexColor("#3fb950")
AMBER      = HexColor("#d29922")
RED        = HexColor("#f85149")


def _wrap(c: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> list[str]:
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


def _color_for(color_name: str):
    return {"green": GREEN, "yellow": AMBER, "red": RED}.get(
        (color_name or "yellow").lower(), AMBER
    )


def build_advisory_pdf(session: AdvisorySession) -> bytes:
    """
    Render an AdvisorySession (with its FinalAdviceReport) as a letter-size
    PDF. Multi-page as needed. Returns raw bytes.

    Raises ValueError if the session has no completed report (the only
    required field — everything else is rendered if present, skipped if not).
    """
    if not session.report:
        raise ValueError("Session has no completed report to render")

    report = session.report

    buf = BytesIO()
    W, H = LETTER
    c = canvas.Canvas(buf, pagesize=LETTER)

    title = (report.recommended_best_move or "Phronesis OS advisory")[:80]
    c.setTitle(f"Phronesis OS — {title}")
    c.setAuthor("IntellCluster")
    c.setSubject("Phronesis OS advisory brief")

    margin = 0.75 * inch
    content_width = W - 2 * margin

    def new_page():
        c.setFillColor(BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)

    def ensure_space(needed: float, current_y: float) -> float:
        """If we'd run off the page, start a new one. Returns y to continue at."""
        if current_y - needed < margin:
            c.showPage()
            new_page()
            return H - margin
        return current_y

    new_page()
    y = H - margin

    # ─── Brand row ───
    c.setFillColor(ACCENT)
    c.circle(margin + 3, y + 4, 3, fill=1, stroke=0)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 14, y, "INTELLCLUSTER")
    c.setFillColor(TEXT_DIM)
    c.drawString(margin + 94, y, "·  PHRONESIS OS  ·  ADVISORY BRIEF")
    y -= 12

    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(margin, y, W - margin, y)
    y -= 26

    # ─── Advisory question ───
    question = (session.intake.advisory_question if session.intake
                else session.raw_input)
    c.setFillColor(TEXT_MUTED)
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, "ADVISORY QUESTION")
    y -= 14
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 12)
    for line in _wrap(c, question, "Helvetica", 12, content_width):
        c.drawString(margin, y, line)
        y -= 15
    y -= 12

    # ─── Recommended best move (hero card) ───
    y = ensure_space(140, y)
    card_height = 0  # will pre-measure below

    # Pre-measure the hero text
    hero_lines = _wrap(c, report.recommended_best_move, "Helvetica-Bold", 16, content_width - 24)
    sub_lines = []
    if report.immediate_next_step:
        sub_lines = _wrap(c, f"Next 48 hours: {report.immediate_next_step}",
                          "Helvetica-Oblique", 11, content_width - 24)
    card_height = 24 + len(hero_lines) * 20 + 8 + len(sub_lines) * 14 + 16
    y = ensure_space(card_height, y)

    # Accent rail
    c.setFillColor(ACCENT)
    c.rect(margin, y - card_height, 3, card_height, fill=1, stroke=0)
    # Card bg
    c.setFillColor(SURFACE)
    c.rect(margin + 3, y - card_height, content_width - 3, card_height, fill=1, stroke=0)

    # Labels inside card
    card_y = y - 24
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin + 18, card_y, "RECOMMENDED BEST MOVE")
    # Confidence chip on the right
    conf_label = (report.confidence_level or "moderate").upper().replace("-", "–")
    if report.confidence_range:
        conf_label = f"{conf_label} · {report.confidence_range}"
    conf_width = c.stringWidth(conf_label, "Helvetica-Bold", 8) + 12
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(W - margin - 8, card_y, conf_label)

    card_y -= 18
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 16)
    for line in hero_lines:
        c.drawString(margin + 18, card_y, line)
        card_y -= 20
    if sub_lines:
        card_y -= 8
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Oblique", 11)
        for line in sub_lines:
            c.drawString(margin + 18, card_y, line)
            card_y -= 14

    y -= card_height + 20

    # ─── Ranked options ───
    if report.ranked_options:
        y = ensure_space(40 + 30 * len(report.ranked_options), y)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, "RANKED OPTIONS")
        y -= 16

        max_score = max((o.score for o in report.ranked_options), default=10) or 10
        for o in report.ranked_options:
            y = ensure_space(28, y)
            # Rank badge
            c.setFillColor(_color_for(o.color))
            c.rect(margin, y - 14, 3, 16, fill=1, stroke=0)
            # Rank + option name
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin + 10, y - 2, f"#{o.rank}")
            c.setFillColor(TEXT)
            c.setFont("Helvetica", 11)
            opt_text = o.option
            if c.stringWidth(opt_text, "Helvetica", 11) > content_width - 120:
                while c.stringWidth(opt_text + "…", "Helvetica", 11) > content_width - 120 and len(opt_text) > 4:
                    opt_text = opt_text[:-1]
                opt_text += "…"
            c.drawString(margin + 38, y - 2, opt_text)
            # Score on right
            c.setFillColor(TEXT)
            c.setFont("Helvetica-Bold", 12)
            c.drawRightString(W - margin, y - 2, f"{o.score:.1f}")
            # Bar
            bar_y = y - 14
            bar_w = content_width - 2
            c.setFillColor(Color(1, 1, 1, 0.06))
            c.rect(margin + 2, bar_y, bar_w, 3, fill=1, stroke=0)
            c.setFillColor(_color_for(o.color))
            c.rect(margin + 2, bar_y, bar_w * (o.score / max_score), 3, fill=1, stroke=0)
            y -= 28
        y -= 10

    def _bullet_block(header: str, items: list[str], dot_color=ACCENT):
        nonlocal y
        if not items:
            return
        y = ensure_space(30 + 18 * len(items), y)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, header.upper())
        y -= 14
        for item in items:
            lines = _wrap(c, item, "Helvetica", 10, content_width - 16)
            y = ensure_space(len(lines) * 13 + 6, y)
            # Dot
            c.setFillColor(dot_color)
            c.circle(margin + 4, y - 4, 1.5, fill=1, stroke=0)
            # First line
            c.setFillColor(TEXT)
            c.setFont("Helvetica", 10)
            for i, line in enumerate(lines):
                c.drawString(margin + 14, y - 4, line)
                y -= 13
            y -= 2
        y -= 8

    # ─── Why this wins ───
    _bullet_block("Why this wins", report.why_this_wins, ACCENT)

    # ─── Key risks ───
    _bullet_block("Key risks", report.key_risks, RED)

    # ─── What could change this ───
    _bullet_block("What could change this advice", report.what_could_change_this, AMBER)

    # ─── Agent consensus ───
    if report.agent_consensus:
        y = ensure_space(40 + 16 * len(report.agent_consensus), y)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, "AGENT CONSENSUS")
        y -= 14
        for role, pick in report.agent_consensus.items():
            y = ensure_space(16, y)
            c.setFillColor(TEXT_DIM)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin + 14, y, f"{role.upper()}")
            c.setFillColor(TEXT)
            c.setFont("Helvetica", 10)
            c.drawString(margin + 120, y, pick)
            y -= 14
        y -= 4
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(margin, y, f"Consensus level: {report.consensus_level.replace('-', '–').capitalize()}")
        y -= 16

    # ─── Action ladder ───
    if report.action_ladder:
        y = ensure_space(30 + 20 * len(report.action_ladder), y)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, "IF WE WERE YOU, WE'D DO THIS")
        y -= 16
        for i, step in enumerate(report.action_ladder, 1):
            step_lines = _wrap(c, step, "Helvetica", 10, content_width - 36)
            y = ensure_space(len(step_lines) * 13 + 8, y)
            c.setFillColor(ACCENT)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin + 8, y - 4, f"{i:02d}")
            c.setFillColor(TEXT)
            c.setFont("Helvetica", 10)
            for line in step_lines:
                c.drawString(margin + 36, y - 4, line)
                y -= 13
            y -= 4

    # ─── Footer ───
    c.setFillColor(TEXT_DIM)
    c.setFont("Helvetica", 8)
    meta_bits = [f"Run ID: {session.run_id}"]
    if session.total_cost_usd:
        meta_bits.append(f"Cost ${session.total_cost_usd:.4f}")
    if session.total_latency_ms:
        meta_bits.append(f"{session.total_latency_ms / 1000:.1f}s")
    if session.category:
        meta_bits.append(f"Category: {session.category}")
    c.drawString(margin, margin / 2, "  ·  ".join(meta_bits))
    c.drawRightString(W - margin, margin / 2, "intellcluster.com  ·  Phronesis OS")

    c.save()
    return buf.getvalue()
