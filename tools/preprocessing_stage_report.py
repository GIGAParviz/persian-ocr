from __future__ import annotations

import argparse
import base64
import difflib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from persian_ocr.config import PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.pdfio import load_gray_page
from persian_ocr.pipeline import process_document
from persian_ocr.text import normalize_digits
from tools.descreen_ab_report import descreen


sys.stdout.reconfigure(encoding="utf-8")
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
STAGES = [
    ("original", "تصویر اصلی"),
    ("descreen", "حذف هافتون با notch ثابت"),
    ("enhanced", "تیزکردن ملایم تصویر"),
    ("lighting", "یکنواخت‌سازی نور"),
    ("stamp", "کاهش ملایم مهر آبی بالا"),
    ("stamp_strong", "حذف قوی‌تر مهر آبی بالا"),
    ("combined", "ترکیب چهار پردازش"),
]


def load_color(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read {path}")
    return image


def enhance(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.addWeighted(gray, 1.15, blurred, -0.15, 0)


def flatten_lighting(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    scale = min(1.0, 1200 / max(height, width))
    small = cv2.resize(gray, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    background = cv2.GaussianBlur(small, (0, 0), 18)
    background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(gray, np.maximum(background, 16), scale=255)


def upper_blue_stamp_mask(color: np.ndarray) -> tuple[np.ndarray, float]:
    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 20]), np.array([140, 255, 255]))
    cut = round(mask.shape[0] * 0.48)
    mask[cut:] = 0
    coverage = float(np.count_nonzero(mask[:cut]) / max(1, mask[:cut].size))
    if coverage < 0.01:
        return np.zeros_like(mask), coverage
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return mask, coverage


def remove_stamp(gray: np.ndarray, mask: np.ndarray, radius: int = 3) -> np.ndarray:
    if not np.any(mask):
        return gray
    return cv2.inpaint(gray, mask, radius, cv2.INPAINT_TELEA)


def preview(array: np.ndarray, max_width: int = 680, max_height: int = 1050) -> str:
    height, width = array.shape[:2]
    scale = min(1.0, max_width / width, max_height / height)
    if scale < 1:
        array = cv2.resize(array, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    encoded = cv2.imencode(".jpg", array, [cv2.IMWRITE_JPEG_QUALITY, 84])[1]
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def focus_crop(array: np.ndarray) -> np.ndarray:
    height, width = array.shape[:2]
    if height > 5000:
        return array[round(height * 0.36):round(height * 0.76), round(width * 0.30):round(width * 0.92)]
    return array[:round(height * 0.50), :]


def long_numbers(text: str) -> Counter:
    pattern = re.compile(r"\d[\d,٬،]*")
    tokens = pattern.findall(normalize_digits(text))
    return Counter(token for token in tokens if len(re.sub(r"\D", "", token)) >= 5)


def make_variants(color: np.ndarray, gray: np.ndarray) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, float]:
    mask, coverage = upper_blue_stamp_mask(color)
    strong_mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) if np.any(mask) else mask
    screened = descreen(gray)
    variants = {
        "original": gray,
        "descreen": screened,
        "enhanced": enhance(gray),
        "lighting": flatten_lighting(gray),
        "stamp": remove_stamp(gray, mask),
        "stamp_strong": remove_stamp(gray, strong_mask, 7),
    }
    combined = remove_stamp(flatten_lighting(enhance(screened)), mask)
    variants["combined"] = combined
    return variants, mask, strong_mask, coverage


def compare_file(engine: OcrEngine, path: Path, output_dir: Path) -> tuple[dict, str]:
    color = load_color(path)
    gray = load_gray_page(path)
    variants, mask, strong_mask, coverage = make_variants(color, gray)
    folder = output_dir / path.stem
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "stamp_mask.png"), mask)
    cv2.imwrite(str(folder / "stamp_mask_strong.png"), strong_mask)
    results = {}
    for key, title in STAGES:
        image_path = folder / f"{key}.png"
        if not cv2.imwrite(str(image_path), variants[key]):
            raise RuntimeError(f"Could not write {image_path}")
        if key == "original":
            source = path
        else:
            source = image_path
        if key in {"stamp", "stamp_strong"} and not np.any(mask):
            result = results["original"]
        else:
            result = process_document(engine, source, PipelineConfig())
        results[key] = result
        (folder / f"{key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path.name, key, "lines", len(result["pages"][0]["raw_text"].splitlines()), "seconds", result["time_sec"], flush=True)
    baseline = results["original"]["pages"][0]["text_dedup"]
    baseline_numbers = long_numbers(baseline)
    cards = []
    summary = {"file": path.name, "size": [gray.shape[1], gray.shape[0]], "blue_coverage_top": round(coverage, 4), "stages": {}}
    for key, title in STAGES:
        image = variants[key]
        page = results[key]["pages"][0]
        output_text = page["text_dedup"]
        removed = list((baseline_numbers - long_numbers(output_text)).elements())
        added = list((long_numbers(output_text) - baseline_numbers).elements())
        summary["stages"][key] = {
            "raw_lines": len(page["raw_text"].splitlines()),
            "text_changed": output_text != baseline,
            "long_numbers_removed": removed,
            "long_numbers_added": added,
            "ocr_seconds": results[key]["time_sec"],
        }
        difference = "\n".join(difflib.unified_diff(baseline.splitlines(), output_text.splitlines(), fromfile="original", tofile=key, lineterm=""))
        note = "مهر آبی بالای تصویر شناسایی نشد؛ این مرحله تغییری نداد." if key in {"stamp", "stamp_strong"} and not np.any(mask) else ""
        cards.append(
            f'<section id="{html.escape(path.stem)}-{key}"><h3>{html.escape(title)}</h3>'
            f'<p>{html.escape(note)}</p>'
            f'<a href="{html.escape(path.stem)}/{key}.png"><img src="{preview(image)}" alt="{html.escape(title)}"></a>'
            f'<h4>برش بزرگ‌شده</h4><img src="{preview(focus_crop(image), 800, 850)}" alt="{html.escape(title)}">'
            f'<p>خطوط OCR: {summary["stages"][key]["raw_lines"]} · اعداد حذف‌شده: {html.escape(str(removed))} · اعداد اضافه‌شده: {html.escape(str(added))}</p>'
            f'<details><summary>متن نهایی OCR</summary><pre dir="auto">{html.escape(output_text)}</pre></details>'
            f'<details><summary>تفاوت متن با تصویر اصلی</summary><pre dir="auto">{html.escape(difference)}</pre></details>'
            f'<p><a href="{html.escape(path.stem)}/{key}.json">JSON خروجی مدل</a></p></section>'
        )
    scale = min(1.0, 680 / color.shape[1], 1050 / color.shape[0])
    mask_overlay = cv2.resize(color, (round(color.shape[1] * scale), round(color.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(mask, (mask_overlay.shape[1], mask_overlay.shape[0]), interpolation=cv2.INTER_NEAREST)
    mask_overlay[small_mask > 0] = (0, 0, 255)
    block = (
        f'<article id="{html.escape(path.stem)}"><h2>{html.escape(path.name)}</h2>'
        f'<p>{gray.shape[1]} × {gray.shape[0]} پیکسل · پوشش رنگ آبی در بالای عکس: {coverage:.2%}</p>'
        f'<div class="reference"><div><h3>تصویر رنگی ورودی</h3><img src="{preview(color)}"></div>'
        f'<div><h3>ماسک مهر، با رنگ قرمز</h3><img src="{preview(mask_overlay)}"></div></div>'
        f'<div class="cards">{"".join(cards)}</div></article>'
    )
    return summary, block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("file/test_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/preprocessing_comparison"))
    args = parser.parse_args()
    paths = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES)
    if not paths:
        raise SystemExit(f"No images in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = OcrEngine.load()
    summaries = []
    blocks = []
    for path in paths:
        summary, block = compare_file(engine, path, args.output_dir)
        summaries.append(summary)
        blocks.append(block)
    (args.output_dir / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    navigation = " ".join(f'<a href="#{html.escape(path.stem)}">{html.escape(path.name)}</a>' for path in paths)
    page = (
        '<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>مقایسهٔ چهار پردازش تصویر و OCR</title>'
        '<style>body{font:16px system-ui;max-width:1600px;margin:auto;padding:24px;background:#f3f5f8;color:#18212b}'
        'article{background:white;padding:20px;margin:28px 0;border-radius:14px;box-shadow:0 2px 12px #0001}'
        '.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}'
        '.reference{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:18px}'
        'section,.reference>div{border:1px solid #d7dde5;padding:14px;border-radius:9px;overflow:auto}'
        'img{display:block;max-width:100%;height:auto;margin:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}'
        'details{margin:9px 0}nav a{margin:0 8px}p{line-height:1.6}'
        '@media(max-width:950px){.cards,.reference{grid-template-columns:1fr}}</style>'
        '<h1>تصویر و خروجی OCR در هر پردازش</h1>'
        '<p>چهار پردازش جداگانه روی تصویر اصلی اجرا شده‌اند؛ برای مهر دو شدت دیده می‌شود. کارت آخر ترکیب فیلتر هافتون، تیزکردن ملایم، اصلاح نور و کاهش ملایم مهر است. '
        'همهٔ تصاویر با پایپلاین پیش‌فرض Indra خوانده شده‌اند. تغییر متن یا confidence به‌تنهایی به معنی افزایش دقت نیست. '
        'برای دیدن تصویر کامل روی پیش‌نمایش کلیک کنید.</p>'
        f'<nav>{navigation}</nav>{"".join(blocks)}</html>'
    )
    (args.output_dir / "comparison.html").write_text(page, encoding="utf-8")
    print((args.output_dir / "comparison.html").resolve(), flush=True)


if __name__ == "__main__":
    main()
