from __future__ import annotations

import os
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent

MODEL_DIR = Path(os.environ.get("PERSIAN_OCR_MODEL_DIR", ROOT / "indra-ocr"))
CACHE_DIR = ROOT / ".cache"
TMP_DIR = CACHE_DIR / "tmp"
OUTPUT_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"
EVAL_DATA_DIR = ROOT / "eval_data"
LEXICON_PATH = PACKAGE_DIR / "data" / "domain_lexicon.json"
FONT_PATH = PACKAGE_DIR / "data" / "Vazirmatn-Regular.ttf"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def setup_environment() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(TMP_DIR)
    os.environ["TMP"] = str(TMP_DIR)
    os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
    os.environ["INDRA_OCR_MODEL_DIR"] = str(MODEL_DIR)


class PreprocessMode(str, Enum):
    original = "original"
    sharpen = "sharpen"
    sharpen_light = "sharpen_light"
    connect = "connect"
    soft_light = "soft_light"


@dataclass(frozen=True)
class PipelineConfig:
    dpi: float = 300.0
    tiling: bool = True
    overlap_ratio: float = 0.18
    engineered: bool = True
    tables: bool = True
    header_fraction: float = 0.30
    low_conf: float = 0.75
    use_lexicon: bool = True
    preprocess: PreprocessMode = PreprocessMode.original
    max_pages: int = 0

    @classmethod
    def baseline(cls, tiling: bool, **kwargs) -> "PipelineConfig":
        return cls(tiling=tiling, engineered=False, tables=False, use_lexicon=False, **kwargs)
