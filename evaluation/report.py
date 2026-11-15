from __future__ import annotations

import functools
import json
import time
from collections import Counter
from pathlib import Path

from persian_ocr.config import EVAL_DATA_DIR, REPORTS_DIR
from persian_ocr.engine import OcrEngine

from .groundtruth import load_gt, load_verdicts
from .hypotheses import MODES, collect
from .metrics import aggregate, document_metrics

ROWS = [
    ("Word Accuracy", "word_acc", "↑"), ("Word Precision", "word_prec", "↑"), ("Word F1", "f1", "↑"),
    ("WER (ordered)", "wer_ordered", "↓"), ("WER (order-free)", "wer_free", "↓"), ("CER (ordered)", "cer", "↓"),
    ("SER", "ser", "↓"), ("SER (adjusted)", "ser_adj", "↓"), ("Number Accuracy (≥۴ رقم)", "num_acc", "↑"),
]
MULTI_PAGE_LIMIT = 2


def _summary_table(agg: dict[str, dict]) -> list[str]:
    lines = ["| متریک | معمولی | Tiling قبلی | **مهندسی‌شده** | جهت بهتر |", "|---|---|---|---|---|"]
    for name, key, direction in ROWS:
        lines.append(f"| {name} | {agg['single_page'][key]:.1%} | {agg['tiled'][key]:.1%} | **{agg['engineered'][key]:.1%}** | {direction} |")
    return lines


def _per_doc_table(docs: list[dict]) -> list[str]:
    lines = ["| سند | صفحه | Word Acc | Word Prec | WER free | CER | SER | SER adj | Number Acc | زمان |", "|---|---|---|---|---|---|---|---|---|---|"]
    for d in docs:
        e, s = d["m"]["engineered"], d["m"]["single_page"]
        lines.append(
            f"| {d['file']} | {d['pages']} | {e['word_acc']:.0%} ({s['word_acc']:.0%}) | {e['word_prec']:.0%} | {e['wer_free']:.0%} | "
            f"{e['cer']:.0%} | {e['ser']:.0%} ({s['ser']:.0%}) | {e['ser_adj']:.0%} | {e['num_acc']:.0%} ({s['num_acc']:.0%}) | {d['time']}s |"
        )
    return lines


def _invoice_table(docs: list[dict]) -> list[str]:
    lines = ["| سند | معادلات درست | اصلاح خودکار | ناسازگار |", "|---|---|---|---|"]
    total = Counter()
    for d in docs:
        if not d["inv"]:
            continue
        ok = sum(c.get("ok", 0) for c in d["inv"])
        fixed = sum(c.get("corrected", 0) for c in d["inv"])
        bad = sum(c.get("mismatch", 0) for c in d["inv"])
        total.update(ok=ok, fixed=fixed, bad=bad)
        lines.append(f"| {d['file']} | {ok} | {fixed} | {bad} |")
    n = sum(total.values()) or 1
    lines.append(f"| **جمع** | {total['ok']} ({total['ok'] / n:.0%}) | {total['fixed']} ({total['fixed'] / n:.0%}) | {total['bad']} ({total['bad'] / n:.0%}) |")
    return lines


NOTES = [
    "- **GT بازنویسی ساختاریافته است**، نه رونویسی خط‌به‌خط (برچسب‌ها و ترتیب فرق دارد). پس WER/CER **ترتیب‌دار** عمداً بدبینانه است؛ "
    "برای قضاوت از Word Accuracy، WER (order-free)، SER و Number Accuracy استفاده کن.",
    "- **Word Precision** پایین‌تر از واقعیت است: OCR مهر، سربرگ و پاورقی را هم می‌خواند و GT ندارد.",
    "- **SER** سخت‌گیر است: یک رقم غلط یعنی کل خط خطا. **SER (adjusted)** خطوطی با شناسه checksum‌نامعتبر (خطای خود GT) را کنار می‌گذارد.",
    "- خروجی مهندسی‌شده = جدول از سلول‌ها + خطوط بیرون جدول (بدون تکرار)، بدون دیکشنری سازمان.",
    "- ۷ سند از ۸ سند همان‌هایی هستند که روی آن‌ها کد تنظیم شد: **این اعداد in-sample و خوش‌بینانه‌اند.**",
]


def _mask_note() -> list[str]:
    verdicts = load_verdicts()
    if not verdicts:
        return []
    wrong = sum(v["verdict"] == "gt" for v in verdicts)
    unreadable = sum(v["verdict"] == "image" for v in verdicts)
    return [
        f"> **ماسک GT:** {wrong + unreadable} عدد از ground truth کنار گذاشته شده‌اند چون با دیدن تصویر «GT اشتباه» ({wrong}) یا «نامفهوم یا روی سند چاپ‌نشده» ({unreadable}) تشخیص داده شدند "
        "(`evaluation/number_verdicts.json`). فایل‌های `eval_data` دست‌نخورده‌اند و ماسک هنگام خواندن اعمال می‌شود. "
        f"{sum(v['verdict'] == 'ocr' for v in verdicts)} خطای واقعی OCR در GT می‌مانند."
    ]


def build_markdown(docs: list[dict]) -> str:
    short = [d for d in docs if d["pages"] <= MULTI_PAGE_LIMIT]
    agg_all = {m: aggregate([d["m"][m] for d in docs]) for m in MODES}
    agg_short = {m: aggregate([d["m"][m] for d in short]) for m in MODES}
    n_pages = sum(d["pages"] for d in docs)

    lines = [
        "# گزارش متریک‌ها — eval_data", "",
        f"اجرا: {time.strftime('%Y-%m-%d %H:%M')} | {len(docs)} سند، {n_pages} صفحه، "
        f"{agg_all['engineered']['N']} واژه و {agg_all['engineered']['lines']} خط در GT | CPU", "",
        *_mask_note(), "",
        "## ۱. نتیجه کلی (جمع همه اسناد)", "", *_summary_table(agg_all), "",
        f"## ۱-ب. فقط {len(short)} سند ۱ تا {MULTI_PAGE_LIMIT} صفحه‌ای", "",
        "GT فاکتورهای چندصفحه‌ای مشخصات خریدار/فروشنده را **یک بار** آورده، ولی هر صفحه فاکتور آن را تکرار می‌کند "
        "(۲۷۱۵۳: ۱۵ بار، ۲۹۴۰۵: ۵ بار) → در آن اسناد Precision/WER/CER ذاتاً ناعادلانه است.", "",
        *_summary_table(agg_short), "",
        "## ۲. به تفکیک سند (مهندسی‌شده؛ در پرانتز: روش معمولی)", "", *_per_doc_table(docs), "",
        "## ۳. سازگاری ریاضی فاکتورها (بدون نیاز به GT)", "", *_invoice_table(docs), "",
        "## ۴. تعریف متریک‌ها و محدودیت‌ها", "", *NOTES,
    ]
    return "\n".join(lines)


def run(refresh: bool = False, data_dir: Path = EVAL_DATA_DIR) -> Path:
    loader = functools.cache(OcrEngine.load)
    docs = []
    for pdf in sorted(data_dir.glob("*.pdf")):
        gt_path = pdf.with_suffix(".txt")
        if not gt_path.exists():
            continue
        gt = load_gt(gt_path)
        hyps = collect(loader, pdf, refresh)
        docs.append({
            "file": pdf.name, "pages": hyps["pages"], "time": hyps["engineered_time"], "inv": hyps["invoice_checks"],
            "m": {m: document_metrics(gt, hyps[m]) for m in MODES},
        })
        print(f"{pdf.stem[:16]:16s} " + " | ".join(f"{m[:6]} WA={docs[-1]['m'][m]['word_acc']:.0%} SER={docs[-1]['m'][m]['ser']:.0%}" for m in MODES))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "metrics_report.md"
    out.write_text(build_markdown(docs), encoding="utf-8", newline="\n")
    (REPORTS_DIR / "metrics_report.json").write_text(
        json.dumps({"aggregate": {m: aggregate([d["m"][m] for d in docs]) for m in MODES},
                    "docs": [{"file": d["file"], "pages": d["pages"], "metrics": d["m"]} for d in docs]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
        newline="\n",
    )
    return out
