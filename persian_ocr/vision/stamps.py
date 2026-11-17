from __future__ import annotations

import cv2
import numpy as np
from indra_ocr.pipeline import Line, OrtOCR
from indra_ocr.rtl import flip


def _read_strip(ort: OrtOCR, strip: np.ndarray) -> list[str]:
    sh, sw = strip.shape
    win = int(sw * 0.22)
    step = max(70, win // 4)
    best_text = ("", 0.0)
    best_digits = ("", 0)
    for sx0 in range(int(sw * 0.15), int(sw * 0.85) - win, step):
        res = ort.recognize(strip, np.array([[sx0, 2, sx0 + win, sh - 2, 1.0]], dtype=np.float32))[0]
        text = flip(res[0]).strip()
        if res[1] > best_text[1] and len(text) >= 8:
            best_text = (text, float(res[1]))
        if res[1] >= 0.48:
            n_digits = sum(ch.isdigit() or ("۰" <= ch <= "۹") for ch in text)
            if n_digits > best_digits[1] and n_digits >= 3:
                best_digits = (text, n_digits)
    parts = []
    if best_text[1] >= 0.52:
        parts.append(best_text[0])
    if best_digits[0] and best_digits[0] != best_text[0]:
        parts.append(best_digits[0])
    return parts


def unwrap_circular_stamps(ort: OrtOCR, gray: np.ndarray) -> list[Line]:
    H, W = gray.shape
    roi_y0 = int(H * 0.35)
    roi = gray[roi_y0:, :]
    scale = min(1.0, (2_000_000 / roi.size) ** 0.5)
    sample = cv2.resize(roi, (round(roi.shape[1] * scale), round(roi.shape[0] * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else roi
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(sample, (5, 5), 0),
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=250 * scale,
        param1=100,
        param2=48,
        minRadius=max(1, round(130 * scale)),
        maxRadius=max(1, round(230 * scale)),
    )
    if circles is None:
        return []

    stamp_lines: list[Line] = []
    for c in circles[0][:2]:
        cx, cy, r = (float(v) / scale for v in c)
        x_min, x_max = max(0, int(cx - r * 1.05)), min(W, int(cx + r * 1.05))
        y_min, y_max = max(0, int(cy - r * 1.05)), min(roi.shape[0], int(cy + r * 1.05))
        patch = roi[y_min:y_max, x_min:x_max]
        if patch.size == 0 or (patch < 180).mean() < 0.05:
            continue

        polar = cv2.warpPolar(
            patch,
            (int(r), int(2 * np.pi * r * 0.95)),
            (cx - x_min, cy - y_min),
            r,
            cv2.WARP_POLAR_LINEAR + cv2.INTER_CUBIC,
        )
        ring = np.vstack([polar, polar])[:, int(r * 0.70):int(r * 0.91)]
        parts: list[str] = []
        for strip in (cv2.rotate(ring, cv2.ROTATE_90_COUNTERCLOCKWISE), cv2.rotate(ring, cv2.ROTATE_90_CLOCKWISE)):
            parts.extend(_read_strip(ort, strip))

        if parts:
            abs_y = roi_y0 + cy
            stamp_lines.append(
                Line(
                    box=[float(x_min), float(abs_y - r), float(x_max), float(abs_y + r)],
                    text=" [مهر دایره‌ای: " + " | ".join(parts) + "]",
                    conf=0.78,
                )
            )
    return stamp_lines
