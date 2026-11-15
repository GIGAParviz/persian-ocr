from __future__ import annotations

import html as htmllib
import json
import re
from collections import Counter
from pathlib import Path

from persian_ocr.config import CACHE_DIR, EVAL_DATA_DIR, REPORTS_DIR

from .groundtruth import load_gt
from .metrics import aggregate, document_metrics, f1, prep, tokens

COMPARE_DIR = EVAL_DATA_DIR / "eval-data-compare"
HYPS_CACHE = CACHE_DIR / "hyps"
PROVIDERS = ("Indra", "Claude", "Gemini", "Chandra")
CURRENT = "Indra (کد فعلی)"
GT_ROWS = (CURRENT,) + PROVIDERS
REFERENCES = ("Claude", "Gemini")
MIN_NUMBER_DIGITS = 4


def html_to_text(content: str) -> str:
    content = re.sub(r"</t[dh]>", " ", content)
    content = re.sub(r"<br\s*/?>|</p>|</h\d>|</tr>|</div>|</li>", "\n", content)
    return htmllib.unescape(re.sub(r"<[^>]+>", "", content))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def chunks_text(path: Path) -> str | None:
    parts = [html_to_text(c.get("content") or c.get("html") or "") for p in _json(path).get("pages", []) for c in p.get("chunks", [])]
    return "\n".join(p for p in parts if p.strip()) or None


def indra_text(path: Path) -> str | None:
    pages = _json(path).get("pages")
    return "\n".join(p["text_dedup"] for p in pages) if pages else None


def lift_fields(path: Path) -> dict | None:
    return _json(path).get("extraction")


def current_indra_text(name: str, cache_dir: Path = HYPS_CACHE) -> str | None:
    return _json(cache_dir / f"{name}.json").get("engineered")


def load_documents(root: Path = COMPARE_DIR) -> dict[str, dict]:
    names = sorted(p.stem for p in (root / "Claude" / "Normalized").glob("*.json"))
    docs = {}
    for name in names:
        docs[name] = {
            CURRENT: current_indra_text(name),
            "Indra": indra_text(root / "Indra" / "Main" / f"{name}.json"),
            "Claude": chunks_text(root / "Claude" / "Normalized" / f"{name}.json"),
            "Gemini": chunks_text(root / "Gemini" / "Normalized" / f"{name}.json"),
            "Chandra": chunks_text(root / "Chandra" / "Normalized" / f"{name}.json"),
            "Lift": lift_fields(root / "Lift" / "Normalized" / f"{name}.json"),
        }
    return docs


def numbers(bag: Counter) -> Counter:
    return Counter({t: n for t, n in bag.items() if t.isdigit() and len(t) >= MIN_NUMBER_DIGITS})


def overlap(ref: Counter, hyp: Counter) -> dict:
    matched = sum((ref & hyp).values())
    recall = matched / max(sum(ref.values()), 1)
    precision = matched / max(sum(hyp.values()), 1)
    return {"recall": recall, "precision": precision, "f1": f1(precision, recall)}


def pair_agreement(a: str, b: str) -> dict:
    bag_a, bag_b = Counter(tokens(a)), Counter(tokens(b))
    return {"words": overlap(bag_a, bag_b), "numbers": overlap(numbers(bag_a), numbers(bag_b))}


def consensus(docs_entry: dict) -> Counter | None:
    a, b = (docs_entry[p] for p in REFERENCES)
    return Counter(tokens(a)) & Counter(tokens(b)) if a and b else None


def vs_consensus(entry: dict, provider: str) -> dict | None:
    ref, text = consensus(entry), entry.get(provider)
    if ref is None or not text:
        return None
    bag = Counter(tokens(text))
    return {"words": overlap(ref, bag), "numbers": overlap(numbers(ref), numbers(bag)), "ref_words": sum(ref.values()), "ref_numbers": sum(numbers(ref).values())}


def gt_results(docs: dict[str, dict], gt_dir: Path = EVAL_DATA_DIR) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for name, entry in docs.items():
        path = gt_dir / f"{name}.txt"
        if not path.exists():
            continue
        gt = load_gt(path)
        out[name] = {p: document_metrics(gt, entry[p]) for p in GT_ROWS if entry.get(p)}
    return out


def lift_vs_gt(fields: dict | None, gt: str) -> dict | None:
    if not fields:
        return None
    gt_tokens = set(tokens(gt))
    values = [str(fields[k]) for k in ("invoice_number", "total") if fields.get(k) not in (None, "")]
    values += [str(item[k]) for item in fields.get("line_items") or [] for k in ("quantity", "unit_price", "amount") if item.get(k) not in (None, "")]
    nums = [prep(v) for v in values if prep(v)]
    hits = sum(n in gt_tokens for n in nums)
    names = {}
    for key in ("seller_name", "buyer_name"):
        toks = tokens(fields.get(key) or "")
        names[key] = sum(t in gt_tokens for t in toks) / len(toks) if toks else None
    return {"numbers": len(nums), "numbers_in_gt": hits, "names": names, "date": prep(str(fields.get("invoice_date") or "")) in gt_tokens or None}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.1f}%"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _gt_section(results: dict[str, dict[str, dict]]) -> list[str]:
    if not results:
        return []
    lines = [f"## ۱. با ground truth ({len(results)} سند: {'، '.join(results)})", ""]
    lines += ["| مدل | Word Acc ↑ | Word Prec ↑ | WER بدون‌ترتیب ↓ | SER (adj) ↓ | Number Acc ↑ |", "|---|---|---|---|---|---|"]
    labels = {"Indra": "**Indra (فایل Main؛ نسخه‌ی قدیمی‌تر کد، دیکشنری روشن)**", CURRENT: "**Indra (کد فعلی، بدون دیکشنری)**"}
    for p in GT_ROWS:
        docs = [r[p] for r in results.values() if p in r]
        if not docs:
            continue
        a = aggregate(docs)
        lines.append(f"| {labels.get(p, p)} | {_pct(a['word_acc'])} | {_pct(a['word_prec'])} | {_pct(a['wer_free'])} | {_pct(a['ser_adj'])} | {_pct(a['num_acc'])} |")
    lines += ["", "به تفکیک سند (Word Acc / Number Acc):", "", "| سند | " + " | ".join(GT_ROWS) + " |", "|---|" + "---|" * len(GT_ROWS)]
    for name, r in results.items():
        cells = [f"{_pct(r[p]['word_acc'])} / {_pct(r[p]['num_acc'])}" if p in r else "–" for p in GT_ROWS]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines + [""]


def _peer_section(docs: dict[str, dict]) -> list[str]:
    lines = ["## ۲. هم‌خوانی دوبه‌دو (همه‌ی اسناد؛ F1 واژه‌ای / F1 اعداد)", ""]
    lines += ["| | " + " | ".join(PROVIDERS) + " |", "|---|" + "---|" * len(PROVIDERS)]
    peer_scores: dict[str, list[float]] = {p: [] for p in PROVIDERS}
    for a in PROVIDERS:
        cells = []
        for b in PROVIDERS:
            if a == b:
                cells.append("–")
                continue
            results = [pair_agreement(e[a], e[b]) for e in docs.values() if e.get(a) and e.get(b)]
            w, n = _mean([r["words"]["f1"] for r in results]), _mean([r["numbers"]["f1"] for r in results])
            cells.append(f"{_pct(w)} / {_pct(n)}")
            if w is not None:
                peer_scores[a].append(w)
        lines.append(f"| **{a}** | " + " | ".join(cells) + " |")
    lines += ["", "میانگین هم‌خوانی هر مدل با بقیه: " + "، ".join(f"{p} {_pct(_mean(v))}" for p, v in peer_scores.items()), ""]
    return lines


def _consensus_section(docs: dict[str, dict]) -> list[str]:
    lines = ["## ۳. اجماع Claude ∩ Gemini (واژه‌هایی که هر دو تولید کرده‌اند) به‌عنوان مرجع تقریبی", ""]
    lines += ["| سند | واژه‌ی مرجع | عدد مرجع | Indra: بازیابی واژه / عدد | Chandra: بازیابی واژه / عدد | Claude↔Gemini F1 |", "|---|---|---|---|---|---|"]
    rec = {"Indra": ([], []), "Chandra": ([], [])}
    ceiling = []
    for name, e in docs.items():
        ref = consensus(e)
        if ref is None:
            continue
        cells = []
        for p in ("Indra", "Chandra"):
            r = vs_consensus(e, p)
            cells.append("–" if r is None else f"{_pct(r['words']['recall'])} / {_pct(r['numbers']['recall'])}")
            if r:
                rec[p][0].append(r["words"]["recall"])
                rec[p][1].append(r["numbers"]["recall"])
        cg = pair_agreement(e["Claude"], e["Gemini"])["words"]["f1"]
        ceiling.append(cg)
        lines.append(f"| {name} | {sum(ref.values())} | {sum(numbers(ref).values())} | {cells[0]} | {cells[1]} | {_pct(cg)} |")
    lines.append(
        f"| **میانگین** | | | **{_pct(_mean(rec['Indra'][0]))} / {_pct(_mean(rec['Indra'][1]))}** | **{_pct(_mean(rec['Chandra'][0]))} / {_pct(_mean(rec['Chandra'][1]))}** | {_pct(_mean(ceiling))} |"
    )
    return lines + [""]


def _lift_section(docs: dict[str, dict], gt_dir: Path) -> list[str]:
    lines = ["## ۴. Lift (استخراج فیلد فاکتور، نه OCR متن کامل)", ""]
    lines += ["| سند | اعداد Lift که در GT هستند | نام فروشنده در GT | نام خریدار در GT | تاریخ در GT |", "|---|---|---|---|---|"]
    total_n = total_hit = 0
    for name, e in docs.items():
        path = gt_dir / f"{name}.txt"
        if not path.exists():
            continue
        r = lift_vs_gt(e.get("Lift"), load_gt(path))
        if r is None:
            continue
        total_n += r["numbers"]
        total_hit += r["numbers_in_gt"]
        lines.append(f"| {name} | {r['numbers_in_gt']} از {r['numbers']} | {_pct(r['names']['seller_name'])} | {_pct(r['names']['buyer_name'])} | {'بله' if r['date'] else 'خیر'} |")
    lines.append(f"| **جمع** | **{total_hit} از {total_n}** | | | |")
    return lines + [""]


def build_markdown(docs: dict[str, dict], gt_dir: Path = EVAL_DATA_DIR) -> str:
    gt = gt_results(docs, gt_dir)
    missing = [n for n, e in docs.items() if not e.get("Indra")]
    out = ["# مقایسه‌ی Indra (این پروژه) با مدل‌های دیگر", ""]
    out += [
        f"{len(docs)} سند در `eval_data/eval-data-compare`. منبع متن هر مدل: Indra = خروجی واقعی API (`Main`، فیلد `text_dedup`، با دیکشنری روشن)؛ Claude و Gemini و Chandra = `Normalized`.",
        "",
        "> **هشدار منبع:** `Indra/Normalized` استفاده نشد. آن فایل‌ها را یک مدل دیگر ساخته و برای هر سند دقیقاً همان توکن مصرف شده (۱۰۷۵ ورودی / ۱۰۶۲ خروجی)، یعنی محتوای سند را ندیده و قالب خالی تولید کرده است.",
    ]
    if missing:
        out.append(f"> سندهای بدون خروجی Indra (در محاسبات کنار گذاشته شدند): {'، '.join(missing)}.")
    out.append("")
    out += _gt_section(gt) + _peer_section(docs) + _consensus_section(docs) + _lift_section(docs, gt_dir)
    out += [
        "## محدودیت‌ها",
        "",
        "- ground truth فقط برای ۳ سند هست؛ این تعداد معنی‌دار آماری نیست و منشأ GT (احتمال ساخت با کمک LLM) می‌تواند به نفع Claude و Gemini سوگیری ایجاد کند.",
        "- Indra روی این سندها in-sample است (۳ سند GT جزو اسناد تنظیم پایپ‌لاین بودند) و با دیکشنری روشن اجرا شده؛ عدد Indra خوش‌بینانه است.",
        "- هم‌خوانی و اجماع **دقت نیستند**: دو مدل می‌توانند هر دو غلط باشند. فقط برای رتبه‌بندی نسبی و پیدا کردن اسناد مشکوک مفیدند.",
        "- `Normalized` Claude و Gemini و Chandra ممکن است خودشان توصیف‌هایی مثل `[مهر: ...]` داشته باشند که متن چاپی نیست.",
        "",
    ]
    return "\n".join(out)


def run(root: Path = COMPARE_DIR) -> Path:
    docs = load_documents(root)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "model_comparison.md"
    out.write_text(build_markdown(docs), encoding="utf-8", newline="\n")
    return out
