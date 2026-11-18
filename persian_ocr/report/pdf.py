from __future__ import annotations

import re

from fpdf import FPDF

from ..config import FONT_PATH

PDF_MIME = "application/pdf"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_MD_SEP = re.compile(r":?-{3,}:?")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹")


def _clean(text: str) -> str:
    return _CONTROL.sub("", text).translate(_AR_DIGITS)


def _fit_font(pdf: FPDF, text: str, max_w: float, start_pt: float) -> float:
    fs = start_pt
    pdf.set_font("Vazir", "", fs)
    w = pdf.get_string_width(text)
    if w > max_w > 0:
        fs = max(4.5, fs * max_w / w)
        pdf.set_font("Vazir", "", fs)
    return fs


def _render_layout_page(pdf: FPDF, layout: dict) -> None:
    w, h = layout["size"]
    pw, ph = (841.89, 595.28) if w > h else (595.28, 841.89)
    margin = 14.0
    scale = min((pw - 2 * margin) / w, (ph - 2 * margin) / h)
    ox = (pw - w * scale) / 2
    oy = (ph - h * scale) / 2

    pdf.set_auto_page_break(False)
    pdf.add_page(format=(pw, ph))

    pdf.set_draw_color(203, 210, 218)
    pdf.set_line_width(0.5)
    for box in layout.get("cells", []):
        x0, y0, x1, y1 = box
        if x1 > x0 and y1 > y0:
            pdf.rect(ox + x0 * scale, oy + y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale)

    items = layout.get("items", [])
    line_heights = sorted(it["box"][3] - it["box"][1] for it in items if it.get("source") == "line")
    typical = line_heights[len(line_heights) // 2] if line_heights else 0
    cell_cap = max(12.0, min(100.0, typical * 0.82)) if typical else 42.0

    pdf.set_text_color(24, 33, 43)
    for it in items:
        text = _clean(str(it.get("text", ""))).strip()
        if not text:
            continue
        x0, y0, x1, y1 = it["box"]
        bw, bh = (x1 - x0) * scale, (y1 - y0) * scale
        if bw <= 1 or bh <= 1:
            continue
        raw_px = min(cell_cap if it.get("source") == "cell" else 100.0, (y1 - y0) * 0.78)
        start_pt = max(5.5, min(28.0, raw_px * scale))
        _fit_font(pdf, text, max(4.0, bw - 2.0), start_pt)
        pdf.set_xy(ox + x0 * scale, oy + y0 * scale)
        pdf.cell(bw, bh, text, align="R")


def _render_plain_page(pdf: FPDF, text: str) -> None:
    pw, ph = 595.28, 841.89
    margin = 36.0
    pdf.set_auto_page_break(True, margin=margin)
    pdf.add_page(format=(pw, ph))
    pdf.set_margins(margin, margin, margin)
    pdf.set_xy(margin, margin)
    pdf.set_text_color(24, 33, 43)
    pdf.set_draw_color(180, 188, 198)
    pdf.set_line_width(0.5)
    usable = pw - 2 * margin

    rows: list[list[str]] = []

    def flush_table() -> None:
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        col_w = usable / max(1, ncols)
        pdf.set_font("Vazir", "", 9.5)
        for row in rows:
            padded = list(reversed(row + [""] * (ncols - len(row))))
            if pdf.get_y() + 20 > ph - margin:
                pdf.add_page(format=(pw, ph))
            for cell in padded:
                txt = _clean(cell)
                if txt:
                    _fit_font(pdf, txt, col_w - 6, 9.5)
                pdf.cell(col_w, 18, txt, border=1, align="R")
            pdf.ln(18)
        pdf.ln(4)
        rows.clear()

    for raw in _clean(text).splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|") and len(line) >= 2:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if any(cells) and not all(_MD_SEP.fullmatch(c) for c in cells if c):
                rows.append(cells)
            continue
        flush_table()
        if not line:
            pdf.ln(6)
            continue
        pdf.set_font("Vazir", "", 11)
        pdf.set_x(margin)
        pdf.multi_cell(usable, 18, line, align="R")
    flush_table()


def build_pdf(pages: list[dict]) -> bytes:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Font not found: {FONT_PATH}")
    pdf = FPDF(unit="pt")
    pdf.add_font("Vazir", "", str(FONT_PATH))
    pdf.set_text_shaping(use_shaping_engine=True, direction="rtl", script="arab", language="fas")
    for p in pages:
        layout = p.get("layout")
        if layout and isinstance(layout.get("size"), list) and len(layout["size"]) == 2 and layout["size"][0] > 0 and layout["size"][1] > 0:
            _render_layout_page(pdf, layout)
        else:
            _render_plain_page(pdf, str(p.get("text") if "text" in p else p.get("text_dedup", "")))
    return bytes(pdf.output())
