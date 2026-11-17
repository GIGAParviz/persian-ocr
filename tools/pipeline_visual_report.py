from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from persian_ocr.config import IMAGE_SUFFIXES, PipelineConfig
from persian_ocr.engine import OcrEngine
from persian_ocr.orientation import robust_upright
from persian_ocr.pdfio import load_gray_page
from persian_ocr.pipeline import _recover_payable, _repair_dark_amount, process_document
from persian_ocr.tables.cells import _line_masks
from persian_ocr.tables.dark import blank_dark_cells
from persian_ocr.tiling import merge_lines, merge_tiles, tile_bounds
from persian_ocr.vision.footer import recover_footer_segments
from persian_ocr.vision.stamps import unwrap_circular_stamps
from persian_ocr.vision.watermark import watermark_suppress


def _render(image: np.ndarray, boxes=(), crop=None, max_side: int = 3000, png: bool = False) -> str:
    if crop is None:
        left, top, right, bottom = 0, 0, image.shape[1], image.shape[0]
    else:
        left, top, right, bottom = (int(v) for v in crop)
        left, top = max(0, left), max(0, top)
        right, bottom = min(image.shape[1], right), min(image.shape[0], bottom)
    part = np.ascontiguousarray(image[top:bottom, left:right])
    if not part.size:
        raise ValueError("Empty image crop")
    scale = min(1.0, max_side / max(part.shape[:2]))
    if scale < 1:
        part = cv2.resize(part, (round(part.shape[1] * scale), round(part.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if part.ndim == 2:
        part = cv2.cvtColor(part, cv2.COLOR_GRAY2BGR)
    for box, color in boxes:
        x0, y0, x1, y1 = (float(v) for v in box[:4])
        start = (round((x0 - left) * scale), round((y0 - top) * scale))
        end = (round((x1 - left) * scale), round((y1 - top) * scale))
        cv2.rectangle(part, start, end, color, 2)
    ext = ".png" if png else ".jpg"
    options = [] if png else [cv2.IMWRITE_JPEG_QUALITY, 86]
    ok, data = cv2.imencode(ext, part, options)
    if not ok:
        raise ValueError("Could not encode stage image")
    mime = "image/png" if png else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _line_boxes(lines, threshold: float, changed=()) -> list[tuple[list[float], tuple[int, int, int]]]:
    changed_ids = set(changed)
    out = []
    for i, line in enumerate(lines):
        color = (30, 170, 30) if i in changed_ids else ((30, 40, 230) if float(line.conf) < threshold else (230, 110, 20))
        out.append((line.box, color))
    return out


def _stage(stages: list[dict], title: str, detail: str, images: list[tuple[str, str]], extra: str = "") -> None:
    stages.append({"title": title, "detail": detail, "images": images, "extra": extra})


def _stamp_rings(gray: np.ndarray) -> list[np.ndarray]:
    height, width = gray.shape
    roi = gray[int(height * 0.35):, :]
    scale = min(1.0, (2_000_000 / roi.size) ** 0.5)
    sample = cv2.resize(roi, (round(roi.shape[1] * scale), round(roi.shape[0] * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else roi
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(sample, (5, 5), 0), cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=250 * scale, param1=100, param2=48,
        minRadius=max(1, round(130 * scale)), maxRadius=max(1, round(230 * scale)),
    )
    if circles is None:
        return []
    rings = []
    for circle in circles[0][:2]:
        cx, cy, radius = (float(v) / scale for v in circle)
        x0, x1 = max(0, int(cx - radius * 1.05)), min(width, int(cx + radius * 1.05))
        y0, y1 = max(0, int(cy - radius * 1.05)), min(roi.shape[0], int(cy + radius * 1.05))
        patch = roi[y0:y1, x0:x1]
        if patch.size == 0 or (patch < 180).mean() < 0.05:
            continue
        polar = cv2.warpPolar(
            patch, (int(radius), int(2 * np.pi * radius * 0.95)),
            (cx - x0, cy - y0), radius, cv2.WARP_POLAR_LINEAR + cv2.INTER_CUBIC,
        )
        ring = np.vstack([polar, polar])[:, int(radius * 0.70):int(radius * 0.91)]
        rings.append(cv2.rotate(ring, cv2.ROTATE_90_COUNTERCLOCKWISE))
    return rings


def _line_signature(lines) -> list[tuple]:
    return [(tuple(round(float(v), 1) for v in line.box), line.text, round(float(line.conf), 4)) for line in lines]


def _report(source: Path, max_side: int) -> tuple[list[dict], dict, bool]:
    raw_color = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
    if raw_color is None:
        raise ValueError(f"Could not read image: {source}")
    input_gray = load_gray_page(source)
    config = PipelineConfig(max_pages=1)
    engine = OcrEngine.load(dpi=config.dpi)
    with engine.force_rtl():
        selected, turns, skew, scores = robust_upright(engine.ort, input_gray)
    captured = {}

    def on_page(index, gray, page):
        captured["gray"] = np.ascontiguousarray(gray.copy())
        captured["page"] = page

    result = process_document(engine, source, config, on_page)
    gray = captured["gray"]
    page = captured["page"]
    height, width = gray.shape
    top_end, bottom_start = tile_bounds(height, config.overlap_ratio)
    top, bottom = gray[:top_end], gray[bottom_start:]
    header = top[: int(height * config.header_fraction)]
    clean_header = watermark_suppress(header)
    footer_y0 = int(height * 0.90)

    with engine.force_rtl():
        top_lines = list(engine.conv.ocr(top).lines)
        bottom_lines = list(engine.conv.ocr(bottom).lines)
        header_lines = list(engine.conv.ocr(clean_header).lines)
        footer_lines = recover_footer_segments(engine.ort, gray)
        stamp_lines = unwrap_circular_stamps(engine.ort, gray)
        top_merged = merge_lines(top_lines, header_lines)
        bottom_merged = merge_lines(bottom_lines, footer_lines, y_offset=-bottom_start)
        for stamp in stamp_lines:
            bottom_merged.append(type(stamp)(
                box=[stamp.box[0], stamp.box[1] - bottom_start, stamp.box[2], stamp.box[3] - bottom_start],
                text=stamp.text, conf=stamp.conf,
            ))
        merged = merge_tiles(top_merged, bottom_merged, bottom_start)
        amounts_repaired = [_repair_dark_amount(engine, gray, line) for line in merged]
        payable_recovered = _recover_payable(engine, gray, amounts_repaired)

    replay_matches = _line_signature(payable_recovered) == _line_signature(page.lines)
    amount_changes = [i for i, (before, after) in enumerate(zip(merged, amounts_repaired)) if before.text != after.text]
    old_signatures = set(_line_signature(merged))
    final_changes = [i for i, signature in enumerate(_line_signature(payable_recovered)) if signature not in old_signatures]
    cells = [cell for table in page.tables for row in table.rows for cell in row]
    table_boxes = [(table.box, (30, 40, 230)) for table in page.tables]
    cell_boxes = [(cell.box, (20, 155, 245)) for cell in cells]
    table_crop = page.tables[0].box if page.tables else None
    scale = min(1.0, (8_000_000 / gray.size) ** 0.5)
    working = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    binary = cv2.adaptiveThreshold(working, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    horiz, vert = _line_masks(working)
    grid = cv2.bitwise_or(horiz, vert)
    dark_input, dark_ids = blank_dark_cells(gray, [cell.box for cell in cells]) if cells else (gray, set())
    stages = []

    _stage(stages, "۰ · تصویر ورودی", f"فایل {source.name}؛ اندازهٔ تصویر رنگی {raw_color.shape[1]} × {raw_color.shape[0]} پیکسل.", [("تصویر اصلی", _render(raw_color, max_side=max_side))])
    _stage(stages, "۱۰ · صفحهٔ خاکستری", f"OpenCV تصویر را به آرایهٔ تک‌کاناله با ابعاد {input_gray.shape[1]} × {input_gray.shape[0]} تبدیل کرد.", [("صفحهٔ خاکستری", _render(input_gray, max_side=max_side))])
    candidates = [(f"چرخش {k * 90} درجه پادساعتگرد؛ امتیاز {scores[k]:.3f}", _render(np.ascontiguousarray(np.rot90(input_gray, k)), max_side=1200)) for k in range(4)]
    _stage(stages, "۲۰ · چهار جهت آزمایشی", "جهت‌یابی نسخهٔ کوچک‌شدهٔ هر چهار چرخش را با تشخیص باکس و اطمینان OCR می‌سنجد.", candidates)
    _stage(stages, "۲۵ · چرخش انتخاب‌شده", f"چرخش انتخاب‌شده: {turns * 90} درجه پادساعتگرد. این تصویر هنوز از تابع رفع کجی عبور نکرده است.", [("پس از چرخش", _render(np.ascontiguousarray(np.rot90(input_gray, turns)), max_side=max_side))])
    same_orientation = np.array_equal(selected, gray)
    _stage(stages, "۳۰ · تصویر صاف‌شده", f"زاویهٔ کجی گزارش‌شده: {skew:.2f} درجه؛ ابعاد خروجی {width} × {height}. تطابق با تصویر استفاده‌شده در اجرای اصلی: {'بله' if same_orientation else 'خیر'}.", [("خروجی جهت‌یابی و رفع کجی", _render(gray, max_side=max_side))])
    _stage(stages, "۴۰ · تایل بالایی", f"ردیف‌های ۰ تا {top_end} از تصویر صاف‌شده؛ آغاز ناحیهٔ هم‌پوشانی از ردیف {bottom_start} است.", [("برش بالایی", _render(top, max_side=max_side))])
    _stage(stages, "۴۵ · OCR تایل بالایی", f"Indra برای این تایل {len(top_lines)} باکس خط برگرداند. آبی: اطمینان کافی؛ قرمز: کمتر از {config.low_conf}.", [("باکس‌های خط روی تایل بالا", _render(top, _line_boxes(top_lines, config.low_conf), max_side=max_side))])
    _stage(stages, "۵۰ · تایل پایینی", f"ردیف‌های {bottom_start} تا {height}؛ هم‌پوشانی واقعی {top_end - bottom_start} ردیف است.", [("برش پایینی", _render(bottom, max_side=max_side))])
    _stage(stages, "۵۵ · OCR تایل پایینی", f"Indra برای این تایل {len(bottom_lines)} باکس خط برگرداند.", [("باکس‌های خط روی تایل پایین", _render(bottom, _line_boxes(bottom_lines, config.low_conf), max_side=max_side))])
    _stage(stages, "۶۰ · پاس مکمل سربرگ", f"۳۰٪ بالای صفحه ابتدا از تصویر صاف‌شده بریده می‌شود؛ پیکسل‌های روشن‌تر از ۱۳۵ سفید و سپس محو می‌شوند. پاس OCR مکمل {len(header_lines)} خط داد.", [("سربرگ پیش از پردازش", _render(header, max_side=max_side)), ("سربرگ پس از حذف واترمارک", _render(clean_header, max_side=max_side)), ("باکس‌های پاس مکمل", _render(clean_header, _line_boxes(header_lines, config.low_conf), max_side=max_side))])
    _stage(stages, "۶۵ · پاورقی کم‌رنگ", f"۱۰٪ پایین صفحه جدا بررسی شد و {len(footer_lines)} خط مکمل بازیابی شد.", [("نوار پایین و باکس‌های بازیابی‌شده", _render(gray, _line_boxes(footer_lines, config.low_conf), crop=(0, footer_y0, width, height), max_side=max_side))])
    rings = _stamp_rings(gray)
    stamp_images = [(f"نوار بازشدهٔ مهر {i + 1}", _render(ring, max_side=max_side)) for i, ring in enumerate(rings)]
    if not stamp_images:
        stamp_images = [("ناحیهٔ جست‌وجوی مهر؛ نوار قابل نمایش پیدا نشد", _render(gray, crop=(0, int(height * 0.35), width, height), max_side=max_side))]
    _stage(stages, "۶۸ · مهر دایره‌ای", f"کد پروژه حلقهٔ مهر را به نوار افقی تبدیل می‌کند؛ در این صفحه {len(stamp_lines)} خط مهر به OCR اضافه شد.", stamp_images)
    _stage(stages, "۷۲ · ادغام خطوط", f"مختصات دو تایل به صفحه برگشت و باکس‌های هم‌پوشان بر اساس موقعیت و اطمینان ادغام شدند؛ تعداد خطوط: {len(merged)}.", [("باکس‌های ادغام‌شده روی صفحه", _render(gray, _line_boxes(merged, config.low_conf), max_side=max_side))])
    _stage(stages, "۷۶ · بازخوانی موردی مبلغ", f"اصلاح شکل رقم در {len(amount_changes)} خط اثر گذاشت. سبز: خطی که متنش در این پاس تغییر کرده است.", [("پس از بازخوانی مبلغ‌های تیره", _render(gray, _line_boxes(amounts_repaired, config.low_conf, amount_changes), max_side=max_side))])
    _stage(stages, "۷۸ · بازخوانی قابل پرداخت", f"بازخوانی برچسب/عدد/واحد در صورت عبور از شرط‌ها انجام می‌شود. خطوط پس از این مرحله: {len(payable_recovered)}. سبز: خروجی تغییرکرده یا افزوده‌شده.", [("پس از بازخوانی قابل پرداخت", _render(gray, _line_boxes(payable_recovered, config.low_conf, final_changes), max_side=max_side))])
    _stage(stages, "۸۰ · تصویر دودویی جدول", f"برای کشف خطوط جدول، تصویر در صورت بزرگی به حداکثر حدود ۸ میلیون پیکسل کوچک می‌شود و آستانه‌گذاری تطبیقی می‌گیرد؛ ابعاد کار {working.shape[1]} × {working.shape[0]}.", [("نقشهٔ سیاه و سفید", _render(binary, max_side=max_side, png=True))])
    _stage(stages, "۸۴ · ماسک خط‌های جدول", "مورفولوژی، خط‌های افقی و عمودی را از نقشهٔ دودویی جدا می‌کند؛ اجتماع این دو ماسک مرزهای سلول را می‌سازد.", [("خط‌های افقی", _render(horiz, max_side=max_side, png=True)), ("خط‌های عمودی", _render(vert, max_side=max_side, png=True)), ("مرزهای ترکیب‌شده", _render(grid, max_side=max_side, png=True))])
    _stage(stages, "۸۷ · سلول‌های تیره", f"{len(dark_ids)} سلول تیره موقتاً در تصویر تشخیص خط سفید شد؛ متن همین سلول‌ها جداگانه از نسخه‌های روشن و تیره خوانده می‌شود.", [("ورودی تشخیص خط پس از سفیدکردن سلول‌های تیره", _render(dark_input, max_side=max_side))])
    table_images = [("باکس جدول و تمام سلول‌ها", _render(gray, table_boxes + cell_boxes, max_side=max_side))]
    if table_crop is not None:
        table_images.append(("نمای نزدیک جدول و سلول‌ها", _render(gray, table_boxes + cell_boxes, crop=table_crop, max_side=max_side)))
    _stage(stages, "۹۰ · سلول‌ها و جدول", f"پایپلاین {len(page.tables)} جدول و {len(cells)} سلول ساخت. نارنجی: سلول؛ قرمز: محدودهٔ جدول.", table_images)
    final_page = result["pages"][0]
    final_text = "\n\n".join([
        "raw_text:\n" + final_page["raw_text"],
        "text:\n" + final_page["text"],
        "text_dedup:\n" + final_page["text_dedup"],
        "tables_markdown:\n" + "\n".join(final_page["tables_markdown"]),
    ])
    extra = "<details><summary>متن‌های خروجی</summary><pre>" + html.escape(final_text) + "</pre></details>"
    extra += "<details><summary>JSON کامل صفحه</summary><pre>" + html.escape(json.dumps(final_page, ensure_ascii=False, indent=2)) + "</pre></details>"
    _stage(stages, "۱۰۰ · خروجی نهایی صفحه", f"اجرای اصلی {len(page.lines)} خط دارد؛ {len(final_page['low_confidence_lines'])} خط کم‌اطمینان و {len(final_page['review_queue'])} مورد مرور ثبت شد. فاکتور ساختاریافته: {'دارد' if final_page['invoice'] else 'شناسایی نشد'}. تطابق بازپخش با خطوط اجرای اصلی: {'بله' if replay_matches else 'خیر؛ این مرحله از خروجی اصلی رسم شده است'}.", [("باکس‌های نهایی OCR و جدول", _render(gray, _line_boxes(page.lines, config.low_conf) + table_boxes, max_side=max_side))], extra)
    return stages, result, replay_matches


def _html_document(stages: list[dict], result: dict, source: Path, replay_matches: bool) -> str:
    blocks = []
    for index, stage in enumerate(stages):
        figures = []
        for number, (label, data) in enumerate(stage["images"]):
            figures.append(
                f'<figure><figcaption>{html.escape(label)}</figcaption>'
                f'<div class="image-wrap"><img src="{data}" alt="{html.escape(label)}" loading="lazy"></div>'
                f'<button type="button" onclick="downloadImage(this,{index},{number})">دانلود تصویر این مرحله</button></figure>'
            )
        active = " active" if index == 0 else ""
        blocks.append(
            f'<section class="step{active}"><h2>{html.escape(stage["title"])}</h2>'
            f'<p>{html.escape(stage["detail"])}</p><div class="images">{"".join(figures)}</div>{stage["extra"]}</section>'
        )
    style = """
body{margin:0;background:#f3f5f8;color:#1c2733;font-family:Tahoma,Arial,sans-serif;direction:rtl}
header{background:#142d48;color:white;padding:18px 24px}h1{font-size:22px;margin:0 0 8px}header p{margin:0;line-height:1.9}
main{max-width:1600px;margin:auto;padding:18px}.toolbar{position:sticky;top:0;z-index:2;background:#fff;padding:10px 14px;display:flex;align-items:center;gap:12px;border:1px solid #d7dfe8;border-radius:10px}
button{background:#135d9d;color:white;border:0;border-radius:7px;padding:9px 15px;cursor:pointer;font:inherit}button:disabled{opacity:.4;cursor:default}
.step{display:none;background:white;border:1px solid #d7dfe8;border-radius:10px;padding:18px;margin-top:14px}.step.active{display:block}.step h2{margin:0 0 10px}.step p{line-height:1.9}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:14px}figure{margin:0;border:1px solid #d9e1ea;border-radius:8px;padding:10px;min-width:0}figcaption{font-weight:bold;margin-bottom:8px}
.image-wrap{max-height:78vh;overflow:auto;background:#eef2f5;text-align:center}.image-wrap img{display:block;max-width:100%;height:auto;margin:auto;cursor:zoom-in}.image-wrap img.zoom{max-width:none;cursor:zoom-out}
figure button{margin-top:10px}details{margin-top:14px;border:1px solid #d7dfe8;border-radius:8px;padding:10px}summary{cursor:pointer;font-weight:bold}
pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;direction:rtl;text-align:right;background:#f8fafc;padding:12px;border-radius:6px}
.note{font-size:13px;color:#4e6072;margin:12px 4px;line-height:1.8}
"""
    script = """
const steps=[...document.querySelectorAll('.step')];let current=0;
function showStep(next){current=Math.max(0,Math.min(steps.length-1,next));steps.forEach((step,i)=>step.classList.toggle('active',i===current));document.getElementById('progress').textContent=`مرحله ${current+1} از ${steps.length}`;document.getElementById('prev').disabled=current===0;document.getElementById('next').disabled=current===steps.length-1;window.scrollTo({top:0,behavior:'auto'});}
document.getElementById('prev').onclick=()=>showStep(current-1);document.getElementById('next').onclick=()=>showStep(current+1);
document.querySelectorAll('.image-wrap img').forEach(img=>img.onclick=()=>img.classList.toggle('zoom'));
function downloadImage(button,stage,image){const img=button.closest('figure').querySelector('img');const a=document.createElement('a');a.href=img.src;a.download=`pipeline-stage-${String(stage+1).padStart(2,'0')}-${image+1}.${img.src.startsWith('data:image/png')?'png':'jpg'}`;a.click();}
showStep(0);
"""
    notice = "بازپخش مراحل OCR با اجرای نهایی تطابق داشت." if replay_matches else "بازپخش مراحل OCR با اجرای نهایی تفاوت داشت؛ پنل آخر از خروجی اصلی رسم شده است."
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>ردگیری تصویری پایپلاین OCR — {html.escape(source.name)}</title><style>{style}</style></head><body>'
        f'<header><h1>ردگیری تصویری پایپلاین Aftab OCR</h1><p>ورودی: {html.escape(str(source))} · زمان اجرای اصلی: {result["time_sec"]} ثانیه · {len(stages)} مرحله</p></header>'
        '<main><div class="toolbar"><button id="prev">مرحلهٔ قبل</button><strong id="progress"></strong><button id="next">مرحلهٔ بعد</button></div>'
        f'<p class="note">همهٔ تصاویر داخل همین فایل HTML هستند و برای دیدنشان اینترنت لازم نیست. روی تصویر کلیک کنید تا بزرگ شود. آبی: باکس OCR؛ قرمز: خط کم‌اطمینان یا محدودهٔ جدول؛ نارنجی: سلول؛ سبز: خوانش تغییرکرده. {html.escape(notice)}</p>'
        + "".join(blocks) + f'<script>{script}</script></main></body></html>'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one self-contained HTML report with visual images from every image stage of Aftab OCR")
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-side", type=int, default=3000)
    args = parser.parse_args()
    source = args.file.resolve()
    if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
        parser.error("The input must be an existing supported image file")
    if not 800 <= args.max_side <= 6000:
        parser.error("--max-side must be between 800 and 6000")
    target = (args.out or source.with_name(source.stem + "_pipeline_trace.html")).resolve()
    stages, result, replay_matches = _report(source, args.max_side)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_html_document(stages, result, source, replay_matches), encoding="utf-8")
    print(f"Saved {len(stages)} visual stages to {target}")
    print(f"Replay matches main pipeline: {replay_matches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
