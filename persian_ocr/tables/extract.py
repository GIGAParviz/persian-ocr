from __future__ import annotations

import numpy as np
from indra_ocr.pipeline import OrtOCR
from indra_ocr.rtl import flip

from .cells import find_cells, group_rows
from .dark import blank_dark_cells, read_dark_cell
from .lines import assign_lines_to_cells
from .models import BBox, Cell, Table


def extract_tables(ort: OrtOCR, gray: np.ndarray, min_cells: int = 6) -> list[Table]:
    cells = find_cells(gray)
    if len(cells) < min_cells:
        return []
    original = gray
    gray, dark = blank_dark_cells(original, cells)
    per_cell = assign_lines_to_cells(gray, ort.detect(gray), cells)
    for ci in dark:
        per_cell[ci] = []

    flat = [(ci, b) for ci, boxes in enumerate(per_cell) for b in boxes]
    texts: dict[int, list[tuple[BBox, str, float]]] = {}
    if flat:
        arr = np.array([[b[0], b[1], b[2], b[3], 1.0] for _, b in flat], dtype=np.float32)
        for (ci, b), (text, conf, _) in zip(flat, ort.recognize(gray, arr)):
            text = flip(text).strip()
            if text:
                texts.setdefault(ci, []).append((b, text, float(conf)))

    for ci in dark:
        x0, y0, x1, y1 = cells[ci]
        text, conf = read_dark_cell(ort, original[y0 + 5:y1 - 5, x0 + 5:x1 - 5])
        if text:
            texts[ci] = [(cells[ci], text, conf)]

    cell_objs = {}
    for ci, box in enumerate(cells):
        parts = sorted(texts.get(ci, []), key=lambda p: (round(p[0][1] / 25), -p[0][2]))
        cell_objs[box] = Cell(
            box=box,
            text=" ".join(p[1] for p in parts),
            conf=float(np.mean([p[2] for p in parts])) if parts else 0.0,
        )

    table = Table(box=(min(c[0] for c in cells), min(c[1] for c in cells), max(c[2] for c in cells), max(c[3] for c in cells)))
    table.rows = [[cell_objs[b] for b in row] for row in group_rows(cells)]
    return [table]


def row_to_markdown(row: list[Cell]) -> str | None:
    texts = [c.text.replace("|", "/") for c in row if c.text]
    return "| " + " | ".join(texts) + " |" if texts else None


def table_to_markdown(table: Table) -> str:
    return "\n".join(md for md in map(row_to_markdown, table.rows) if md)
