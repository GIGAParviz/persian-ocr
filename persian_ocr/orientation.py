from __future__ import annotations

import cv2
import numpy as np
from indra_ocr.pipeline import OrtOCR


def orientation_score(ort: OrtOCR, gray: np.ndarray) -> float:
    small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    boxes = ort.detect(small)
    if not len(boxes):
        return 0.0
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]
    horizontal = w > 2 * h
    idx = [i for i in np.argsort(-w) if horizontal[i]][:12]
    if not idx:
        return 0.0
    recs = ort.recognize(small, boxes[idx])
    return float(horizontal.mean()) * float(np.mean([r[1] for r in recs]))


def robust_upright(ort: OrtOCR, gray: np.ndarray) -> tuple[np.ndarray, int, float, list[float]]:
    scores = [orientation_score(ort, np.ascontiguousarray(np.rot90(gray, k))) for k in range(4)]
    k = int(np.argmax(scores))
    rotated = np.ascontiguousarray(np.rot90(gray, k))
    straightened, _, skew = ort.upright(rotated, turn=False)
    return straightened, k, skew, scores
