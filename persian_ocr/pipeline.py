from __future__ import annotations

import re
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import numpy as np
from indra_ocr.pipeline import Line

from .config import PipelineConfig
from .engine import OcrEngine
from .invoice import parse_invoice, reconcile_document
from .orientation import robust_upright
from .pdfio import iter_gray_pages
from .tables import Cell, Table, extract_tables, row_to_markdown, table_to_markdown
from .text import normalize, normalize_digits, postprocess_text
from .tiling import merge_lines, merge_tiles, tile_bounds
from .vision import recover_footer_segments, unwrap_circular_stamps, watermark_suppress


@dataclass
class PageOcr:
    lines: list[Line]
    tables: list[Table] = field(default_factory=list)


def _recognize_lines(engine: OcrEngine, gray: np.ndarray, config: PipelineConfig) -> list[Line]:
    if not config.tiling:
        return list(engine.conv.ocr(gray).lines)

    top_end, bottom_start = tile_bounds(gray.shape[0], config.overlap_ratio)
    top, bottom = gray[:top_end, :], gray[bottom_start:, :]
    top_lines = list(engine.conv.ocr(top).lines)
    bottom_lines = list(engine.conv.ocr(bottom).lines)

    if config.engineered:
        header = top[: int(gray.shape[0] * config.header_fraction), :]
        top_lines = merge_lines(top_lines, engine.conv.ocr(watermark_suppress(header)).lines)
        bottom_lines = merge_lines(bottom_lines, recover_footer_segments(engine.ort, gray), y_offset=-bottom_start)
        for stamp in unwrap_circular_stamps(engine.ort, gray):
            bottom_lines.append(Line(box=[stamp.box[0], stamp.box[1] - bottom_start, stamp.box[2], stamp.box[3] - bottom_start], text=stamp.text, conf=stamp.conf))

    return merge_tiles(top_lines, bottom_lines, bottom_start)


PageHook = Callable[[int, np.ndarray, PageOcr], None]


def ocr_page(engine: OcrEngine, gray: np.ndarray, config: PipelineConfig, on_page: PageHook | None = None, idx: int = 0) -> PageOcr:
    with engine.force_rtl() if config.engineered else nullcontext():
        if config.engineered:
            gray, _, _, _ = robust_upright(engine.ort, gray)
        lines = _recognize_lines(engine, gray, config)
        tables = extract_tables(engine.ort, gray) if config.engineered and config.tables else []
    page = PageOcr(lines=lines, tables=tables)
    if on_page is not None:
        on_page(idx, gray, page)
    return page


def ocr_document(engine: OcrEngine, path: str | Path, config: PipelineConfig | None = None, on_page: PageHook | None = None) -> tuple[list[PageOcr], float]:
    config = config or PipelineConfig()
    t0 = time.perf_counter()
    pages = [ocr_page(engine, gray, config, on_page, i) for i, gray in enumerate(iter_gray_pages(path, config.dpi, config.max_pages))]
    return pages, time.perf_counter() - t0


SUPPLEMENT_TITLE = "[خطوط تکمیلی از ناحیه جدول]"
COVER_MIN_TOKEN = 2
COVER_RATIO = 0.6
FUZZY_MIN_LEN = 4
FUZZY_RATIO = 0.8
CONFLICT_MIN_DIGITS = 3
NUMBER = re.compile(r"\d[\d,٬،./]*")


def _line_y(line: Line) -> float:
    return (line.box[1] + line.box[3]) / 2


def _cell_of(line: Line, tables: list[Table], margin: float = 8.0) -> Cell | None:
    cx, cy = (line.box[0] + line.box[2]) / 2, _line_y(line)
    for table in tables:
        for row in table.rows:
            for c in row:
                if c.text and c.box[0] - margin <= cx <= c.box[2] + margin and c.box[1] - margin <= cy <= c.box[3] + margin:
                    return c
    return None


def _token_covered(token: str, cell: str, cell_tokens: list[str]) -> bool:
    if token in cell:
        return True
    return len(token) >= FUZZY_MIN_LEN and any(abs(len(c) - len(token)) <= 2 and SequenceMatcher(None, token, c).ratio() >= FUZZY_RATIO for c in cell_tokens)


def _covered(text: str, cell_text: str) -> bool:
    cell = normalize_digits(normalize(cell_text))
    cell_tokens = cell.split()
    tokens = [t for t in normalize_digits(normalize(text)).split() if len(t) >= COVER_MIN_TOKEN]
    return not tokens or sum(_token_covered(t, cell, cell_tokens) for t in tokens) / len(tokens) >= COVER_RATIO


def _digit_strings(text: str) -> list[str]:
    found = (re.sub(r"\D", "", m) for m in NUMBER.findall(normalize_digits(normalize(text))))
    return [d for d in found if len(d) >= CONFLICT_MIN_DIGITS]


def _reading_conflicts(line: Line, cell: Cell) -> list[dict]:
    cell_numbers = _digit_strings(cell.text)
    out = []
    for digits in _digit_strings(line.text):
        if digits in cell_numbers:
            continue
        near = [(SequenceMatcher(None, digits, c).ratio(), c) for c in cell_numbers if abs(len(c) - len(digits)) <= 1]
        ratio, other = max(near, default=(0.0, ""))
        if ratio >= FUZZY_RATIO:
            out.append({
                "kind": "reading_conflict",
                "input": other,
                "output": other,
                "status": "ambiguous_review",
                "candidates": [digits],
                "note": "cell_vs_line",
                "context": line.text,
                "cell_conf": round(float(cell.conf), 3),
                "line_conf": round(float(line.conf), 3),
            })
    return out


def _row_y(row: list[Cell]) -> float:
    return sum((c.box[1] + c.box[3]) / 2 for c in row) / len(row)


def _compose_text(lines: list[Line], tables: list[Table], config: PipelineConfig) -> tuple[str, list[dict]]:
    def clean(items: list[Line]) -> str:
        text = "\n".join(l.text for l in items)
        return postprocess_text(text, use_lexicon=config.use_lexicon)["text"] if config.engineered else text

    rows = sorted(((_row_y(r), md) for t in tables for r in t.rows if r and (md := row_to_markdown(r))), key=lambda x: x[0])
    parts: list[str] = []
    run: list[Line] = []
    extras: list[Line] = []
    conflicts: dict[tuple[str, str], dict] = {}
    nxt = 0

    def flush() -> None:
        if run:
            parts.append(clean(run))
            run.clear()

    for line in lines:
        cell = _cell_of(line, tables)
        if cell is not None:
            for conflict in _reading_conflicts(line, cell):
                conflicts.setdefault((conflict["input"], conflict["candidates"][0]), conflict)
            if not _covered(line.text, cell.text) and float(line.conf) >= config.low_conf:
                extras.append(line)
            continue
        while nxt < len(rows) and rows[nxt][0] <= _line_y(line):
            flush()
            parts.append(rows[nxt][1])
            nxt += 1
        run.append(line)
    flush()
    parts.extend(md for _, md in rows[nxt:])
    if extras:
        parts += [SUPPLEMENT_TITLE, clean(extras)]
    return "\n".join(p for p in parts if p), list(conflicts.values())


def _build_page(idx: int, page: PageOcr, config: PipelineConfig) -> dict:
    lines = [l for l in page.lines if l.text.strip()]
    tables_md = [table_to_markdown(t) for t in page.tables]
    raw = "\n".join(l.text for l in lines)

    invoice = next((inv for inv in (parse_invoice(t, page_text=raw) for t in page.tables) if inv), None)
    if config.engineered:
        post = postprocess_text(raw, use_lexicon=config.use_lexicon)
    else:
        post = {"text": raw, "corrections": [], "review_queue": []}

    text_dedup, conflicts = _compose_text(lines, page.tables, config)
    return {
        "page": idx + 1,
        "raw_text": raw,
        "text": post["text"],
        "text_dedup": text_dedup,
        "corrections": post["corrections"],
        "review_queue": post["review_queue"] + conflicts,
        "low_confidence_lines": [
            {"text": l.text, "conf": round(float(l.conf), 3), "box": [round(float(v), 1) for v in l.box]}
            for l in lines
            if float(l.conf) < config.low_conf
        ],
        "tables_markdown": tables_md,
        "invoice": invoice,
    }


def process_document(engine: OcrEngine, path: str | Path, config: PipelineConfig | None = None, on_page: PageHook | None = None) -> dict:
    config = config or PipelineConfig()
    pages_ocr, elapsed = ocr_document(engine, path, config, on_page)
    pages = [_build_page(i, p, config) for i, p in enumerate(pages_ocr)]
    reconcile_document([p["invoice"] for p in pages if p["invoice"]])
    return {"file": Path(path).name, "time_sec": round(elapsed, 2), "pages": pages}
