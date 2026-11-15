from __future__ import annotations

import base64
import functools
import html
import json
import re
import time
from pathlib import Path
from typing import Callable

from persian_ocr.config import CACHE_DIR, EVAL_DATA_DIR, IMAGE_SUFFIXES, REPORTS_DIR, PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.pdfio import preview_jpeg
from persian_ocr.pipeline import SUPPLEMENT_TITLE, process_document
from persian_ocr.report.html import page_notes, render_invoice

from .cache import source_signature
from .metrics import prep, tokens

TEMPLATE = Path(__file__).with_name("dashboard.html")
RESULT_CACHE = CACHE_DIR / "dashboard"
OUTPUT = REPORTS_DIR / "dashboard.html"
PLACEHOLDER = "__DATA__"
IMAGE_DPI = 100.0
IMAGE_QUALITY = 70
MIN_MARK_LEN = 4
MAX_MARK_VALUE_LEN = 40
WORD = re.compile(r"\S+")


def source_files(data_dir: Path = EVAL_DATA_DIR) -> list[Path]:
    return sorted(p for p in data_dir.iterdir() if p.is_file() and (p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGE_SUFFIXES))


def load_result(loader: Callable[[], OcrEngine], path: Path, lexicon: bool, refresh: bool = False, cache_dir: Path = RESULT_CACHE) -> dict:
    cache = cache_dir / f"{path.stem}.{'lex' if lexicon else 'nolex'}.json"
    signature = source_signature(path)
    if cache.exists() and not refresh:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("source") == signature:
            return saved["result"]
    result = process_document(loader(), path, PipelineConfig(use_lexicon=lexicon))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"source": signature, "result": result}, ensure_ascii=False), encoding="utf-8")
    return result


def mark_tokens(values) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = str(value or "")
        if text and len(text) <= MAX_MARK_VALUE_LEN:
            out |= {t for t in tokens(text) if len(t) >= MIN_MARK_LEN}
    return out


class Marker:
    def __init__(self, fix: set[str] = frozenset(), review: set[str] = frozenset()):
        self.fix, self.review = fix, review

    def word(self, word: str) -> str:
        found = set(tokens(word))
        escaped = html.escape(word)
        if found & self.fix:
            return f"<span class='w fix'>{escaped}</span>"
        if found & self.review:
            return f"<span class='w rev'>{escaped}</span>"
        return escaped


def render_html(text: str, marker: Marker, low: frozenset[str] = frozenset()) -> str:
    out: list[str] = []
    rows: list[str] = []

    def flush() -> None:
        if rows:
            out.append("<table class='t'>" + "".join(rows) + "</table>")
            rows.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [" ".join(marker.word(w) for w in WORD.findall(cell)) for cell in line.strip("|").split(" | ")]
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells if c) + "</tr>")
            continue
        flush()
        words = " ".join(marker.word(w) for w in WORD.findall(line))
        if line == SUPPLEMENT_TITLE:
            out.append(f"<div class='sup'>{words}</div>")
        else:
            out.append(f"<div class='l{' low' if prep(line) in low else ''}'>{words}</div>")
    flush()
    return "".join(out)


def build_doc(path: Path, result: dict) -> dict:
    pages = []
    for idx, p in enumerate(result["pages"]):
        image, width, height = preview_jpeg(path, idx, IMAGE_DPI, IMAGE_QUALITY)
        marker = Marker(
            fix=mark_tokens(c.get("output") for c in p["corrections"]),
            review=mark_tokens([r.get("input") for r in p["review_queue"]] + [c for r in p["review_queue"] for c in r.get("candidates", [])]),
        )
        low = frozenset(prep(l["text"]) for l in p["low_confidence_lines"])
        pages.append({
            "page": p["page"],
            "image": base64.b64encode(image).decode("ascii") if image else "",
            "size": [width, height],
            "html": render_html(p["text_dedup"], marker, low),
            "notes": "".join(page_notes(p)),
            "invoice": render_invoice(p["invoice"]) if p.get("invoice") else "",
            "stats": {
                "words": len(WORD.findall(p["text_dedup"])),
                "tables": len(p["tables_markdown"]),
                "corr": len(p["corrections"]),
                "rev": len(p["review_queue"]),
                "low": len(p["low_confidence_lines"]),
            },
        })
    mismatches = sum(p["invoice"]["check_summary"].get("mismatch", 0) for p in result["pages"] if p.get("invoice"))
    issues = [p["stats"]["rev"] + p["stats"]["low"] for p in pages]
    return {
        "name": path.stem,
        "file": path.name,
        "time": result["time_sec"],
        "mismatch": mismatches,
        "focus": issues.index(max(issues)) if issues else 0,
        "pages": pages,
    }


def render_page(data: dict, template: str | None = None) -> str:
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, payload)


def run(refresh: bool = False, lexicon: bool = False, data_dir: Path = EVAL_DATA_DIR, out: Path = OUTPUT) -> Path:
    loader = functools.cache(OcrEngine.load)
    docs = []
    for path in source_files(data_dir):
        doc = build_doc(path, load_result(loader, path, lexicon, refresh))
        docs.append(doc)
        print(f"{path.stem[:20]:22s} صفحه={len(doc['pages']):2d} زمان={doc['time']}")
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "lexicon": lexicon, "docs": docs}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_page(data), encoding="utf-8", newline="\n")
    return out
