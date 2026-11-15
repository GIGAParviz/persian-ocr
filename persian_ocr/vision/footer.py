from __future__ import annotations

import numpy as np
from indra_ocr.pipeline import Line, OrtOCR
from indra_ocr.rtl import flip


def recover_footer_segments(ort: OrtOCR, gray: np.ndarray) -> list[Line]:
    H, W = gray.shape
    band_y0 = int(H * 0.90)
    boxes = ort.detect(gray[band_y0:, :])
    recovered: list[Line] = []

    for b in boxes:
        bx0, by0, bx1, by1 = [int(v) for v in b[:4]]
        bw = bx1 - bx0
        if bw < W * 0.35:
            continue
        abs_y0, abs_y1 = band_y0 + by0, band_y0 + by1
        step = max(120, bw // 6)
        segments = []
        for sx0 in range(bx0, bx1 - 80, step // 2):
            sx1 = min(bx1, sx0 + step)
            top = max(0, abs_y0 - 6)
            sub = gray[top:min(H, abs_y1 + 6), sx0:sx1]
            if not sub.size:
                continue
            ys = np.where((sub < 210).mean(axis=1) > 0.02)[0]
            if len(ys) < 4:
                continue
            ty0, ty1 = top + int(ys[0]), top + int(ys[-1]) + 1
            if not (14 <= (ty1 - ty0) <= 36):
                continue
            rec = ort.recognize(gray, np.array([[sx0, ty0, sx1, ty1, 1.0]], dtype=np.float32))[0]
            text = flip(rec[0]).strip()
            if text and rec[1] >= 0.48:
                segments.append(text)
        if segments:
            recovered.append(Line(box=[float(bx0), float(abs_y0), float(bx1), float(abs_y1)], text=" | ".join(segments), conf=0.82))
    return recovered
