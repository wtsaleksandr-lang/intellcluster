"""
Synthesis research run → PDF.

Same visual language as advisory_pdf but renders a StructuredReport
(executive summary, key findings, evidence table with verification
chips, contradictions, recommendation, risks, next actions, sources).

Designed for print + share: light background, accent orange, compact.
Single pass through the report with automatic page breaks. No external
fonts required — Helvetica is the ReportLab built-in.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


# ── palette (print-friendly: light bg, dark text) ──
BG          = HexColor("#ffffff")
SURFACE     = HexColor("#f6f7f9")
BORDER      = HexColor("#dfe3e9")
TEXT        = HexColor("#0d1117")
TEXT_MUTED  = HexColor("#4b5563")
TEXT_DIM    = HexColor("#9ca3af")
ACCENT      = HexColor("#FF5600")
GREEN       = HexColor("#16a34a")
AMBER       = HexColor("#d97706")
RED         = HexColor("#dc2626")
GREY        = HexColor("#9ca3af")

BAND_COLOR = {
    "low":           RED,
    "moderate":      AMBER,
    "moderate-high": GREEN,
    "high":          GREEN,
}

STRENGTH_COLOR = {"strong": GREEN, "moderate": AMBER, "weak": GREY}
VERIFICATION_COLOR = {"supported": GREEN, "partial": AMBER, "unsupported": RED}


# ──────────────────────── text wrapping ────────────────────────

def _wrap(c: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> list[str]:
    """Greedy word-wrap respecting the real measured width."""
    if not text:
        return []
    out: list[str] = []
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip() if cur else w
            if c.stringWidth(trial, font, size) <= max_width:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out


# ──────────────────────── page cursor ────────────────────────

class _Cursor:
    """Vertical cursor with automatic page-break."""

    def __init__(self, c: canvas.Canvas, page_w: float, page_h: float, margin: float):
        self.c = c
        self.W = page_w
        self.H = page_h
        self.margin = margin
        self.y = page_h - margin
        self.page = 1
        self.content_width = page_w - 2 * margin

    def space(self, dy: float) -> None:
        self.y -= dy
        self.ensure(0)

    def ensure(self, required: float) -> None:
        if self.y - required < self.margin + 0.5 * inch:
            self.new_page()

    def new_page(self) -> None:
        self._footer()
        self.c.showPage()
        self.page += 1
        self._header_line()
        self.y = self.H - self.margin

    def _header_line(self) -> None:
        self.c.setFillColor(TEXT_DIM)
        self.c.setFont("Helvetica", 8)
        self.c.drawString(self.margin, self.H - self.margin + 14,
                          "Synthesis — Research Report")

    def _footer(self) -> None:
        self.c.setFillColor(TEXT_DIM)
        self.c.setFont("Helvetica", 8)
        self.c.drawString(self.margin, 0.45 * inch, f"Page {self.page}")
        self.c.drawRightString(self.W - self.margin, 0.45 * inch,
                               "intellcluster.io / synthesis")


# ──────────────────────── primitives ────────────────────────

def _draw_text(cur: _Cursor, text: str, font="Helvetica", size=10.5, color=TEXT,
               leading=1.4, left_pad=0.0) -> None:
    lines = _wrap(cur.c, text, font, size, cur.content_width - left_pad)
    cur.c.setFont(font, size)
    cur.c.setFillColor(color)
    line_h = size * leading
    for line in lines:
        cur.ensure(line_h)
        cur.c.drawString(cur.margin + left_pad, cur.y - size, line)
        cur.y -= line_h


def _draw_fig_label(cur: _Cursor, fig_num: int, label: str) -> None:
    cur.space(10)
    cur.ensure(20)
    cur.c.setFillColor(ACCENT)
    cur.c.setFont("Helvetica-Bold", 8.5)
    cur.c.drawString(cur.margin, cur.y, f"FIG {fig_num}")
    cur.c.setFillColor(TEXT_DIM)
    cur.c.drawString(cur.margin + 0.35 * inch, cur.y, f"— {label}")
    cur.y -= 4
    cur.c.setStrokeColor(BORDER)
    cur.c.setLineWidth(0.4)
    cur.c.line(cur.margin, cur.y, cur.W - cur.margin, cur.y)
    cur.y -= 12


def _draw_pill(cur: _Cursor, x: float, y: float, text: str, color) -> float:
    """Draw a small pill; returns the right x of the drawn pill."""
    cur.c.setFont("Helvetica-Bold", 7.5)
    w = cur.c.stringWidth(text, "Helvetica-Bold", 7.5) + 10
    cur.c.setStrokeColor(color)
    cur.c.setFillColor(BG)
    cur.c.roundRect(x, y, w, 12, 6, stroke=1, fill=1)
    cur.c.setFillColor(color)
    cur.c.drawString(x + 5, y + 3, text)
    return x + w + 6


def _draw_source_chip(cur: _Cursor, x: float, y: float, cid: int) -> float:
    text = f"[{cid}]"
    cur.c.setFont("Helvetica", 7.5)
    w = cur.c.stringWidth(text, "Helvetica", 7.5) + 8
    cur.c.setStrokeColor(ACCENT)
    cur.c.setFillColor(BG)
    cur.c.roundRect(x, y, w, 11, 3, stroke=1, fill=1)
    cur.c.setFillColor(ACCENT)
    cur.c.drawString(x + 4, y + 3, text)
    return x + w + 3


# ──────────────────────── sections ────────────────────────

def _draw_title(cur: _Cursor, entry: dict) -> None:
    prompt = (entry.get("prompt") or "").strip()[:300]
    title_lines = _wrap(cur.c, prompt, "Helvetica-Bold", 16, cur.content_width)
    cur.c.setFillColor(TEXT)
    cur.c.setFont("Helvetica-Bold", 16)
    for line in title_lines[:4]:
        cur.ensure(22)
        cur.c.drawString(cur.margin, cur.y - 16, line)
        cur.y -= 22
    # Metadata row
    meta_bits = []
    if entry.get("run_id"):       meta_bits.append(str(entry["run_id"]))
    if entry.get("mode"):         meta_bits.append(entry["mode"].upper())
    if entry.get("model_count"):  meta_bits.append(f"{entry['model_count']} MODELS")
    sources = entry.get("sources") or []
    if sources:                   meta_bits.append(f"{len(sources)} SOURCES")
    cur.c.setFillColor(TEXT_MUTED)
    cur.c.setFont("Courier", 9)
    cur.c.drawString(cur.margin, cur.y - 10, "   ·   ".join(meta_bits))
    cur.y -= 22

    report = entry.get("structured_report") or {}
    confidence = (report.get("confidence") or {})
    band = confidence.get("band")
    if band:
        color = BAND_COLOR.get(band, AMBER)
        _draw_pill(cur, cur.margin, cur.y - 14, f"CONFIDENCE: {band.upper()}", color)
        cur.y -= 20

    # Scope chips
    scope = entry.get("scope") or {}
    x = cur.margin
    y = cur.y - 14
    for field, label in (("audience", "AUDIENCE"),
                          ("decision_intent", "INTENT"),
                          ("timeframe", "WHEN"),
                          ("region", "WHERE")):
        val = scope.get(field)
        if not val:
            continue
        text = f"{label}: {val}"
        cur.c.setFont("Helvetica", 7.5)
        w = cur.c.stringWidth(text, "Helvetica", 7.5) + 10
        cur.c.setStrokeColor(BORDER); cur.c.setFillColor(SURFACE)
        cur.c.roundRect(x, y, w, 12, 6, stroke=1, fill=1)
        cur.c.setFillColor(TEXT_MUTED)
        cur.c.drawString(x + 5, y + 3, text)
        x += w + 6
        if x > cur.W - cur.margin - 120:   # wrap to new row
            y -= 16
            x = cur.margin
    cur.y = y - 8


def _draw_exec_summary(cur: _Cursor, report: dict) -> None:
    summary = (report.get("executive_summary") or "").strip()
    if not summary:
        return
    _draw_fig_label(cur, 1, "EXECUTIVE SUMMARY")
    # Orange accent bar
    cur.c.setFillColor(ACCENT)
    cur.c.rect(cur.margin, cur.y - 5, 2.5, -5, stroke=0, fill=1)
    _draw_text(cur, summary, font="Helvetica", size=11, color=TEXT, left_pad=10)


def _draw_key_findings(cur: _Cursor, report: dict) -> None:
    findings = report.get("key_findings") or []
    if not findings:
        return
    _draw_fig_label(cur, 2, "KEY FINDINGS")
    for i, f in enumerate(findings, 1):
        text = (f.get("finding") or "").strip()
        if not text:
            continue
        cur.ensure(16)
        # number
        cur.c.setFillColor(TEXT_DIM)
        cur.c.setFont("Courier", 8)
        cur.c.drawString(cur.margin, cur.y - 10, f"{i:02d}")
        _draw_text(cur, text, font="Helvetica", size=10.5, color=TEXT, left_pad=24)
        # strength + citations row
        strength = (f.get("strength") or "moderate").lower()
        s_color = STRENGTH_COLOR.get(strength, AMBER)
        x = cur.margin + 24
        y = cur.y - 4
        x = _draw_pill(cur, x, y, strength.upper(), s_color)
        for cid in (f.get("citations") or []):
            x = _draw_source_chip(cur, x, y, cid)
        cur.y -= 18


def _draw_evidence_table(cur: _Cursor, report: dict) -> None:
    rows = report.get("evidence_table") or []
    if not rows:
        return
    _draw_fig_label(cur, 3, "EVIDENCE TABLE")
    for row in rows:
        claim = (row.get("claim") or "").strip()
        if not claim:
            continue
        cur.ensure(22)
        _draw_text(cur, claim, font="Helvetica", size=10, color=TEXT)
        note = (row.get("note") or "").strip()
        if note:
            _draw_text(cur, note, font="Helvetica-Oblique", size=9, color=TEXT_MUTED, left_pad=0)

        # Strength + verification + citations
        x = cur.margin
        y = cur.y - 4
        strength = (row.get("strength") or "moderate").lower()
        x = _draw_pill(cur, x, y, strength.upper(), STRENGTH_COLOR.get(strength, AMBER))
        verdict = row.get("verification")
        if verdict:
            x = _draw_pill(cur, x, y, verdict.upper(),
                           VERIFICATION_COLOR.get(verdict, AMBER))
        for cid in (row.get("citations") or []):
            x = _draw_source_chip(cur, x, y, cid)
        cur.y -= 20


def _draw_confidence(cur: _Cursor, report: dict) -> None:
    confidence = report.get("confidence") or {}
    components = confidence.get("components") or {}
    rationale = (confidence.get("rationale") or "").strip()
    note = (report.get("source_confidence_note") or "").strip()
    if not (components or rationale or note):
        return
    _draw_fig_label(cur, 4, "SOURCE CONFIDENCE")
    if rationale:
        _draw_text(cur, rationale, font="Helvetica", size=10.5, color=TEXT)
    if note:
        _draw_text(cur, note, font="Helvetica", size=10, color=TEXT_MUTED)

    # Component bars in two columns
    labels = {
        "source_quality":       "source quality",
        "evidence_quantity":    "evidence quantity",
        "source_agreement":     "source agreement",
        "freshness":            "freshness",
        "contradiction_penalty":"contradictions",
        "model_consensus":      "model consensus",
    }
    col_w = (cur.content_width - 16) / 2
    row_h = 18
    cur.space(6)
    i = 0
    for key, label in labels.items():
        val = float(components.get(key, 0.0))
        col = i % 2
        row = i // 2
        x = cur.margin + col * (col_w + 16)
        y = cur.y - 6 - row * row_h
        cur.ensure(0)
        cur.c.setFillColor(TEXT_DIM)
        cur.c.setFont("Helvetica-Bold", 7.5)
        cur.c.drawString(x, y + 6, label.upper())
        # bar
        bar_w = col_w
        cur.c.setFillColor(BORDER)
        cur.c.rect(x, y - 2, bar_w, 3, stroke=0, fill=1)
        fill_color = RED if key == "contradiction_penalty" else ACCENT
        cur.c.setFillColor(fill_color)
        cur.c.rect(x, y - 2, bar_w * max(0.0, min(1.0, val)), 3, stroke=0, fill=1)
        cur.c.setFillColor(TEXT_MUTED)
        cur.c.setFont("Courier", 7.5)
        cur.c.drawRightString(x + bar_w, y + 6, f"{int(val * 100)}%")
        i += 1
    cur.y -= row_h * ((i + 1) // 2) + 4


def _draw_bullets(cur: _Cursor, fig_num: int, label: str, items: list[str],
                  ordered: bool = False) -> None:
    items = [i.strip() for i in (items or []) if (i or "").strip()]
    if not items:
        return
    _draw_fig_label(cur, fig_num, label)
    for i, item in enumerate(items, 1):
        cur.ensure(16)
        bullet = f"{i}." if ordered else "•"
        cur.c.setFillColor(ACCENT if ordered else TEXT_DIM)
        cur.c.setFont("Helvetica-Bold", 9)
        cur.c.drawString(cur.margin, cur.y - 9, bullet)
        _draw_text(cur, item, font="Helvetica", size=10.5, color=TEXT, left_pad=16)
        cur.space(2)


def _draw_contradictions(cur: _Cursor, report: dict) -> None:
    contras = report.get("contradictions") or []
    if not contras:
        return
    _draw_fig_label(cur, 5, "CONTRADICTIONS / DEBATE")
    for c_ in contras:
        point = (c_.get("point") or "").strip()
        if not point:
            continue
        cur.ensure(20)
        cur.c.setFillColor(TEXT)
        cur.c.setFont("Helvetica-Bold", 10.5)
        cur.c.drawString(cur.margin, cur.y - 10, point)
        cur.y -= 14
        sa = c_.get("side_a") or ""
        sb = c_.get("side_b") or ""
        _draw_text(cur, f"Side A: {sa}", font="Helvetica", size=10, color=TEXT_MUTED)
        _draw_text(cur, f"Side B: {sb}", font="Helvetica", size=10, color=TEXT_MUTED)
        cur.space(4)


def _draw_recommendation(cur: _Cursor, report: dict) -> None:
    rec = (report.get("recommendation") or "").strip()
    if not rec:
        return
    _draw_fig_label(cur, 7, "RECOMMENDATION")
    cur.c.setFillColor(ACCENT)
    cur.c.rect(cur.margin, cur.y - 5, 2.5, -5, stroke=0, fill=1)
    _draw_text(cur, rec, font="Helvetica", size=11, color=TEXT, left_pad=10)


def _draw_sources(cur: _Cursor, sources: list, source_quality: dict) -> None:
    if not sources:
        return
    _draw_fig_label(cur, 10, "SOURCES")
    for s in sources:
        title = (s.get("title") or "(untitled)").strip()
        url = (s.get("url") or "").strip()
        domain = (s.get("domain") or "").strip()
        published = (s.get("published") or "")[:10]
        sid = s.get("id")
        q = source_quality.get(str(sid)) or source_quality.get(sid) or {}
        overall = q.get("overall") if isinstance(q, dict) else None

        cur.ensure(22)
        cur.c.setFillColor(ACCENT)
        cur.c.setFont("Helvetica-Bold", 8.5)
        cur.c.drawString(cur.margin, cur.y - 9, f"[{sid}]")
        _draw_text(cur, title, font="Helvetica", size=10, color=TEXT, left_pad=24)
        meta = " · ".join(x for x in [domain, published] if x)
        if overall is not None:
            meta = f"{meta}  ·  Q {int(float(overall) * 100)}%" if meta else f"Q {int(float(overall) * 100)}%"
        if meta:
            _draw_text(cur, meta, font="Courier", size=8, color=TEXT_DIM, left_pad=24)
        if url:
            _draw_text(cur, url, font="Helvetica-Oblique", size=8.5, color=ACCENT, left_pad=24)
        cur.space(4)


# ──────────────────────── entry point ────────────────────────

def build_synthesis_pdf(entry: dict[str, Any]) -> bytes:
    """Render a persisted Synthesis run entry (as saved by save_synthesis_run)
    into a letter-size PDF. Returns raw bytes.

    Gracefully handles entries missing the structured_report — falls back to
    dumping the legacy `output` string as a single-section PDF.
    """
    buf = BytesIO()
    W, H = LETTER
    c = canvas.Canvas(buf, pagesize=LETTER)
    margin = 0.75 * inch

    prompt = (entry.get("prompt") or "Synthesis Research Report")[:80]
    c.setTitle(f"Synthesis — {prompt}")
    c.setAuthor("IntellCluster")
    c.setSubject("Synthesis research brief")

    cur = _Cursor(c, W, H, margin)

    # Header section (prompt + metadata)
    _draw_title(cur, entry)
    cur.space(10)

    report = entry.get("structured_report")
    sources = entry.get("sources") or []
    source_quality = entry.get("source_quality") or {}

    if report:
        _draw_exec_summary(cur, report)
        _draw_key_findings(cur, report)
        _draw_evidence_table(cur, report)
        _draw_confidence(cur, report)
        _draw_contradictions(cur, report)
        _draw_bullets(cur, 6, "RISKS & UNKNOWNS", report.get("risks_unknowns"))
        _draw_recommendation(cur, report)
        _draw_bullets(cur, 8, "WHAT COULD CHANGE THIS", report.get("what_could_change"))
        _draw_bullets(cur, 9, "NEXT ACTIONS", report.get("next_actions"), ordered=True)
        _draw_sources(cur, sources, source_quality)
    else:
        # Legacy fallback — dump the raw markdown-ish output as plain text.
        legacy = (entry.get("output") or "").strip()
        _draw_fig_label(cur, 1, "SYNTHESIZED ANSWER")
        _draw_text(cur, legacy or "(no content)", font="Helvetica", size=10.5, color=TEXT)

    cur._footer()
    c.save()
    buf.seek(0)
    return buf.read()
