from __future__ import annotations

import html
import json
from pathlib import Path

from ..pdfio import preview_jpeg_b64

ITEM_COLS = [
    ("code", "کد"), ("description", "شرح"), ("qty", "مقدار"), ("unit", "واحد"), ("unit_price", "فی"),
    ("amount", "مبلغ"), ("discount", "تخفیف"), ("after_discount", "پس از تخفیف"), ("tax", "مالیات"), ("net", "خالص"),
]
STATUS_STYLE = {
    "ok": ("#e7f6ec", "✓"), "corrected": ("#fff8d6", "اصلاح"), "filled": ("#fff8d6", "تکمیل"),
    "mismatch": ("#fdecec", "✗ بررسی"), "deferred": ("#eef", "…"),
}
CSS = """
body{font-family:Tahoma,Vazirmatn,sans-serif;margin:0;background:#f4f5f7;color:#222}
header{background:#1f3a5f;color:#fff;padding:12px 20px}
.page{display:flex;gap:16px;margin:16px;background:#fff;border-radius:8px;padding:12px;box-shadow:0 1px 3px #0002}
.img{flex:1;max-width:48%}.img img{width:100%;border:1px solid #ddd}
.txt{flex:1;overflow:auto}
pre{white-space:pre-wrap;font-family:inherit;line-height:1.9;background:#fafafa;padding:10px;border-radius:6px}
.box{border-radius:6px;padding:8px 10px;margin:8px 0;font-size:13px}
.fix{background:#e7f6ec;border:1px solid #9fd6b0}
.rev{background:#fff4e5;border:1px solid #f0c27a}
.low{background:#fdecec;border:1px solid #f2a7a7}
.inv{border:1px solid #9bb4d6;background:#f3f7fc}
code{direction:ltr;unicode-bidi:embed;background:#0000000d;padding:0 4px;border-radius:3px}
"""


def _esc(v) -> str:
    return html.escape(str(v))


def _fmt(v) -> str:
    return f"{v:,}" if isinstance(v, int) else html.escape(str(v or ""))


def _kv(pairs: dict) -> str:
    return " | ".join(f"{_esc(k)}: <code>{_esc(v)}</code>" for k, v in pairs.items())


def render_invoice(inv: dict) -> str:
    out = ["<div class='box inv'><b>فاکتور ساختاریافته</b>", f"<div>{_kv(inv['header'])}</div>"]
    for side, label in (("seller", "فروشنده"), ("buyer", "خریدار")):
        party = inv["parties"].get(side)
        if party:
            out.append(f"<div><b>{label}:</b> {_kv(party)}</div>")

    cols = [(k, n) for k, n in ITEM_COLS if any(k in it for it in inv["items"])]
    cell = "style='border:1px solid #ccc;padding:3px'"
    out.append("<table style='border-collapse:collapse;margin:8px 0;font-size:12px'><tr>" + "".join(f"<th {cell}>{n}</th>" for _, n in cols) + "</tr>")
    for it in inv["items"]:
        out.append("<tr>" + "".join(f"<td {cell}>{_fmt(it.get(k))}</td>" for k, _ in cols) + "</tr>")
    out.append("</table>")

    if inv["totals"]:
        out.append("<div>جمع‌ها: " + " | ".join(f"{_esc(k)}: <code>{_fmt(v)}</code>" for k, v in inv["totals"].items()) + "</div>")
    s = inv["check_summary"]
    out.append(f"<div style='margin-top:6px'><b>راستی‌آزمایی:</b> ✓{s.get('ok', 0)} | اصلاح {s.get('corrected', 0)} | ✗{s.get('mismatch', 0)}</div><ul style='font-size:12px'>")
    for c in inv["checks"]:
        bg, tag = STATUS_STYLE.get(c["status"], ("#fff", c["status"]))
        extra = {k: v for k, v in c.items() if k not in ("check", "status")}
        detail = f"<code>{_esc(json.dumps(extra, ensure_ascii=False))}</code>" if extra else ""
        out.append(f"<li style='background:{bg}'>{tag} — {_esc(c['check'])} {detail}</li>")
    out.append("</ul></div>")
    return "".join(out)


def page_notes(p: dict) -> list[str]:
    parts = []
    if p["corrections"]:
        items = "".join(
            f"<li>{_esc(c.get('kind', 'checksum'))}: <code>{_esc(c.get('input', ''))}</code> ← <code>{_esc(c.get('output', ''))}</code></li>"
            for c in p["corrections"]
        )
        parts.append(f"<div class='box fix'><b>اصلاحات خودکار ({len(p['corrections'])})</b> — برای تایید نگاه کنید<ul>{items}</ul></div>")
    if p["review_queue"]:
        items = "".join(
            f"<li>{_esc(r.get('kind', ''))}: <code>{_esc(r.get('input', ''))}</code> — وضعیت: {_esc(r.get('status', ''))}"
            f" — کاندیدها: <code>{_esc(', '.join(r.get('candidates', [])))}</code></li>"
            for r in p["review_queue"]
        )
        parts.append(f"<div class='box rev'><b>نیازمند بررسی انسانی ({len(p['review_queue'])})</b><ul>{items}</ul></div>")
    if p["low_confidence_lines"]:
        items = "".join(f"<li>[{l['conf']}] {_esc(l['text'])}</li>" for l in p["low_confidence_lines"])
        parts.append(f"<div class='box low'><b>خطوط کم‌اطمینان ({len(p['low_confidence_lines'])})</b><ul>{items}</ul></div>")
    return parts


def build_review_html(result: dict, source: str | Path) -> str:
    parts = [
        "<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>",
        f"<title>مرور OCR — {_esc(result['file'])}</title><style>{CSS}</style></head><body>",
        f"<header><b>مرور انسانی OCR</b> — {_esc(result['file'])} — زمان پردازش: {result['time_sec']} ثانیه</header>",
    ]
    for p in result["pages"]:
        img = preview_jpeg_b64(source, p["page"] - 1)
        parts.append("<div class='page'>")
        parts.append(f"<div class='img'><h3>صفحه {p['page']}</h3><img src='data:image/jpeg;base64,{img}'></div>")
        parts.append("<div class='txt'>")
        parts.extend(page_notes(p))
        if p.get("invoice"):
            parts.append(render_invoice(p["invoice"]))
        parts.append(f"<details><summary>متن کامل صفحه</summary><pre>{_esc(p['text'])}</pre></details>")
        parts.append("</div></div>")
    parts.append("</body></html>")
    return "".join(parts)
