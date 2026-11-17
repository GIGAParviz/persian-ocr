from __future__ import annotations

import argparse
import base64
import difflib
import html
import json
import os
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from persian_ocr.config import PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.pdfio import load_gray_page
from persian_ocr.pipeline import PageOcr, process_document
from persian_ocr.text import normalize_digits


FREQ_X = 0.024
FREQ_Y = 0.025
NOTCH_SIGMA = 0.002
CORE = 768
HALO = 128
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def notch_patch(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    fy = np.fft.fftfreq(height)[:, None]
    fx = np.fft.fftfreq(width)[None, :]
    mask = np.ones((height, width), dtype=np.float32)
    for sy in (-1, 1):
        for sx in (-1, 1):
            radius = (fy - sy * FREQ_Y) ** 2 + (fx - sx * FREQ_X) ** 2
            mask *= 1 - np.exp(-radius / (2 * NOTCH_SIGMA**2))
    filtered = np.fft.ifft2(np.fft.fft2(gray.astype(np.float32)) * mask).real
    return np.clip(filtered, 0, 255).astype(np.uint8)


def descreen(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    result = np.empty_like(gray)
    for y0 in range(0, height, CORE):
        y1 = min(y0 + CORE, height)
        ry0, ry1 = max(0, y0 - HALO), min(height, y1 + HALO)
        for x0 in range(0, width, CORE):
            x1 = min(x0 + CORE, width)
            rx0, rx1 = max(0, x0 - HALO), min(width, x1 + HALO)
            patch = notch_patch(gray[ry0:ry1, rx0:rx1])
            result[y0:y1, x0:x1] = patch[y0 - ry0:y1 - ry0, x0 - rx0:x1 - rx0]
    return result


def embedded_preview(gray: np.ndarray) -> str:
    height, width = gray.shape
    scale = min(1.0, 950 / width, 1600 / height)
    if scale < 1:
        gray = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    encoded = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 83])[1]
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def embedded_crop(gray: np.ndarray, box: tuple[int, int, int, int], pad: int = 18) -> str:
    x0, y0, x1, y1 = box
    crop = gray[max(0, y0 - pad):min(gray.shape[0], y1 + pad), max(0, x0 - pad):min(gray.shape[1], x1 + pad)]
    if crop.size == 0:
        return ""
    encoded = cv2.imencode(".png", crop)[1]
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")


def item_box(item: object) -> tuple[int, int, int, int]:
    return tuple(round(float(v)) for v in item.box[:4])


def match_items(before: list, after: list) -> list[tuple[object, object]]:
    pairs = []
    available = set(range(len(after)))
    for original in before:
        x0, y0, x1, y1 = item_box(original)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        nearest = None
        for j in available:
            ax0, ay0, ax1, ay1 = item_box(after[j])
            acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
            distance = abs(cx - acx) / max(30, x1 - x0) + abs(cy - acy) / max(20, y1 - y0)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, j)
        if nearest is not None and nearest[0] < 0.7:
            available.remove(nearest[1])
            pairs.append((original, after[nearest[1]]))
    return pairs


def all_items(page: PageOcr) -> list:
    return [*page.lines, *(cell for table in page.tables for row in table.rows for cell in row)]


def crop_cards(before: PageOcr, after: PageOcr, gray_before: np.ndarray, gray_after: np.ndarray) -> tuple[str, int]:
    pairs = match_items(all_items(before), all_items(after))
    changes = [(a, b) for a, b in pairs if a.text.strip() != b.text.strip() and (a.text.strip() or b.text.strip())]
    changes.sort(key=lambda pair: (any(ch.isdigit() for ch in pair[0].text + pair[1].text), len(pair[0].text) + len(pair[1].text)), reverse=True)
    selected = changes[:12]
    if len(selected) < 4:
        unchanged = sorted((pair for pair in pairs if pair not in changes and pair[0].text.strip()), key=lambda pair: float(pair[0].conf))
        selected.extend(unchanged[:4 - len(selected)])
    cards = []
    for original, filtered in selected:
        a = embedded_crop(gray_before, item_box(original))
        b = embedded_crop(gray_after, item_box(filtered))
        if not a or not b:
            continue
        cards.append(
            '<div class="crop-pair">'
            f'<div><img src="{a}"><p dir="auto">{html.escape(original.text)}</p><small>{float(original.conf):.3f}</small></div>'
            f'<div><img src="{b}"><p dir="auto">{html.escape(filtered.text)}</p><small>{float(filtered.conf):.3f}</small></div>'
            '</div>'
        )
    return "".join(cards), len(changes)


def number_changes(before: str, after: str) -> tuple[list[str], list[str]]:
    pattern = re.compile(r"\d[\d,٬،]*")
    left = Counter(token for token in pattern.findall(normalize_digits(before)) if len(re.sub(r"\D", "", token)) >= 5)
    right = Counter(token for token in pattern.findall(normalize_digits(after)) if len(re.sub(r"\D", "", token)) >= 5)
    return list((left - right).elements()), list((right - left).elements())


def compare_file(engine: OcrEngine, path: Path, output_dir: Path) -> tuple[dict, str]:
    gray = load_gray_page(path)
    filtered = descreen(gray)
    filtered_path = output_dir / f"{path.stem}_notch.png"
    if not cv2.imwrite(str(filtered_path), filtered):
        raise RuntimeError(f"Could not save {filtered_path}")
    seen_before = {}
    seen_after = {}

    def before_hook(index: int, page_gray: np.ndarray, page: PageOcr) -> None:
        seen_before["gray"] = page_gray
        seen_before["page"] = page

    def after_hook(index: int, page_gray: np.ndarray, page: PageOcr) -> None:
        seen_after["gray"] = page_gray
        seen_after["page"] = page

    baseline = process_document(engine, path, PipelineConfig(), before_hook)
    candidate = process_document(engine, filtered_path, PipelineConfig(), after_hook)
    before_page = baseline["pages"][0]
    after_page = candidate["pages"][0]
    changed_crops, changed_pairs = crop_cards(seen_before["page"], seen_after["page"], seen_before["gray"], seen_after["gray"])
    removed, added = number_changes(before_page["text_dedup"], after_page["text_dedup"])
    before_text = before_page["text_dedup"]
    after_text = after_page["text_dedup"]
    summary = {
        "file": path.name,
        "size": [gray.shape[1], gray.shape[0]],
        "before_lines": len(seen_before["page"].lines),
        "after_lines": len(seen_after["page"].lines),
        "matched_text_changes": changed_pairs,
        "text_changed": before_text != after_text,
        "numbers_removed": removed,
        "numbers_added": added,
        "before_ocr_sec": baseline["time_sec"],
        "after_ocr_sec": candidate["time_sec"],
    }
    (output_dir / f"{path.stem}_before.json").write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir / f"{path.stem}_after.json").write_text(json.dumps(candidate,ensure_ascii=False,indent=2),encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(before_text.splitlines(), after_text.splitlines(), fromfile="before", tofile="after", lineterm=""))
    original_href = os.path.relpath(path.resolve(), output_dir.resolve()).replace("\\", "/")
    block = (
        f'<article id="{html.escape(path.stem)}"><h2>{html.escape(path.name)}</h2>'
        f'<p>{gray.shape[1]} × {gray.shape[0]} px · matched changed readings: {changed_pairs} · '
        f'long numeric tokens removed: {html.escape(str(removed))} · added: {html.escape(str(added))}</p>'
        '<div class="grid"><section><h3>Before · original</h3>'
        f'<a href="{html.escape(original_href)}"><img src="{embedded_preview(gray)}"></a>'
        f'<pre dir="auto">{html.escape(before_text)}</pre></section>'
        '<section><h3>After · experimental notch</h3>'
        f'<a href="{html.escape(filtered_path.name)}"><img src="{embedded_preview(filtered)}"></a>'
        f'<pre dir="auto">{html.escape(after_text)}</pre></section></div>'
        '<h3>Matched OCR crops</h3><p>Left: original; right: notch. Detector, recognizer and pipeline settings are unchanged.</p>'
        f'{changed_crops or "<p>No matched changed crops.</p>"}'
        f'<details><summary>Text diff</summary><pre dir="auto">{html.escape(diff)}</pre></details></article>'
    )
    return summary, block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("file/test_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/descreen_comparison"))
    args = parser.parse_args()
    paths = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    if not paths:
        raise SystemExit(f"No images in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = OcrEngine.load()
    summaries = []
    blocks = []
    for path in paths:
        print(f"Comparing {path.name}", flush=True)
        summary, block = compare_file(engine, path, args.output_dir)
        summaries.append(summary)
        blocks.append(block)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(
        f'<tr><td><a href="#{html.escape(Path(item["file"]).stem)}">{html.escape(item["file"])}</a></td>'
        f'<td>{item["before_lines"]} → {item["after_lines"]}</td>'
        f'<td>{item["matched_text_changes"]}</td>'
        f'<td>{html.escape(str(item["numbers_removed"]))}</td>'
        f'<td>{html.escape(str(item["numbers_added"]))}</td></tr>'
        for item in summaries
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Descreen OCR A/B</title>'
        '<style>body{font:16px system-ui;margin:auto;max-width:1500px;padding:24px;background:#f4f6f8;color:#16202d}'
        'article{background:#fff;border-radius:14px;margin:28px 0;padding:18px;box-shadow:0 2px 10px #0001}'
        '.grid,.crop-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}'
        'section,.crop-pair>div{border:1px solid #d8dde4;border-radius:8px;padding:12px;overflow:auto}'
        'table{border-collapse:collapse;background:white;width:100%}th,td{border:1px solid #d8dde4;padding:8px;text-align:left;vertical-align:top}'
        'img{display:block;max-width:100%;height:auto;margin:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}'
        '.crop-pair{margin:12px 0}.crop-pair img{max-height:280px;object-fit:contain}'
        '.crop-pair p{font-size:20px;min-height:1.5em}small{color:#66758b}'
        '@media(max-width:850px){.grid,.crop-pair{grid-template-columns:1fr}}</style>'
        '<h1>Descreen OCR A/B</h1><p>The after image uses the same fixed experimental frequency notch on every input. '
        'Both images run through the default OCR pipeline. Text changes and model confidence are not accuracy scores; '
        'verified transcriptions are needed to judge improvement. Click a preview to open the full resolution image.</p>'
        '<table><thead><tr><th>Image</th><th>OCR lines</th><th>Changed matched readings</th><th>Long numbers removed</th><th>Long numbers added</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        + "".join(blocks) + '</html>'
    )
    (args.output_dir / "comparison.html").write_text(page, encoding="utf-8")
    print((args.output_dir / "comparison.html").resolve())


if __name__ == "__main__":
    main()
