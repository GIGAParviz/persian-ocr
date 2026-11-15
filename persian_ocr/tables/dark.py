from __future__ import annotations

import cv2
import numpy as np
from indra_ocr.pipeline import OrtOCR
from indra_ocr.rtl import flip

from .models import BBox

DARK_CELL_MEDIAN = 150


def _variants(reg: np.ndarray) -> list[np.ndarray]:
    sm = cv2.medianBlur(reg, 3)
    med = float(np.median(sm))
    lo = float(np.percentile(sm, 2))
    dark_text = np.clip((sm.astype(np.float32) - lo) * 255.0 / max(8.0, med * 0.85 - lo), 0, 255).astype(np.uint8)
    hi = float(np.percentile(sm, 98))
    light_text = np.clip((hi - sm.astype(np.float32)) * 255.0 / max(8.0, hi - med * 1.15), 0, 255).astype(np.uint8)
    return [dark_text, light_text]


def _line_boxes_by_projection(img: np.ndarray, min_h: int = 12, max_h: int = 90) -> list[BBox]:
    ink = img < 128
    rows = ink.mean(axis=1) > 0.01
    boxes, y = [], 0
    H = img.shape[0]
    while y < H:
        if rows[y]:
            y0 = y
            while y < H and (rows[y] or (y + 6 < H and rows[y:y + 6].any())):
                y += 1
            if min_h <= y - y0 <= max_h:
                cols = np.where(ink[y0:y].mean(axis=0) > 0.02)[0]
                if len(cols) > 4:
                    boxes.append((int(cols[0]), y0, int(cols[-1]) + 1, y))
        y += 1
    return boxes


def read_dark_cell(ort: OrtOCR, region: np.ndarray) -> tuple[str, float]:
    best = ("", 0.0)
    for variant in _variants(region):
        variant = cv2.copyMakeBorder(variant, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        boxes = _line_boxes_by_projection(variant)
        if not boxes:
            continue
        recs = ort.recognize(variant, np.array([[*b, 1.0] for b in boxes], dtype=np.float32))
        texts = [flip(r[0]).strip() for r in recs]
        confs = [r[1] for r in recs if r[0].strip()]
        if confs and float(np.mean(confs)) > best[1]:
            best = (" ".join(t for t in texts if t), float(np.mean(confs)))
    return best


def blank_dark_cells(gray: np.ndarray, cells: list[BBox], pad: int = 5) -> tuple[np.ndarray, set[int]]:
    out, dark = gray.copy(), set()
    for ci, (x0, y0, x1, y1) in enumerate(cells):
        reg = gray[y0 + pad:y1 - pad, x0 + pad:x1 - pad]
        if reg.size and float(np.median(reg)) < DARK_CELL_MEDIAN:
            out[y0 + pad:y1 - pad, x0 + pad:x1 - pad] = 255
            dark.add(ci)
    return out, dark
