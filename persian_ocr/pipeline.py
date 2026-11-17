from __future__ import annotations

import re
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from indra_ocr.pipeline import Line
from indra_ocr.rec_preproc import is_dark_line
from indra_ocr.rtl import flip

from .config import PipelineConfig, PreprocessMode
from .engine import OcrEngine
from .invoice import parse_invoice, reconcile_document
from .orientation import robust_upright
from .pdfio import iter_gray_pages
from .tables import Cell, Table, extract_tables, row_to_markdown, table_to_markdown
from .text import normalize, normalize_digits, postprocess_text
from .tiling import merge_lines, merge_tiles, tile_bounds
from .vision import recover_footer_segments, unwrap_circular_stamps, watermark_suppress
from .vision.payable import recover_faint_payable
from .vision.preprocess import apply_preprocessing


@dataclass
class PageOcr:
    lines: list[Line]
    tables: list[Table] = field(default_factory=list)
    review_queue: list[dict] = field(default_factory=list)


AMOUNT_RE = re.compile(r"\d{1,3}(?:[,٬،]\d{3}){2,}")


def _repair_dark_amount(engine: OcrEngine, gray: np.ndarray, line: Line) -> Line:
    amount = AMOUNT_RE.search(normalize_digits(line.text))
    if amount is None or amount.group().count("5") < 2 or not is_dark_line(gray, line.box):
        return line
    result = engine.ort.recognize(gray, np.array([[*line.box, 1.0]], dtype=np.float32))[0]
    chars = [(normalize_digits(ch), float(x)) for ch, x in result[2] if isinstance(ch, str) and len(ch) == 1 and (ch.isdigit() or ch in ",٬،")]
    token_text = "".join(ch for ch, _ in chars)
    token_amount = AMOUNT_RE.search(token_text)
    if token_amount is None or token_amount.group() != amount.group():
        return line
    x0, y0, x1, y1 = (int(v) for v in line.box)
    height = y1 - y0
    mask = (gray[y0:y1, x0:x1] > 165).astype(np.uint8)
    if not mask.size:
        return line
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components = [(x0 + x, x0 + x + w, h) for x, _, w, h, area in stats[1:] if 8 <= w < height * 0.9 and 8 <= h < height * 0.95 and area > height * height * 0.003]

    def glyph_height(x: float) -> int:
        return max((h for left, right, h in components if left <= x <= right), default=0)

    segment = chars[token_amount.start():token_amount.end()]
    tall = max((glyph_height(x) for ch, x in segment if ch.isdigit() and ch != "5"), default=0)
    if tall < height * 0.5:
        return line
    corrected = ["0" if ch == "5" and 0 < glyph_height(x) < tall * 0.72 else ch for ch, x in segment]
    if sum(a != b for (a, _), b in zip(segment, corrected)) < 2:
        return line
    text = line.text[:amount.start()] + "".join(corrected) + line.text[amount.end():]
    text = re.sub(r"ميلغ", "مبلغ", text)
    text = re.sub(r"ر\s*[يی]ال", " ریال", text)
    return Line(box=list(line.box), text=text, conf=min(float(line.conf), 0.74))


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
    gray = apply_preprocessing(gray, config.preprocess)
    with engine.force_rtl() if config.engineered else nullcontext():
        if config.engineered:
            gray, _, _, _ = robust_upright(engine.ort, gray)
        lines = _recognize_lines(engine, gray, config)
        recovery_review = []
        if config.engineered:
            lines = [_repair_dark_amount(engine, gray, line) for line in lines]
            lines = _recover_payable(engine, gray, lines)
            lines, recovery_review = recover_faint_payable(engine, gray, lines)
        tables = extract_tables(engine.ort, gray) if config.engineered and config.tables else []
    review_queue = list(recovery_review)
    for line in lines:
        if not line.text.startswith("قابل پرداخت:") or float(line.conf) < 0.85:
            continue
        cell = _cell_of(line, tables)
        if cell is None or not normalize(cell.text).startswith("قابل پرداخت:") or float(cell.conf) >= float(line.conf):
            continue
        review_queue.extend(_reading_conflicts(line, cell))
        cell.text = line.text
        cell.conf = float(line.conf)
    page = PageOcr(lines=lines, tables=tables, review_queue=review_queue)
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


def _recover_payable(engine: OcrEngine, gray: np.ndarray, lines: list[Line]) -> list[Line]:
    height, width = gray.shape
    for label in lines:
        if "پردا" not in label.text or label.box[1] < height * 0.5:
            continue
        label_height = label.box[3] - label.box[1]
        row = [line for line in lines if abs(_line_y(line) - _line_y(label)) < label_height * 0.7]
        numbers = [line for line in row if line.box[2] < label.box[0] and 2 <= sum(ch.isdigit() for ch in line.text) <= 4]
        if not numbers:
            continue
        number = max(numbers, key=lambda line: line.box[0])
        number_width = number.box[2] - number.box[0]
        number_height = number.box[3] - number.box[1]
        label_box = [max(0, label.box[0] - width * 0.12), max(0, label.box[1] - label_height * 0.15), min(width, label.box[2] + width * 0.05), min(height, label.box[3] + label_height * 0.15), 1.0]
        number_box = [max(0, number.box[0] - number_width * 0.1), number.box[1] + number_height * 0.28, min(width, label.box[0] - width * 0.2, number.box[0] + width * 0.25), min(height, number.box[3] + number_height * 0.2), 1.0]
        number_box = [round(number_box[0]), round(number_box[1]), int(np.ceil(number_box[2])), int(np.ceil(number_box[3])), 1.0]
        if number_box[2] <= number_box[0] or number_box[3] <= number_box[1]:
            continue
        unit = max((line for line in row if line.box[2] < number.box[0] and not any(ch.isdigit() for ch in line.text)), key=lambda line: line.box[2], default=None)
        boxes = [label_box, number_box]
        if unit is not None:
            unit_width = unit.box[2] - unit.box[0]
            unit_height = unit.box[3] - unit.box[1]
            boxes.append([max(0, unit.box[0] - unit_width * 1.2), unit.box[1] + unit_height * 0.14, min(width, unit.box[2] + unit_width * 1.3), unit.box[3] - unit_height * 0.02, 1.0])
        readings = [engine.ort.recognize(gray, np.array([box], dtype=np.float32))[0] for box in boxes]
        label_text = normalize(flip(readings[0][0])).strip()
        number_text = normalize_digits(flip(readings[1][0])).strip()
        if label_text.rstrip(":") != "قابل پرداخت" or readings[0][1] < 0.85 or readings[1][1] < 0.85 or not re.fullmatch(r"[\d,٬،\s]+", number_text):
            continue
        digits = re.sub(r"\D", "", number_text)
        if not 5 <= len(digits) <= 12:
            continue
        currency = " ریال" if unit is not None and readings[2][1] >= 0.7 and normalize(flip(readings[2][0])) == "ریال" else ""
        text = f"قابل پرداخت: {int(digits):,}{currency}"
        removed = {id(line) for line in row}
        recovered = [line for line in lines if id(line) not in removed]
        confidence = min(float(reading[1]) for reading in readings[:3 if currency else 2])
        recovered.append(Line(box=[min(line.box[0] for line in row), min(line.box[1] for line in row), max(line.box[2] for line in row), max(line.box[3] for line in row)], text=text, conf=confidence))
        recovered.sort(key=lambda line: (round(line.box[1] / 30) * 30, -line.box[0]))
        return recovered
    return lines


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
        "review_queue": post["review_queue"] + page.review_queue + conflicts,
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
    return {"file": Path(path).name, "time_sec": round(elapsed, 2), "preprocess": PreprocessMode(config.preprocess).value, "pages": pages}
