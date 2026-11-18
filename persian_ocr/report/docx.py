from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_RTL_SEG = re.compile(r"([\u0621-\u064A\u067E-\u06D5\uFB50-\uFDFF\uFE70-\uFEFF]+(?:\s+[\u0621-\u064A\u067E-\u06D5\uFB50-\uFDFF\uFE70-\uFEFF]+)*)")
_MD_SEP = re.compile(r":?-{3,}:?")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/main" Target="word/document.xml"/>'
    "</Relationships>"
)


def _clean(text: str) -> str:
    return _INVALID_XML.sub("", text)


def _runs(text: str, bold: bool = False, size: int = 22, color: str | None = None) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    extra = ("<w:b/><w:bCs/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "")
    fonts = '<w:rFonts w:ascii="Tahoma" w:hAnsi="Tahoma" w:cs="Tahoma"/>'
    sz = f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    parts = []
    for seg in _RTL_SEG.split(cleaned):
        if not seg:
            continue
        rtl = "<w:rtl/>" if _RTL_SEG.fullmatch(seg) else ""
        parts.append(f'<w:r><w:rPr>{fonts}{sz}{extra}{rtl}</w:rPr><w:t xml:space="preserve">{escape(seg)}</w:t></w:r>')
    return "".join(parts)


def _para(text: str, page_break: bool = False, bold: bool = False, size: int = 22, color: str | None = None, space_after: int = 80) -> str:
    brk = "<w:pageBreakBefore/>" if page_break else ""
    return (
        f"<w:p><w:pPr>{brk}<w:bidi/>"
        f'<w:spacing w:after="{space_after}" w:line="320" w:lineRule="auto"/>'
        '<w:jc w:val="right"/></w:pPr>'
        f"{_runs(text, bold=bold, size=size, color=color)}</w:p>"
    )


def _table(rows: list[list[str]]) -> str:
    ncols = max(len(r) for r in rows)
    col_w = max(500, 9600 // max(1, ncols))
    grid = "".join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(ncols))
    border = '<w:top w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/><w:left w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/><w:right w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="CBD2DA"/>'
    trs = []
    for row in rows:
        padded = row + [""] * (ncols - len(row))
        tcs = "".join(
            '<w:tc><w:tcPr><w:tcMar><w:top w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar></w:tcPr>'
            f"{_para(cell, size=20, space_after=20)}</w:tc>"
            for cell in padded
        )
        trs.append(f"<w:tr>{tcs}</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:bidiVisual/>'
        f"<w:tblBorders>{border}</w:tblBorders></w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(trs)}</w:tbl>"
    )


def _page_blocks(text: str, page_label: str | None, page_break: bool) -> str:
    blocks: list[str] = []
    pending_break = page_break
    if page_label:
        blocks.append(_para(page_label, page_break=pending_break, bold=True, size=18, color="5D6879", space_after=100))
        pending_break = False

    rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal pending_break
        if rows:
            blocks.append(_table(rows))
            rows.clear()
            pending_break = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|") and len(line) >= 2:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and not all(_MD_SEP.fullmatch(c) for c in cells if c):
                rows.append(cells)
            continue
        flush_table()
        if line:
            blocks.append(_para(line, page_break=pending_break))
            pending_break = False
    flush_table()
    if pending_break or (not blocks and page_label is None):
        blocks.append(_para("", page_break=pending_break))
    return "".join(blocks)


def build_docx(pages: list[dict]) -> bytes:
    multi = len(pages) > 1
    body = "".join(
        _page_blocks(
            str(p.get("text") if "text" in p else p.get("text_dedup", "")),
            f"صفحه {p.get('page', idx + 1)}" if multi else None,
            page_break=idx > 0,
        )
        for idx, p in enumerate(pages)
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
        "<w:bidi/></w:sectPr></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
    return buf.getvalue()
