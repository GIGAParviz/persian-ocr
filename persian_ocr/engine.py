from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import indra_ocr.pipeline as indra_pipeline
import indra_ocr.rec_preproc as rec_preproc
import numpy as np
from indra_ocr.document import Converter
from indra_ocr.models import model_dir
from indra_ocr.pipeline import OrtOCR

from .config import MODEL_DIR

MIN_REC_WIDTH = 32
_indra_pad_batch = rec_preproc.pad_batch


def pad_batch_min_width(lines: list[np.ndarray], multiple: int = rec_preproc.WIDTH_MULTIPLE) -> tuple[np.ndarray, np.ndarray]:
    arr, widths = _indra_pad_batch(lines, multiple)
    if arr.shape[3] < MIN_REC_WIDTH:
        arr = np.pad(arr, ((0, 0), (0, 0), (0, 0), (0, MIN_REC_WIDTH - arr.shape[3])))
    return arr, widths


rec_preproc.pad_batch = indra_pipeline.pad_batch = pad_batch_min_width


@dataclass
class OcrEngine:
    ort: OrtOCR
    conv: Converter

    @classmethod
    def load(cls, threads: int = 4, dpi: float = 300.0) -> "OcrEngine":
        ort = OrtOCR(
            onnx_dir=model_dir(str(MODEL_DIR), math=False),
            threads=threads,
            adaptive=True,
            table_heads=False,
            furniture=True,
            math=False,
            providers=["CPUExecutionProvider"],
        )
        return cls(ort=ort, conv=Converter(ort, dpi=dpi, mode="ocr", image_ocr=True))

    @contextmanager
    def force_rtl(self) -> Iterator[None]:
        original = self.ort.line_groups
        self.ort.line_groups = lambda crops, batch=64: (["rtl"] * len(crops), [True] * len(crops))
        try:
            yield
        finally:
            self.ort.line_groups = original
