from __future__ import annotations

import base64
import html
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from persian_ocr.config import EVAL_DATA_DIR, REPORTS_DIR, PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.pipeline import PageOcr, process_document

from .dashboard import render_page, source_files
from .groundtruth import load_gt
from .metrics import prep, tokens

TEMPLATE = Path(__file__).with_name("errors.html")
OUTPUT = REPORTS_DIR / "number_errors.html"
MIN_DIGITS = 4
NEAR_MIN = 3
LABEL_MIN_RATIO = 75
LABEL_MIN_LEN = 4
LABEL_MIN_COVER = 0.8
LABEL_BELOW = 6.0
CROP_MARGIN = 0.6
CROP_MIN_HEIGHT = 100
CROP_MAX_WIDTH = 1600
PAGE_JPEG_QUALITY = 90
CROP_JPEG_QUALITY = 85

KINDS = {
    "missing": "پیدا نشد",
    "dropped": "رقم افتاده",
    "dropped_zero": "صفر افتاده",
    "added": "رقم اضافه",
    "added_zero": "صفر اضافه",
    "replaced": "رقم جایگزین",
    "multi": "چند خطا",
}
WHERE = {
    "reading": "محل خوانش نزدیک",
    "label": "محل تقریبی از روی برچسب",
    "annotation": "خط توضیحی GT؛ روی سند چاپ نشده",
    "unknown": "محل نامشخص",
}


@dataclass
class Item:
    page: int
    token: str
    box: tuple[float, float, float, float]


def number_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t.isdigit() and len(t) >= MIN_DIGITS]


def missed_numbers(gt: str, hyp: str) -> list[str]:
    gt_bag, hyp_bag = Counter(number_tokens(gt)), Counter(number_tokens(hyp))
    missing = gt_bag - hyp_bag
    out = []
    for token in number_tokens(gt):
        if missing[token] > 0:
            missing[token] -= 1
            out.append(token)
    return out


def _in_zero_run(text: str, pos: int) -> bool:
    return text[pos] == "0" and ((pos > 0 and text[pos - 1] == "0") or (pos + 1 < len(text) and text[pos + 1] == "0"))


def classify(gt: str, reading: str) -> str:
    if not reading:
        return "missing"
    ops = Levenshtein.editops(gt, reading)
    if len(ops) != 1:
        return "multi"
    op = ops[0]
    if op.tag == "delete":
        return "dropped_zero" if _in_zero_run(gt, op.src_pos) else "dropped"
    if op.tag == "insert":
        return "added_zero" if _in_zero_run(reading, op.dest_pos) else "added"
    return "replaced"


def diff_html(a: str, b: str) -> tuple[str, str]:
    left, right = [], []
    for tag, i0, i1, j0, j1 in Levenshtein.opcodes(a, b):
        l, r = html.escape(a[i0:i1]), html.escape(b[j0:j1])
        if tag == "equal":
            left.append(l)
            right.append(r)
        else:
            if l:
                left.append(f"<mark>{l}</mark>")
            if r:
                right.append(f"<mark>{r}</mark>")
    return "".join(left), "".join(right)


def collect_items(pages: list[PageOcr]) -> list[Item]:
    items = []
    for idx, page in enumerate(pages):
        for line in page.lines:
            items += [Item(idx, t, tuple(line.box)) for t in number_tokens(line.text)]
        for table in page.tables:
            for row in table.rows:
                for cell in row:
                    items += [Item(idx, t, tuple(cell.box)) for t in number_tokens(cell.text)]
    return items


def gt_context(gt: str, number: str) -> str:
    return next((line.strip() for line in gt.splitlines() if number in number_tokens(line)), "")


def nearest_item(number: str, items: list[Item], pool: Counter) -> Item | None:
    best, best_dist = None, 99
    for item in items:
        if pool[item.token] <= 0 or abs(len(item.token) - len(number)) > NEAR_MIN:
            continue
        dist = Levenshtein.distance(number, item.token)
        if dist < best_dist:
            best, best_dist = item, dist
    if best is not None and best_dist <= max(NEAR_MIN, len(number) // 3):
        pool[best.token] -= 1
        return best
    return None


def is_annotation(context: str) -> bool:
    return context.startswith("[")


def label_key(context: str, number: str) -> str:
    head = re.split(r"[:：]", context, maxsplit=1)
    return prep(head[0] if len(head) > 1 else context.replace(number, " "))


def label_line(context: str, number: str, pages: list[PageOcr]) -> tuple[int, tuple] | None:
    label = label_key(context, number)
    if len(label) < LABEL_MIN_LEN or is_annotation(context):
        return None
    best, best_score = None, 0.0
    for idx, page in enumerate(pages):
        for line in page.lines:
            text = prep(line.text)
            if len(text) < LABEL_MIN_COVER * len(label):
                continue
            score = fuzz.partial_ratio(label, text)
            if score > best_score:
                best, best_score = (idx, tuple(line.box)), score
    return best if best_score >= LABEL_MIN_RATIO else None


def make_crop(page_jpeg: bytes, box: tuple, wide: bool = False) -> str:
    gray = cv2.imdecode(np.frombuffer(page_jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    height, width = gray.shape
    x0, y0, x1, y1 = (float(v) for v in box[:4])
    h = max(1.0, y1 - y0)
    mx = (x1 - x0) if wide else CROP_MARGIN * h
    below = LABEL_BELOW * h if wide else CROP_MARGIN * h
    cx0, cx1 = int(max(0, x0 - mx)), int(min(width, x1 + mx))
    cy0, cy1 = int(max(0, y0 - CROP_MARGIN * h)), int(min(height, y1 + below))
    crop = cv2.cvtColor(gray[cy0:cy1, cx0:cx1], cv2.COLOR_GRAY2BGR)
    scale = min(max(1.0, CROP_MIN_HEIGHT / max(1, crop.shape[0])), CROP_MAX_WIDTH / max(1, crop.shape[1]))
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    p0, p1 = (int((x0 - cx0) * scale), int((y0 - cy0) * scale)), (int((x1 - cx0) * scale), int((y1 - cy0) * scale))
    cv2.rectangle(crop, p0, p1, (0, 0, 220), 2)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, CROP_JPEG_QUALITY])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def build_rows(doc: str, gt: str, hyp: str, pages: list[PageOcr], jpegs: list[bytes]) -> list[dict]:
    items = collect_items(pages)
    pool = Counter(number_tokens(hyp)) - Counter(number_tokens(gt))
    rows = []
    seen: Counter = Counter()
    for number in missed_numbers(gt, hyp):
        context = gt_context(gt, number)
        item = nearest_item(number, items, pool)
        page = box = None
        where, wide = "unknown", False
        if item is not None:
            page, box, where = item.page, item.box, "reading"
        else:
            found = label_line(context, number, pages)
            if found is not None:
                (page, box), where, wide = found, "label", True
            elif is_annotation(context):
                where = "annotation"
        reading = item.token if item else ""
        kind = classify(number, reading)
        gt_marked, ocr_marked = diff_html(number, reading) if reading else (html.escape(number), "")
        seen[number] += 1
        rows.append({
            "id": f"{doc}:{number}:{seen[number]}",
            "doc": doc,
            "page": page + 1 if page is not None else None,
            "gt": number,
            "ocr": reading,
            "gt_html": gt_marked,
            "ocr_html": ocr_marked,
            "kind": kind,
            "kind_label": KINDS[kind],
            "where": where,
            "where_label": WHERE[where],
            "context": context,
            "crop": make_crop(jpegs[page], box, wide) if box is not None else "",
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "by_doc": dict(Counter(r["doc"] for r in rows)),
        "located": sum(1 for r in rows if r["crop"]),
    }


def run(lexicon: bool = False, remaining: bool = False, data_dir: Path = EVAL_DATA_DIR, out: Path = OUTPUT) -> Path:
    engine = OcrEngine.load()
    rows: list[dict] = []
    for path in source_files(data_dir):
        gt_path = path.with_suffix(".txt")
        if not gt_path.exists():
            continue
        gt = load_gt(gt_path, masked=remaining)
        store: dict[int, tuple[bytes, PageOcr]] = {}

        def keep(idx: int, gray: np.ndarray, page: PageOcr) -> None:
            ok, buf = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, PAGE_JPEG_QUALITY])
            store[idx] = (buf.tobytes() if ok else b"", page)

        result = process_document(engine, path, PipelineConfig(use_lexicon=lexicon), on_page=keep)
        hyp = "\n".join(p["text_dedup"] for p in result["pages"])
        ordered = [store[i] for i in sorted(store)]
        doc_rows = build_rows(path.stem, gt, hyp, [p for _, p in ordered], [j for j, _ in ordered])
        rows += doc_rows
        print(f"{path.stem[:20]:22s} اعداد اشتباه={len(doc_rows):3d}")
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "kinds": KINDS, "summary": summarize(rows), "rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_page(data, TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return out
