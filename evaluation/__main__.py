import argparse
import sys


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="evaluation")
    sub = ap.add_subparsers(dest="command")
    metrics = sub.add_parser("metrics", help="متریک‌های متنی روی eval_data (پیش‌فرض)")
    metrics.add_argument("--refresh", action="store_true", help="OCR دوباره (نادیده گرفتن کش)")
    sub.add_parser("fields", help="دقت فیلدهای نامه‌ها")
    sub.add_parser("compare", help="مقایسه‌ی Indra با مدل‌های دیگر (eval_data/eval-data-compare)")
    dash = sub.add_parser("dashboard", help="داشبورد HTML: تصویر اصلی (قابل چرخش) کنار خروجی مدل")
    dash.add_argument("--refresh", action="store_true", help="OCR دوباره (نادیده گرفتن کش)")
    dash.add_argument("--lexicon", action="store_true", help="دیکشنری سازمان هم اعمال شود (پیش‌فرض خاموش)")
    dash.add_argument("--dir", default=None, help="پوشه‌ی PDF و تصویر (پیش‌فرض eval_data)")
    err = sub.add_parser("errors", help="گالری اعداد اشتباه: برش تصویر، خوانش ما و GT کنار هم")
    err.add_argument("--lexicon", action="store_true", help="دیکشنری سازمان هم اعمال شود (پیش‌فرض خاموش)")
    err.add_argument("--remaining", action="store_true", help="اعدادی که قضاوت‌شده «GT اشتباه» یا «نامفهوم» بودند ماسک شوند؛ فقط خطاهای باقی‌مانده بماند")
    args = ap.parse_args()

    if args.command == "fields":
        from .fields import run
        out = run()
    elif args.command == "compare":
        from .compare import run
        out = run()
    elif args.command == "errors":
        from .errors import run
        out = run(lexicon=args.lexicon, remaining=args.remaining)
    elif args.command == "dashboard":
        from .dashboard import run
        from pathlib import Path

        from persian_ocr.config import EVAL_DATA_DIR

        out = run(refresh=args.refresh, lexicon=args.lexicon, data_dir=Path(args.dir) if args.dir else EVAL_DATA_DIR)
    else:
        from .report import run
        out = run(refresh=getattr(args, "refresh", False))
    print(f"\nگزارش: {out}")
    return 0


sys.exit(main())
