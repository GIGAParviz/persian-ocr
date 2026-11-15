from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import CACHE_DIR, OUTPUT_DIR, PipelineConfig

COMMANDS = {"run", "debug", "serve"}


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="persian_ocr", description="OCR فارسی اسناد ساخت‌دار (PDF یا تصویر)")
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="OCR کامل و ذخیره خروجی‌ها")
    run.add_argument("file", help="مسیر PDF یا تصویر")
    run.add_argument("--out", type=Path, default=OUTPUT_DIR, help="پوشه خروجی (پیش‌فرض: output/)")
    run.add_argument("--no-lexicon", action="store_true", help="بدون دیکشنری موجودیت‌های سازمان")
    run.add_argument("--no-html", action="store_true", help="بدون گزارش HTML")
    run.add_argument("--no-tables", action="store_true", help="بدون استخراج جدول و فاکتور (برای آزمون)")
    run.add_argument("--max-pages", type=int, default=0)

    dbg = sub.add_parser("debug", help="جدول و معادلات یک صفحه (برای عیب‌یابی فاکتور)")
    dbg.add_argument("file")
    dbg.add_argument("--page", type=int, default=1)

    srv = sub.add_parser("serve", help="اجرای API با Swagger UI (پیش‌فرض: 0.0.0.0:8000)")
    srv.add_argument("--host", default=None, help="پیش‌فرض 0.0.0.0 (روی شبکه باز)؛ برای فقط محلی 127.0.0.1")
    srv.add_argument("--port", type=int, default=None)
    return ap


def _run(args: argparse.Namespace) -> int:
    from .engine import OcrEngine
    from .pipeline import process_document
    from .report import write_outputs

    source = Path(args.file).resolve()
    if not source.exists():
        print(f"خطا: فایل پیدا نشد: {source}")
        return 1
    print(f"پردازش: {source.name} ...")
    config = PipelineConfig(use_lexicon=not args.no_lexicon, max_pages=args.max_pages, tables=not args.no_tables)
    result = process_document(OcrEngine.load(), source, config)
    write_outputs(result, source, args.out, html=not args.no_html)

    pages = result["pages"]
    print(
        f"تمام شد در {result['time_sec']} ثانیه — اصلاح خودکار: {sum(len(p['corrections']) for p in pages)} | "
        f"نیازمند بررسی: {sum(len(p['review_queue']) for p in pages)} | "
        f"خطوط کم‌اطمینان: {sum(len(p['low_confidence_lines']) for p in pages)}"
    )
    print(f"خروجی‌ها در: {args.out}")
    return 0


def _debug(args: argparse.Namespace) -> int:
    from .engine import OcrEngine
    from .invoice import parse_invoice
    from .orientation import robust_upright
    from .pdfio import load_gray_page
    from .tables import extract_tables, table_to_markdown

    source = Path(args.file).resolve()
    engine = OcrEngine.load()
    gray = load_gray_page(source, args.page)
    with engine.force_rtl():
        gray, turns, skew, _ = robust_upright(engine.ort, gray)
        tables = extract_tables(engine.ort, gray)
    out = [f"# {source.name} p{args.page} (turn={turns}, skew={skew:.2f})"]
    for t in tables:
        out.append(table_to_markdown(t))
        out.append("```json\n" + json.dumps(parse_invoice(t), ensure_ascii=False, indent=1) + "\n```")
    target = CACHE_DIR / "debug" / f"{source.stem}_p{args.page}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n".join(out), encoding="utf-8", newline="\n")
    print(f"نوشته شد: {target}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    from .api.server import serve

    serve(args.host, args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "run")
    args = _build_parser().parse_args(argv)
    return {"run": _run, "debug": _debug, "serve": _serve}[args.command](args)
