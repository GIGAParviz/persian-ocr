from __future__ import annotations

import cv2
import numpy as np


def watermark_suppress(gray: np.ndarray, threshold: int = 135) -> np.ndarray:
    clean = gray.copy()
    clean[clean > threshold] = 255
    return cv2.GaussianBlur(clean, (3, 3), 0)
