from __future__ import annotations

import cv2
import numpy as np

from persian_ocr.config import PreprocessMode


SHARP_AMOUNT = 0.15
BRIDGE_STRENGTH = 0.25
LIGHT_STRENGTH = 0.15


def sharpen(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.addWeighted(gray, 1 + SHARP_AMOUNT, blurred, -SHARP_AMOUNT, 0)


def connect_strokes(gray: np.ndarray) -> np.ndarray:
    inverted = 255 - gray
    structure = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    joined = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, structure)
    return cv2.addWeighted(gray, 1 - BRIDGE_STRENGTH, 255 - joined, BRIDGE_STRENGTH, 0)


def flatten_lighting(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    scale = min(1.0, 1200 / max(height, width))
    small = cv2.resize(gray, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    background = cv2.GaussianBlur(small, (0, 0), 18)
    background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(gray, np.maximum(background, 16), scale=255)


def apply_preprocessing(gray: np.ndarray, mode: PreprocessMode | str) -> np.ndarray:
    selected = PreprocessMode(mode)
    if selected is PreprocessMode.original:
        return gray
    sharp = sharpen(gray)
    if selected is PreprocessMode.sharpen:
        return sharp
    if selected is PreprocessMode.sharpen_light:
        return cv2.addWeighted(sharp, 1 - LIGHT_STRENGTH, flatten_lighting(sharp), LIGHT_STRENGTH, 0)
    connected = connect_strokes(sharp)
    if selected is PreprocessMode.connect:
        return connected
    return cv2.addWeighted(connected, 1 - LIGHT_STRENGTH, flatten_lighting(connected), LIGHT_STRENGTH, 0)
