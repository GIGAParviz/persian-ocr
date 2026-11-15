from __future__ import annotations

import cv2
import numpy as np

from .models import BBox


def _line_masks(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    H, W = gray.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, W // 35), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, H // 70)))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk, iterations=1)
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk, iterations=1)
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9)))
    return horiz, vert


def find_cells(gray: np.ndarray, min_w: int = 40, min_h: int = 28) -> list[BBox]:
    horiz, vert = _line_masks(gray)
    inv = cv2.bitwise_not(cv2.bitwise_or(horiz, vert))
    H, W = gray.shape
    n, _, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    cells = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < min_w or h < min_h:
            continue
        if w > W * 0.97 and h > H * 0.5:
            continue
        if area < 0.6 * w * h:
            continue
        cells.append((int(x), int(y), int(x + w), int(y + h)))
    return cells


def group_rows(cells: list[BBox]) -> list[list[BBox]]:
    cells = sorted(cells, key=lambda c: (c[1] + c[3]) / 2)
    rows: list[list[BBox]] = []
    for c in cells:
        cy, ch = (c[1] + c[3]) / 2, c[3] - c[1]
        if rows:
            last = rows[-1]
            ly = np.mean([(r[1] + r[3]) / 2 for r in last])
            lh = np.mean([r[3] - r[1] for r in last])
            if abs(cy - ly) < 0.5 * min(ch, lh):
                last.append(c)
                continue
        rows.append([c])
    return [sorted(r, key=lambda c: -c[2]) for r in rows]
