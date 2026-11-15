from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from persian_ocr.config import CACHE_DIR, PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.pipeline import ocr_document, process_document

from .cache import source_signature

MODES = ("single_page", "tiled", "engineered")
CACHE = CACHE_DIR / "hyps"


def flat_text(pages) -> str:
    return "\n".join(l.text for p in pages for l in p.lines)


def collect(loader: Callable[[], OcrEngine], pdf: Path, refresh: bool = False) -> dict:
    cache = CACHE / f"{pdf.stem}.json"
    signature = source_signature(pdf)
    if cache.exists() and not refresh:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("signature") == signature:
            return saved

    engine = loader()
    out: dict = {"signature": signature}
    pages, _ = ocr_document(engine, pdf, PipelineConfig.baseline(tiling=False))
    out["single_page"] = flat_text(pages)
    pages, _ = ocr_document(engine, pdf, PipelineConfig.baseline(tiling=True))
    out["tiled"] = flat_text(pages)

    t0 = time.perf_counter()
    result = process_document(engine, pdf, PipelineConfig(use_lexicon=False))
    out["engineered"] = "\n".join(p["text_dedup"] for p in result["pages"])
    out["engineered_time"] = round(time.perf_counter() - t0, 2)
    out["pages"] = len(result["pages"])
    out["invoice_checks"] = [p["invoice"]["check_summary"] for p in result["pages"] if p.get("invoice")]

    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
