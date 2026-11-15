from __future__ import annotations

import base64
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
import pypdfium2 as pdfium

from .config import IMAGE_SUFFIXES


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _read_image(path: Path, flags: int) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), flags)
    if img is None:
        raise ValueError(f"تصویر خوانده نشد: {path}")
    return img


def _to_gray(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 3 and arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY)
    if arr.ndim == 3:
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    return arr


def iter_gray_pages(path: str | Path, dpi: float = 300.0, max_pages: int = 0) -> Iterator[np.ndarray]:
    path = Path(path)
    if is_image(path):
        yield _read_image(path, cv2.IMREAD_GRAYSCALE)
        return
    with pdfium.PdfDocument(str(path)) as doc:
        n = len(doc) if not max_pages else min(len(doc), max_pages)
        for i in range(n):
            yield _to_gray(doc[i].render(scale=dpi / 72.0).to_numpy())


def load_gray_page(path: str | Path, page: int = 1, dpi: float = 300.0) -> np.ndarray:
    path = Path(path)
    if is_image(path):
        return _read_image(path, cv2.IMREAD_GRAYSCALE)
    with pdfium.PdfDocument(str(path)) as doc:
        if not 1 <= page <= len(doc):
            raise IndexError(f"صفحه {page} وجود ندارد (سند {len(doc)} صفحه دارد)")
        return _to_gray(doc[page - 1].render(scale=dpi / 72.0).to_numpy())


def preview_jpeg(path: str | Path, page_idx: int, dpi: float = 110.0, quality: int = 80) -> tuple[bytes, int, int]:
    path = Path(path)
    if is_image(path):
        arr = _read_image(path, cv2.IMREAD_COLOR)
    else:
        with pdfium.PdfDocument(str(path)) as doc:
            arr = doc[page_idx].render(scale=dpi / 72.0).to_numpy()
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    height, width = arr.shape[:2]
    return (buf.tobytes() if ok else b""), width, height


def preview_jpeg_b64(path: str | Path, page_idx: int, dpi: float = 110.0, quality: int = 80) -> str:
    data, _, _ = preview_jpeg(path, page_idx, dpi, quality)
    return base64.b64encode(data).decode("ascii") if data else ""
