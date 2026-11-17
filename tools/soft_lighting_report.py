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
from indra_ocr.rtl import flip

from persian_ocr.config import PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.orientation import robust_upright
from persian_ocr.pdfio import load_gray_page
from persian_ocr.pipeline import process_document
from persian_ocr.text import normalize_digits
from tools.preprocessing_stage_report import enhance, flatten_lighting, focus_crop, preview


sys.stdout.reconfigure(encoding="utf-8")
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
STAGES = [
    ("original", "تصویر اصلی"),
    ("sharpen", "شارپ‌سازی ملایم"),
    ("connect", "شارپ‌سازی و اتصال شکستگی‌های کوچک"),
    ("soft_light", "اتصال متن و اصلاح نور ملایم"),
    ("old_light", "اصلاح نور قبلی با شدت ۱۰۰٪"),
]


def connect_faint_strokes(gray: np.ndarray, kernel: int = 2, strength: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    inverted = 255 - gray
    structure = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel))
    joined = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, structure)
    result = cv2.addWeighted(gray, 1 - strength, 255 - joined, strength, 0)
    gain = np.maximum(gray.astype(np.int16) - result.astype(np.int16), 0).astype(np.uint8)
    return result, gain


def make_variants(gray: np.ndarray, strength: float, bridge_strength: float, kernel: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
    sharp = enhance(gray)
    connected, gain = connect_faint_strokes(sharp, kernel, bridge_strength)
    full = flatten_lighting(connected)
    soft = cv2.addWeighted(connected, 1 - strength, full, strength, 0)
    variants = {
        "original": gray,
        "sharpen": sharp,
        "connect": connected,
        "soft_light": soft,
        "old_light": flatten_lighting(gray),
    }
    return variants, gain


def embedded_png(array: np.ndarray) -> str:
    encoded = cv2.imencode(".png", array)[1]
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")


def number_tokens(text: str) -> Counter:
    tokens = re.findall(r"\d[\d,٬،]*", normalize_digits(text))
    return Counter(token for token in tokens if len(re.sub(r"\D", "", token)) >= 5)


def fixed_box_comparison(engine: OcrEngine, gray: np.ndarray, strength: float, bridge_strength: float, kernel: int) -> tuple[list[dict], np.ndarray, np.ndarray]:
    with engine.force_rtl():
        oriented, _, _, _ = robust_upright(engine.ort, gray)
        boxes = engine.ort.detect(oriented)
        baseline = engine.ort.recognize(oriented, boxes)
        sharp = enhance(oriented)
        connected, _ = connect_faint_strokes(sharp, kernel, bridge_strength)
        processed = cv2.addWeighted(connected, 1 - strength, flatten_lighting(connected), strength, 0)
        del sharp, connected
        candidate = engine.ort.recognize(processed, boxes)
    records = []
    for box, old, new in zip(boxes, baseline, candidate):
        x0, y0, x1, y1 = (round(float(v)) for v in box[:4])
        records.append({
            "box": [x0, y0, x1, y1],
            "before": flip(old[0]).strip(),
            "after": flip(new[0]).strip(),
            "before_conf": round(float(old[1]), 4),
            "after_conf": round(float(new[1]), 4),
        })
    return records, oriented, processed


def crop_cards(records: list[dict], before: np.ndarray, after: np.ndarray, limit: int = 14) -> str:
    changed = [item for item in records if item["before"] != item["after"]]
    changed.sort(key=lambda item: (item["before_conf"], -len(item["before"])))
    cards = []
    for item in changed[:limit]:
        x0, y0, x1, y1 = item["box"]
        pad = 15
        a = before[max(0, y0 - pad):min(before.shape[0], y1 + pad), max(0, x0 - pad):min(before.shape[1], x1 + pad)]
        b = after[max(0, y0 - pad):min(after.shape[0], y1 + pad), max(0, x0 - pad):min(after.shape[1], x1 + pad)]
        if not a.size or not b.size:
            continue
        cards.append(
            '<div class="pair">'
            f'<div><img src="{embedded_png(a)}"><p dir="auto">{html.escape(item["before"])}</p><small>{item["before_conf"]:.3f}</small></div>'
            f'<div><img src="{embedded_png(b)}"><p dir="auto">{html.escape(item["after"])}</p><small>{item["after_conf"]:.3f}</small></div>'
            '</div>'
        )
    return "".join(cards) if cards else "<p>در باکس‌های ثابت، متن خروجی تغییر نکرد.</p>"


def compare_file(engine: OcrEngine, path: Path, output_dir: Path, strength: float, bridge_strength: float, kernel: int) -> tuple[dict, str]:
    gray = load_gray_page(path)
    variants, gain = make_variants(gray, strength, bridge_strength, kernel)
    folder = output_dir / path.stem
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "bridge_gain.png"), np.clip(gain.astype(np.uint16) * 8, 0, 255).astype(np.uint8))
    results = {}
    for key, title in STAGES:
        image_path = folder / f"{key}.png"
        if not cv2.imwrite(str(image_path), variants[key]):
            raise RuntimeError(f"Cannot write {image_path}")
        result = process_document(engine, path if key == "original" else image_path, PipelineConfig())
        results[key] = result
        (folder / f"{key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path.name, key, "lines", len(result["pages"][0]["raw_text"].splitlines()), flush=True)
    fixed, oriented, processed = fixed_box_comparison(engine, gray, strength, bridge_strength, kernel)
    (folder / "fixed_boxes.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline = results["original"]["pages"][0]["text_dedup"]
    baseline_numbers = number_tokens(baseline)
    summary = {
        "file": path.name,
        "size": [gray.shape[1], gray.shape[0]],
        "fixed_boxes": len(fixed),
        "fixed_boxes_changed": sum(item["before"] != item["after"] for item in fixed),
        "stages": {},
    }
    cards = []
    for key, title in STAGES:
        text = results[key]["pages"][0]["text_dedup"]
        removed = list((baseline_numbers - number_tokens(text)).elements())
        added = list((number_tokens(text) - baseline_numbers).elements())
        summary["stages"][key] = {
            "raw_lines": len(results[key]["pages"][0]["raw_text"].splitlines()),
            "long_numbers_removed": removed,
            "long_numbers_added": added,
            "text_changed": text != baseline,
        }
        diff = "\n".join(difflib.unified_diff(baseline.splitlines(), text.splitlines(), fromfile="original", tofile=key, lineterm=""))
        cards.append(
            f'<section><h3>{html.escape(title)}</h3><a href="{html.escape(path.stem)}/{key}.png"><img src="{preview(variants[key])}"></a>'
            f'<h4>برش بزرگ‌شده</h4><img src="{preview(focus_crop(variants[key]), 800, 800)}">'
            f'<p>خطوط: {summary["stages"][key]["raw_lines"]} · اعداد حذف‌شده: {html.escape(str(removed))} · اعداد اضافه‌شده: {html.escape(str(added))}</p>'
            f'<details><summary>متن کامل Indra</summary><pre dir="auto">{html.escape(text)}</pre></details>'
            f'<details><summary>تفاوت با نسخهٔ اصلی</summary><pre dir="auto">{html.escape(diff)}</pre></details>'
            f'<a href="{html.escape(path.stem)}/{key}.json">JSON مدل</a></section>'
        )
    mask_preview = np.clip(gain.astype(np.uint16) * 8, 0, 255).astype(np.uint8)
    block = (
        f'<article id="{html.escape(path.stem)}"><h2>{html.escape(path.name)}</h2>'
        f'<p>{gray.shape[1]} × {gray.shape[0]} پیکسل · {summary["fixed_boxes_changed"]} خوانش تغییرکرده از {summary["fixed_boxes"]} باکس ثابت</p>'
        f'<div class="grid">{"".join(cards)}</div>'
        '<h3>محل اتصال پیکسل‌ها</h3><p>نقاط روشن، پیکسل‌هایی هستند که مرحلهٔ اتصال کمی تیره‌تر کرده است.</p>'
        f'<img class="mask" src="{preview(focus_crop(mask_preview), 800, 700)}">'
        f'<h3>آزمایش Indra با باکس‌های ثابت</h3><p>باکس‌ها فقط روی تصویر اصلی تشخیص داده شدند. ستون راست خوانش اصلی و ستون چپ خوانش بعد از شارپ‌سازی، اتصال و اصلاح نور {strength:.0%} است. این بخش تغییرِ باکس‌یابی را حذف می‌کند.</p>'
        f'{crop_cards(fixed, oriented, processed)}<p><a href="{html.escape(path.stem)}/fixed_boxes.json">تمام باکس‌ها و خوانش‌ها</a></p></article>'
    )
    return summary, block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("file/test_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/soft_lighting_comparison"))
    parser.add_argument("--lighting-strength", type=float, default=0.15)
    parser.add_argument("--bridge-strength", type=float, default=0.25)
    parser.add_argument("--bridge-kernel", type=int, default=2)
    args = parser.parse_args()
    if not 0 <= args.lighting_strength <= 1 or not 0 <= args.bridge_strength <= 1 or args.bridge_kernel not in (2, 3):
        raise SystemExit("Invalid processing parameters")
    paths = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES)
    if not paths:
        raise SystemExit(f"No images in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = OcrEngine.load()
    summaries = []
    blocks = []
    for path in paths:
        summary, block = compare_file(engine, path, args.output_dir, args.lighting_strength, args.bridge_strength, args.bridge_kernel)
        summaries.append(summary)
        blocks.append(block)
    (args.output_dir / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    links = " ".join(f'<a href="#{html.escape(path.stem)}">{html.escape(path.name)}</a>' for path in paths)
    page = (
        '<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>شارپ‌سازی و نور ملایم در OCR</title>'
        '<style>body{font:16px system-ui;max-width:1600px;margin:auto;padding:24px;background:#f4f6f8;color:#17212c}'
        'article{background:white;border-radius:13px;padding:20px;margin:28px 0;box-shadow:0 2px 12px #0001}'
        '.grid,.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}'
        'section,.pair>div{border:1px solid #d7dde5;border-radius:8px;padding:13px;overflow:auto}'
        'img{display:block;max-width:100%;height:auto;margin:auto}.pair{margin:12px 0}.pair img{max-height:250px;object-fit:contain}'
        '.pair p{font-size:20px;min-height:1.4em}.mask{background:#111;max-height:700px}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}details{margin:8px 0}nav a{margin:0 8px}'
        '@media(max-width:900px){.grid,.pair{grid-template-columns:1fr}}</style>'
        '<h1>شارپ‌سازی، اتصال شکستگی‌ها و نور ملایم</h1>'
        f'<p>مراحل به ترتیب اجرا شده‌اند. اصلاح نور جدید با شدت {args.lighting_strength:.0%} با خروجی اصلاح نور قبلی ترکیب شده است. '
        f'اتصال، شکاف‌های تا حدود {args.bridge_kernel - 1} پیکسل را با وزن {args.bridge_strength:.0%} تیره می‌کند. تصویر نور قبلی با شدت ۱۰۰٪ برای مقایسه آمده است. '
        'همهٔ کارت‌ها متن مدل Indra را نشان می‌دهند؛ تغییر متن و confidence به‌تنهایی نشان‌دهندهٔ افزایش دقت نیست.</p>'
        f'<nav>{links}</nav>{"".join(blocks)}</html>'
    )
    (args.output_dir / "comparison.html").write_text(page, encoding="utf-8")
    print((args.output_dir / "comparison.html").resolve(), flush=True)


if __name__ == "__main__":
    main()
