from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Mm, Pt

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_MD_SEP = re.compile(r":?-{3,}:?")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹")
_A4_W_MM = 210
_A4_H_MM = 297
_MARGIN_MM = 12
_CONTENT_TWIPS = round((_A4_W_MM - 2 * _MARGIN_MM) * 1440 / 25.4)


def _clean(text: str) -> str:
    return _CONTROL.sub("", text).translate(_AR_DIGITS)


def _set_sect_rtl(sec) -> None:
    sect_pr = sec._sectPr
    bidi = OxmlElement("w:bidi")
    doc_grid = sect_pr.find(qn("w:docGrid"))
    if doc_grid is not None:
        doc_grid.addprevious(bidi)
    else:
        sect_pr.append(bidi)


def _set_para_rtl(p, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after: int = 2, space_before: int = 0) -> None:
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    pPr = p._p.get_or_add_pPr()
    spacing = pPr.find(qn("w:spacing"))
    bidi = OxmlElement("w:bidi")
    if spacing is not None:
        spacing.addprevious(bidi)
    else:
        pPr.insert(0, bidi)
    p.alignment = align


def _add_run(p, text: str, size_pt: float = 10.5, bold: bool = False) -> None:
    cleaned = _clean(text)
    if not cleaned:
        return
    r = p.add_run(cleaned)
    r.bold = bold
    r.font.name = "Tahoma"
    r.font.size = Pt(size_pt)
    rPr = r._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:cs"), "Tahoma")


def _style_table(tbl, bordered: bool, col_widths: list[int]) -> None:
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    if bordered:
        tbl.style = "Table Grid"
    tblPr = tbl._tbl.tblPr
    bidi = OxmlElement("w:bidiVisual")
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is not None:
        tblW.addprevious(bidi)
    else:
        tblPr.insert(0, bidi)
    if not bordered:
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            '<w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/>'
            '<w:right w:val="none"/><w:insideH w:val="none"/><w:insideV w:val="none"/>'
            "</w:tblBorders>"
        )
        look = tblPr.find(qn("w:tblLook"))
        if look is not None:
            look.addprevious(borders)
        else:
            tblPr.append(borders)
    tblGrid = tbl._tbl.tblGrid
    for child in list(tblGrid):
        tblGrid.remove(child)
    for w in col_widths:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(w))
        tblGrid.append(gc)
    for tr in tbl._tbl.tr_lst:
        for idx, tc in enumerate(tr.tc_lst):
            tcPr = tc.get_or_add_tcPr()
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcW = OxmlElement("w:tcW")
                tcPr.insert(0, tcW)
            tcW.set(qn("w:w"), str(col_widths[idx]))
            tcW.set(qn("w:type"), "dxa")


def _cluster_values(vals: list[float], tol: float) -> list[float]:
    if not vals:
        return []
    ordered = sorted(vals)
    groups = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _align_for(box: list[int], page_w: int) -> WD_ALIGN_PARAGRAPH:
    x0, _, x1, _ = box
    cx = (x0 + x1) / 2
    bw = x1 - x0
    if bw < page_w * 0.75 and abs(cx - page_w / 2) <= page_w * 0.10:
        return WD_ALIGN_PARAGRAPH.CENTER
    if x1 < page_w * 0.55 and x0 < page_w * 0.25:
        return WD_ALIGN_PARAGRAPH.LEFT
    return WD_ALIGN_PARAGRAPH.RIGHT


def _configure_section(sec, landscape: bool) -> int:
    w_mm, h_mm = (_A4_H_MM, _A4_W_MM) if landscape else (_A4_W_MM, _A4_H_MM)
    sec.page_width = Mm(w_mm)
    sec.page_height = Mm(h_mm)
    sec.top_margin = Mm(_MARGIN_MM)
    sec.bottom_margin = Mm(_MARGIN_MM)
    sec.left_margin = Mm(_MARGIN_MM)
    sec.right_margin = Mm(_MARGIN_MM)
    _set_sect_rtl(sec)
    return round((w_mm - 2 * _MARGIN_MM) * 1440 / 25.4)


def _emit_table_group(doc: Document, cells: list[list[int]], cell_items: dict[int, list[dict]], cell_indices: list[int], page_w: float, page_h: float, content_twips: int) -> None:
    tol_x = max(10.0, page_w * 0.01)
    tol_y = max(10.0, page_h * 0.008)
    group_cells = [cells[i] for i in cell_indices]
    y_edges = _cluster_values([c[1] for c in group_cells] + [c[3] for c in group_cells], tol_y)
    x_edges = list(reversed(_cluster_values([c[0] for c in group_cells] + [c[2] for c in group_cells], tol_x)))
    if len(y_edges) < 2 or len(x_edges) < 2:
        return

    nrows, ncols = len(y_edges) - 1, len(x_edges) - 1
    total_x = max(1.0, x_edges[0] - x_edges[-1])
    table_twips = max(2000, round(min(1.0, total_x / page_w) * content_twips))
    col_widths = [max(300, round((x_edges[k] - x_edges[k + 1]) / total_x * table_twips)) for k in range(ncols)]

    tbl = doc.add_table(rows=nrows, cols=ncols)
    _style_table(tbl, bordered=True, col_widths=col_widths)

    def nearest_idx(val: float, edges: list[float]) -> int:
        return min(range(len(edges)), key=lambda i: abs(edges[i] - val))

    rows_cells = [row.cells for row in tbl.rows]
    occupied = [[False] * ncols for _ in range(nrows)]
    for ci in cell_indices:
        x0, y0, x1, y1 = cells[ci]
        r0 = min(nrows - 1, nearest_idx(y0, y_edges))
        r1 = max(r0 + 1, min(nrows, nearest_idx(y1, y_edges)))
        c0 = min(ncols - 1, nearest_idx(x1, x_edges))
        c1 = max(c0 + 1, min(ncols, nearest_idx(x0, x_edges)))
        if any(occupied[r][c] for r in range(r0, r1) for c in range(c0, c1)):
            continue
        for r in range(r0, r1):
            for c in range(c0, c1):
                occupied[r][c] = True
        cell = rows_cells[r0][c0]
        if r1 - r0 > 1 or c1 - c0 > 1:
            cell.merge(rows_cells[r1 - 1][c1 - 1])
        items = sorted(cell_items.get(ci, []), key=lambda it: (it["box"][1], -it["box"][2]))
        if not items:
            _set_para_rtl(cell.paragraphs[0], space_after=0)
            continue
        for k, it in enumerate(items):
            p = cell.paragraphs[0] if k == 0 else cell.add_paragraph()
            _set_para_rtl(p, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=1)
            _add_run(p, str(it.get("text", "")), size_pt=9.5)


def _emit_row_band(doc: Document, band: list[dict], page_w: int, content_twips: int) -> None:
    ordered = sorted(band, key=lambda it: -it["box"][2])
    if len(ordered) == 1:
        it = ordered[0]
        p = doc.add_paragraph()
        _set_para_rtl(p, align=_align_for(it["box"], page_w), space_after=3)
        bh = it["box"][3] - it["box"][1]
        fs = max(9.5, min(14.0, round(bh * 0.25, 1)))
        _add_run(p, str(it.get("text", "")), size_pt=fs, bold=(fs >= 12.5))
        return

    bounds = [float(page_w)]
    for a, b in zip(ordered, ordered[1:]):
        mid = (a["box"][0] + b["box"][2]) / 2
        bounds.append(max(0.0, min(float(page_w), mid)))
    bounds.append(0.0)
    col_widths = [max(400, round((bounds[k] - bounds[k + 1]) / max(1, page_w) * content_twips)) for k in range(len(ordered))]

    tbl = doc.add_table(rows=1, cols=len(ordered))
    _style_table(tbl, bordered=False, col_widths=col_widths)
    for idx, it in enumerate(ordered):
        p = tbl.rows[0].cells[idx].paragraphs[0]
        _set_para_rtl(p, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=1)
        _add_run(p, str(it.get("text", "")), size_pt=10.0)


def _render_layout_page(doc: Document, layout: dict, content_twips: int) -> None:
    page_w, page_h = int(layout["size"][0]), int(layout["size"][1])
    cells = [c for c in layout.get("cells", []) if c[2] > c[0] and c[3] > c[1]]
    items = [it for it in layout.get("items", []) if str(it.get("text", "")).strip()]

    cell_items: dict[int, list[dict]] = {}
    free_items: list[dict] = []
    for it in items:
        x0, y0, x1, y1 = it["box"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        matches = [i for i, c in enumerate(cells) if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
        if matches:
            best = min(matches, key=lambda i: (cells[i][2] - cells[i][0]) * (cells[i][3] - cells[i][1]))
            cell_items.setdefault(best, []).append(it)
        else:
            free_items.append(it)

    table_boxes = layout.get("tables", [])
    table_groups: dict[int, list[int]] = {}
    extra_cells: list[int] = []
    for ci, c in enumerate(cells):
        cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        hit = next((ti for ti, tb in enumerate(table_boxes) if tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]), None)
        if hit is not None:
            table_groups.setdefault(hit, []).append(ci)
        else:
            extra_cells.append(ci)
    groups = list(table_groups.values()) + ([extra_cells] if extra_cells else [])

    blocks: list[tuple[float, str, object]] = []
    for grp in groups:
        if grp:
            blocks.append((min(cells[i][1] for i in grp), "table", grp))

    bands: list[list[dict]] = []
    for it in sorted(free_items, key=lambda x: (x["box"][1], -x["box"][2])):
        if bands:
            prev = bands[-1]
            by0 = min(x["box"][1] for x in prev)
            by1 = max(x["box"][3] for x in prev)
            iy0, iy1 = it["box"][1], it["box"][3]
            overlap = min(by1, iy1) - max(by0, iy0)
            if overlap > 0.35 * min(by1 - by0, iy1 - iy0) or abs((by0 + by1) / 2 - (iy0 + iy1) / 2) <= 0.5 * max(by1 - by0, iy1 - iy0):
                prev.append(it)
                continue
        bands.append([it])
    for b in bands:
        blocks.append((min(x["box"][1] for x in b), "band", b))

    blocks.sort(key=lambda blk: blk[0])
    for _, kind, data in blocks:
        if kind == "table":
            _emit_table_group(doc, cells, cell_items, data, page_w, page_h, content_twips)
        else:
            _emit_row_band(doc, data, page_w, content_twips)
    if not blocks:
        _set_para_rtl(doc.add_paragraph())


def _render_plain_page(doc: Document, text: str, content_twips: int = _CONTENT_TWIPS) -> None:
    rows: list[list[str]] = []

    def flush_table() -> None:
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        col_w = [max(400, content_twips // max(1, ncols))] * ncols
        tbl = doc.add_table(rows=len(rows), cols=ncols)
        _style_table(tbl, bordered=True, col_widths=col_w)
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                p = tbl.rows[r_idx].cells[c_idx].paragraphs[0]
                _set_para_rtl(p, space_after=1)
                _add_run(p, val, size_pt=9.5)
        rows.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|") and len(line) >= 2:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if any(cells) and not all(_MD_SEP.fullmatch(c) for c in cells if c):
                rows.append(cells)
            continue
        flush_table()
        if line:
            p = doc.add_paragraph()
            _set_para_rtl(p, space_after=3)
            _add_run(p, line, size_pt=10.5)
    flush_table()


def _is_landscape(page: dict) -> bool:
    layout = page.get("layout")
    if layout and isinstance(layout.get("size"), list) and len(layout["size"]) == 2:
        return layout["size"][0] > layout["size"][1]
    return False


def build_docx(pages: list[dict]) -> bytes:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Tahoma"
    normal.font.size = Pt(10.5)

    prev_land = _is_landscape(pages[0]) if pages else False
    content_twips = _configure_section(doc.sections[0], prev_land)

    for idx, p in enumerate(pages):
        land = _is_landscape(p)
        if idx > 0:
            if land != prev_land:
                content_twips = _configure_section(doc.add_section(WD_SECTION.NEW_PAGE), land)
                prev_land = land
            else:
                doc.add_page_break()
        layout = p.get("layout")
        if layout and isinstance(layout.get("size"), list) and len(layout["size"]) == 2 and layout["size"][0] > 0 and layout["size"][1] > 0:
            _render_layout_page(doc, layout, content_twips)
        else:
            _render_plain_page(doc, str(p.get("text") if "text" in p else p.get("text_dedup", "")), content_twips)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
