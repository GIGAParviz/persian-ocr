from __future__ import annotations

from persian_ocr.text import normalize


def _box(values, width: int, height: int) -> list[int] | None:
    x0 = max(0, min(width, round(float(values[0]))))
    y0 = max(0, min(height, round(float(values[1]))))
    x1 = max(0, min(width, round(float(values[2]))))
    y1 = max(0, min(height, round(float(values[3]))))
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def build_layout(size: tuple[int, int], page, final_text: str) -> dict:
    width, height = size
    lines = [line for line in page.lines if line.text.strip()]
    final_lines = final_text.splitlines()
    line_texts = final_lines if len(final_lines) == len(lines) else [normalize(line.text) for line in lines]
    cells = []
    tables = []
    for table in page.tables:
        table_box = _box(table.box, width, height)
        if table_box is not None:
            tables.append(table_box)
        for row in table.rows:
            for cell in row:
                cell_box = _box(cell.box, width, height)
                if cell_box is not None:
                    cells.append({"box": cell_box, "text": cell.text.strip(), "conf": round(float(cell.conf), 3)})
    filled = [cell for cell in cells if cell["text"]]
    items = [{"box": cell["box"], "text": cell["text"], "conf": cell["conf"], "source": "cell"} for cell in filled]
    for line, text in zip(lines, line_texts):
        box = _box(line.box, width, height)
        if box is None or not text.strip():
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if any(cell["box"][0] <= cx <= cell["box"][2] and cell["box"][1] <= cy <= cell["box"][3] for cell in filled):
            continue
        items.append({"box": box, "text": text.strip(), "conf": round(float(line.conf), 3), "source": "line"})
    items.sort(key=lambda item: (round(item["box"][1] / 25), -item["box"][2]))
    return {"size": [width, height], "items": items, "cells": [cell["box"] for cell in cells], "tables": tables}
