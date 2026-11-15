from __future__ import annotations

import numpy as np

from .models import BBox


def _tight_y(gray: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int]:
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0:
        return y0, y1
    ys = np.where((sub < 200).mean(axis=1) > 0.01)[0]
    if len(ys) < 3:
        return y0, y1
    return y0 + int(ys[0]), y0 + int(ys[-1]) + 1


def assign_lines_to_cells(gray: np.ndarray, page_boxes: np.ndarray, cells: list[BBox], pad: int = 6) -> list[list[BBox]]:
    per_cell: list[list[BBox]] = []
    for cx0, cy0, cx1, cy1 in cells:
        ix0, iy0, ix1, iy1 = cx0 + pad, cy0 + pad // 2, cx1 - pad, cy1 - pad // 2
        mine = []
        for b in page_boxes:
            bx0, by0, bx1, by1 = (float(v) for v in b[:4])
            if not (cy0 <= (by0 + by1) / 2 <= cy1):
                continue
            x0, x1 = int(max(bx0, ix0)), int(min(bx1, ix1))
            if x1 - x0 < 12:
                continue
            y0, y1 = int(max(by0 - 3, iy0)), int(min(by1 + 3, iy1))
            if y1 - y0 < 8:
                continue
            ty0, ty1 = _tight_y(gray, x0, y0, x1, y1)
            mine.append((x0, ty0, x1, ty1))
        if not mine:
            mine = _ink_fallback(gray, ix0, iy0, ix1, iy1)
        per_cell.append(mine)
    return per_cell


def _ink_fallback(gray: np.ndarray, ix0: int, iy0: int, ix1: int, iy1: int) -> list[BBox]:
    sub = gray[iy0:iy1, ix0:ix1]
    if not sub.size:
        return []
    ink = np.where(sub < 150)
    if len(ink[0]) <= 15:
        return []
    y0, y1 = iy0 + int(ink[0].min()), iy0 + int(ink[0].max()) + 1
    x0, x1 = ix0 + int(ink[1].min()), ix0 + int(ink[1].max()) + 1
    if not 10 <= (y1 - y0) <= 70:
        return []
    cx = (x0 + x1) // 2
    half = max((x1 - x0) // 2 + 8, 14)
    return [(max(ix0, cx - half), y0, min(ix1, cx + half), y1)]
