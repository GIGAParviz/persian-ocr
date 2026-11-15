from __future__ import annotations

import json
import re
import time
from pathlib import Path

from persian_ocr.config import EVAL_DATA_DIR, PipelineConfig, REPORTS_DIR, ROOT
from persian_ocr.engine import OcrEngine
from persian_ocr.pipeline import ocr_document, process_document
from persian_ocr.text import normalize, normalize_digits, postprocess_text

from .hypotheses import flat_text

GROUND_TRUTH_DIR = Path(__file__).resolve().parent / "ground_truth"
SEARCH_DIRS = (ROOT / "files", EVAL_DATA_DIR)
MODES = ("single_page", "tiled", "engineered", "engineered+lexicon")


_COMPACT = re.compile(r"[ \t,\u060c/\\\u066b\u066c.:-]")


def _contains(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    left = r"(?<!\d)" if needle[0].isdigit() else ""
    right = r"(?!\d)" if needle[-1].isdigit() else ""
    return re.search(left + re.escape(needle) + right, haystack) is not None


def evaluate_fields(fields: list[dict], hyp_text: str) -> dict:
    hyp_lines = [normalize_digits(normalize(line)) for line in hyp_text.splitlines()]
    compact_lines = [_COMPACT.sub("", line) for line in hyp_lines]
    details = []
    for f in fields:
        value = normalize_digits(normalize(str(f["value"])))
        exact = any(_contains(line, value) for line in hyp_lines)
        ok = exact or any(_contains(line, _COMPACT.sub("", value)) for line in compact_lines)
        details.append({"name": f["name"], "expected": value, "matched": ok, "match_type": "exact" if exact else ("normalized" if ok else "missed")})
    matched = sum(d["matched"] for d in details)
    return {"total": len(fields), "matched": matched, "accuracy": matched / len(fields) if fields else None, "details": details}


def _find_pdf(name: str) -> Path | None:
    return next((d / name for d in SEARCH_DIRS if (d / name).exists()), None)


def run() -> Path:
    engine = OcrEngine.load()
    rows, missed = [], []
    for gt_path in sorted(GROUND_TRUTH_DIR.glob("*.json")):
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        pdf = _find_pdf(gt["file"])
        if pdf is None:
            print(f"پیدا نشد: {gt['file']}")
            continue
        single, _ = ocr_document(engine, pdf, PipelineConfig.baseline(tiling=False))
        tiled, _ = ocr_document(engine, pdf, PipelineConfig.baseline(tiling=True))
        result = process_document(engine, pdf, PipelineConfig(use_lexicon=False))
        raw = "\n".join(p["raw_text"] for p in result["pages"])
        texts = {
            "single_page": flat_text(single),
            "tiled": flat_text(tiled),
            "engineered": "\n".join(p["text"] for p in result["pages"]),
            "engineered+lexicon": postprocess_text(raw, use_lexicon=True)["text"],
        }
        scores = {m: evaluate_fields(gt["fields"], texts[m]) for m in MODES}
        rows.append((gt["file"], len(gt["fields"]), scores))
        missed += [f"- {gt['file']}: {d['name']} (انتظار: `{d['expected']}`)" for d in scores["engineered"]["details"] if not d["matched"]]
        print(gt["file"], " | ".join(f"{m} {scores[m]['matched']}/{scores[m]['total']}" for m in MODES))

    lines = [
        "# ارزیابی در سطح فیلد (نامه‌ها)", "", f"اجرا: {time.strftime('%Y-%m-%d %H:%M')}", "",
        "| سند | فیلد | " + " | ".join(MODES) + " |", "|---|---|" + "---|" * len(MODES),
    ]
    for name, n, scores in rows:
        lines.append(f"| {name} | {n} | " + " | ".join(f"{scores[m]['matched']}/{n}" for m in MODES) + " |")
    lines += [
        "", "ستون **engineered** دقت واقعی OCR با قواعد است. **engineered+lexicon** از دیکشنری سازمان "
        "(`persian_ocr/data/domain_lexicon.json`) استفاده می‌کند و در ارزیابی عدد را بالا می‌برد.",
        "", "## فیلدهای از دست‌رفته در engineered", "", *(missed or ["- هیچ"]),
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "fields_report.md"
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return out
