# مرجع کد: هر فایل، هر فانکشن، دقیقاً چه می‌کند

کد عمداً هیچ کامنتی ندارد. توضیح تفصیلی همه‌چیز اینجاست.
ترتیب فایل‌ها همان ترتیب جریان داده است: ورودی ← پایپ‌لاین ← جدول و فاکتور ← قواعد متنی ← خروجی ← ارزیابی.

## جریان داده در یک نگاه

```
فایل (PDF/تصویر)
  → pdfio.iter_gray_pages            آرایه خاکستری هر صفحه (۳۰۰ dpi)
  → orientation.robust_upright       صفحه صاف‌شده
  → pipeline._recognize_lines        خطوط (Line: box, text, conf) با Tiling و بهبودهای تصویری
  → tables.extract_tables            جدول سلول‌به‌سلول (Table)
  → pipeline._build_page             متن، اصلاح‌ها، صف مرور + invoice.parse_invoice
  → invoice.reconcile_document       چک‌های سطح کل سند
  → report.write_outputs             txt + json + html
```

نتیجه `process_document` یک dict است:

| کلید | معنی |
|---|---|
| `file`، `time_sec` | نام فایل و زمان OCR (ثانیه) |
| `pages[i].raw_text` | متن همه خطوط قبل از پس‌پردازش |
| `pages[i].text` | متن بعد از پس‌پردازش (checksum، تاریخ، ...) |
| `pages[i].text_dedup` | **متن کامل و مرتب**: خطوط بیرون جدول و ردیف‌های جدول (markdown) به ترتیب عمودی صفحه، بدون تکرار، به‌علاوه‌ی «خطوط تکمیلی»؛ فایل `.txt` دانلودی و مبنای ارزیابی |
| `pages[i].corrections` | اصلاح‌های خودکار انجام‌شده |
| `pages[i].review_queue` | موارد نیازمند مرور انسانی |
| `pages[i].low_confidence_lines` | خطوط با اطمینان کمتر از `low_conf` |
| `pages[i].tables_markdown` | جدول‌ها به markdown |
| `pages[i].invoice` | فاکتور ساختاریافته یا `None` |

---

# بسته `persian_ocr/`

## `__init__.py`
- با وارد شدن بسته `setup_environment()` اجرا می‌شود تا `TEMP`/`TMP`/`HF_HOME` قبل از بارگذاری کتابخانه‌های سنگین به `.cache/` داخل پروژه بروند.
- `__version__`: شماره نسخه. ماژول‌های سنگین (onnx، opencv) اینجا import نمی‌شوند.

## `__main__.py`
`python -m persian_ocr` را به `cli.main()` وصل می‌کند و کد خروج را برمی‌گرداند.

## `config.py`
**ثابت‌ها**
- `PACKAGE_DIR`، `ROOT`: مسیر بسته و ریشه پروژه.
- `MODEL_DIR`: متغیر محیطی `PERSIAN_OCR_MODEL_DIR` یا `ROOT/indra-ocr`.
- `CACHE_DIR` (`.cache`)، `TMP_DIR` (`.cache/tmp`)، `OUTPUT_DIR` (`output`)، `REPORTS_DIR` (`reports`)، `EVAL_DATA_DIR` (`eval_data`)، `LEXICON_PATH` (`persian_ocr/data/domain_lexicon.json`).
- `IMAGE_SUFFIXES`: پسوندهایی که تصویر حساب می‌شوند (png، jpg، jpeg، bmp، tif، tiff، webp).

**`setup_environment()`**
پوشه `TMP_DIR` را می‌سازد، `TEMP` و `TMP` را به آن می‌برد، `HF_HOME` را (اگر از قبل نباشد) به `.cache/huggingface` می‌برد و `INDRA_OCR_MODEL_DIR` را به `MODEL_DIR` تنظیم می‌کند. هدف: هیچ فایلی روی درایو C نوشته نشود.

**`PipelineConfig`** (dataclass فقط‌خواندنی)
| فیلد | پیش‌فرض | کار |
|---|---|---|
| `dpi` | 300 | وضوح رندر PDF |
| `tiling` | True | دو تایل هم‌پوشان |
| `overlap_ratio` | 0.18 | سهم هم‌پوشانی دو تایل از ارتفاع |
| `engineered` | True | همه تکنیک‌ها (جهت‌یابی، Force-RTL، بهبود تصویر، جدول، پس‌پردازش). False = خط پایه |
| `tables` | True | استخراج جدول (فقط وقتی `engineered` است) |
| `header_fraction` | 0.30 | سهمی از بالای صفحه که واترمارک‌زدایی می‌شود |
| `low_conf` | 0.75 | آستانه «خط کم‌اطمینان» |
| `use_lexicon` | True | دیکشنری سازمان |
| `max_pages` | 0 | 0 = همه صفحات |

`baseline(tiling)`: کانفیگ خط پایه؛ `engineered=False`، `tables=False`، `use_lexicon=False`.

## `engine.py`
**`OcrEngine`** (dataclass با `ort` و `conv`)
- `load(threads=4, dpi=300.0)`: `OrtOCR` را با مدل‌های `MODEL_DIR` می‌سازد: `adaptive=True` (اگر متن ریز باشد یک پاس تشخیص دوم با رزولوشن بالاتر)، `furniture=True` (سربرگ و پاورقی حفظ شوند)، `table_heads=False`، `math=False`، فقط `CPUExecutionProvider`. سپس `Converter` را با `mode="ocr"` (همیشه OCR، نه لایه متنی PDF) می‌سازد.
- `force_rtl()`: context manager. `ort.line_groups` را موقتاً با تابعی جایگزین می‌کند که **همه** خطوط را `"rtl"` و «مطمئن» برمی‌گرداند؛ در `finally` تابع اصلی را برمی‌گرداند. دلیل: `script.onnx` سطرهای کوتاه تاریخ و دوزبانه را به مدل لاتین می‌فرستاد.

## `pdfio.py`
- `is_image(path)`: پسوند در `IMAGE_SUFFIXES` است؟
- `_read_image(path, flags)`: با `np.fromfile` + `cv2.imdecode` می‌خواند (چون `cv2.imread` روی مسیر غیر ASCII ویندوز شکست می‌خورد). اگر خوانده نشد `ValueError`.
- `_to_gray(arr)`: BGRA یا BGR را به خاکستری تبدیل می‌کند.
- `iter_gray_pages(path, dpi, max_pages)`: generator صفحه‌ها. تصویر = یک صفحه. PDF: هر صفحه با `render(scale=dpi/72)`؛ سند در `finally` بسته می‌شود.
- `load_gray_page(path, page, dpi)`: فقط یک صفحه (شماره از ۱) بدون رندر صفحه‌های قبلی؛ `IndexError` اگر صفحه نباشد.
- `preview_jpeg(path, page_idx, dpi=110, quality=80)`: پیش‌نمایش JPEG رنگی (بایت‌ها) به‌علاوه‌ی عرض و ارتفاع پیکسلی؛ داشبورد از ابعاد برای چرخاندن تصویر استفاده می‌کند.
- `preview_jpeg_b64(path, page_idx, dpi=110, quality=80)`: همان پیش‌نمایش به صورت base64 برای گزارش HTML.

## `orientation.py`
- `orientation_score(ort, gray)`: تصویر را نصف می‌کند، خطوط را تشخیص می‌دهد؛ «افقی» یعنی عرض > ۲×ارتفاع. ۱۲ خط افقی پهن‌تر را می‌خواند. امتیاز = (سهم خطوط افقی) × (میانگین اطمینان خواندن). بدون خط → ۰.
- `robust_upright(ort, gray)`: امتیاز هر ۴ چرخش (`np.rot90`, k=0..3) را حساب می‌کند، بهترین را برمی‌دارد و با `ort.upright(turn=False)` فقط کجی جزئی را رفع می‌کند. خروجی: (تصویر، تعداد ربع‌چرخش، زاویه کجی، امتیازها).

## `tiling.py`
- `tile_bounds(height, overlap_ratio)`: (پایان تایل بالا، شروع تایل پایین). مثال: ارتفاع ۱۰۰۰ و ۰.۱۸ ← (۵۹۰، ۴۱۰)؛ ۱۸٪ ارتفاع هم‌پوشان است.
- `line_iou(box1, box2)`: نسبت اشتراک به اجتماع دو جعبه.
- `merge_lines(base, extra, y_offset)`: خطوط پایه را (با متن trim‌شده و غیرخالی) نگه می‌دارد. هر خط `extra` پس از افزودن `y_offset` به y با خطوط موجود مقایسه می‌شود؛ «همان خط» است اگر IoU > 0.20 **یا** هم‌پوشانی عمودی > ۵۵٪ ارتفاع کمینه و هم‌پوشانی افقی > ۵۰٪ عرض کمینه. اگر همان خط بود، خط با `conf` بالاتر می‌ماند؛ وگرنه افزوده می‌شود.
- `merge_tiles(top, bottom, bottom_y0)`: `merge_lines` + مرتب‌سازی: ابتدا y گردشده به مضرب ۳۰ پیکسل (هم‌ردیف شدن)، بعد `-x0` (راست به چپ).

## `pipeline.py`
- `PageOcr`: خطوط (`lines`) و جدول‌های (`tables`) یک صفحه.
- `_recognize_lines(engine, gray, config)`: اگر `tiling=False` همان `conv.ocr` روی کل صفحه. وگرنه صفحه را به تایل بالا/پایین می‌شکند و هر دو را می‌خواند. در حالت `engineered`:
  1. سربرگ (بالای `header_fraction` ارتفاع تایل بالا) با `watermark_suppress` دوباره خوانده و ادغام می‌شود.
  2. `recover_footer_segments` روی کل صفحه؛ خطوطش با `y_offset=-bottom_start` به تایل پایین ادغام می‌شوند.
  3. مهرهای دایره‌ای با `unwrap_circular_stamps`؛ مختصاتشان نسبت به تایل پایین جابه‌جا و اضافه می‌شود.
  در پایان `merge_tiles`.
- `PageHook`: نوع تابع `on_page(idx, gray, page)`.
- `ocr_page(engine, gray, config, on_page=None, idx=0)`: در حالت `engineered` داخل `force_rtl()` ابتدا `robust_upright`، بعد `_recognize_lines`، بعد `extract_tables` (اگر `tables=True`). اگر `on_page` داده شود، بعد از خواندن صفحه با **تصویر هم‌جهت‌شده‌ای که OCR دیده** صدا زده می‌شود (مثلاً برای برش گرفتن از همان تصویر، چون مختصات خطوط و سلول‌ها مال همان تصویر است). تصویر نگه داشته نمی‌شود، پس مصرف رم بالا نمی‌رود.
- `ocr_document(engine, path, config, on_page=None)`: روی همه صفحه‌ها `ocr_page`؛ خروجی (لیست `PageOcr`، زمان).
- `_cell_of(line, tables, margin=8)`: سلولِ **دارای متن** که مرکز خط داخل آن است (با ۸ پیکسل حاشیه)، وگرنه `None`. عمداً با جعبه‌ی بیرونی جدول سنجیده نمی‌شود: آن جعبه اجتماع همه‌ی سلول‌هاست و عنوان و برچسب‌های بین سلول‌ها (مثل «صورت حساب فروش»، «شماره سریال»، «مشخصات فروشنده») را هم می‌بلعید و حذف می‌کرد.
- `_covered(text, cell_text)`: آیا متن خط در متن سلول هست؟ ارقام و نویسه‌ها نرمال می‌شوند؛ هر توکن (حداقل ۲ نویسه) یا زیررشته‌ی متن سلول است یا شباهت `SequenceMatcher` ≥ ۰٫۸ با یکی از توکن‌های سلول دارد (عددی که یک رقم فرق دارد یا `تھران` در برابر `تهران` تکراری حساب می‌شود، نه خط تازه). اگر ≥ ۶۰٪ توکن‌ها پوشش داده شوند، خط «پوشش‌داده‌شده» است.
- `_digit_strings(text)`: رقم‌های هر عدد متن (ارقام و جداکننده نرمال، فقط عددهای ≥۳ رقم)، مثلاً `٣,٢٠٠,٠٠٠` ← `3200000`.
- `_reading_conflicts(line, cell)`: **هشدار تعارض.** اگر عددی در خط صفحه دقیقاً در عددهای سلول نیست ولی با یکی از آن‌ها شباهت ≥ ۰٫۸ دارد (اختلاف طول ≤۱؛ یعنی فقط چند رقم فرق دارد)، دو خوانش «تعارض» دارند. این حالت قبلاً ساکت «پوشش‌داده‌شده» حساب می‌شد و خط (که ممکن بود درست باشد) دور ریخته می‌شد. اکنون یک ورودی `reading_conflict` ساخته می‌شود: `input` = رقم‌های خوانش سلول (همان که در متن مانده)، `candidates` = [رقم‌های خوانش خط]، `status: ambiguous_review`، `note: cell_vs_line`، `context` = متن خط، و `cell_conf` و `line_conf` = اطمینان دو خوانش. **متن خروجی تغییر نمی‌کند** (حدس نمی‌زند کدام درست است)؛ فقط به `review_queue` می‌رود تا انسان ببیند. بدون وابستگی به اطمینان خط، چون تعارض بین دو خوانش خودش علامت است.
  - **اندازه‌گیری روی ۸ سند (با GT ماسک‌شده؛ in-sample):** ۸۶ تعارض: **۲۰** مورد «خط درست، سلول غلط» (گرفتن خطای واقعی، مثل `350,000,000` ← `250,000,000` یا `30000067` ← `0000067`)، **۳۷** هشدار الکی (سلول درست، خط غلط)، ۴ مورد هر دو عدد در GT، ۲۵ مورد نامشخص (عدد ماسک‌شده/کوتاه). متن خروجی در هر ۸ سند **بی‌تغییر** ماند. ۵۸ از ۸۶ مورد در فاکتور ۱۵ صفحه‌ای `27153` است.
  - **دقت هشدار ≈ ۳۵٪** (۲۰ از ۵۷ مورد برچسب‌دار). **اطمینان دو خوانش آن‌ها را جدا نمی‌کند**: هشت قاعده‌ی اطمینان آزموده شد؛ بهترین (`cell_conf < 0.75`) دقت را به ۵۴٪ می‌رساند ولی فقط ۷ از ۲۰ مورد درست را نگه می‌دارد. به همین دلیل فیلتر اطمینان **عمداً گذاشته نشد** (قاعده‌ی تنظیم‌شده روی همین ۸ سند خوش‌بینانه می‌شد).
- `_compose_text(lines, tables, config)`: **`(متن، فهرست تعارض‌ها)` برمی‌گرداند.** تعارض‌های تکراری یک بار می‌آیند. متن کامل و مرتب صفحه. خطوط بیرون سلول‌ها به ترتیب اصلی می‌آیند و ردیف‌های markdown جدول (با y میانگین سلول‌ها) درست در جای عمودی خودشان وارد می‌شوند، نه همه ته متن. هر دسته‌ی پیوسته از خطوط جداگانه `postprocess_text` می‌شود. خطی که داخل سلول است ولی متن سلول پوشاندنش را نمی‌دهد، اگر اطمینانش ≥ `low_conf` باشد (۰٫۷۵) زیر عنوان `[خطوط تکمیلی از ناحیه جدول]` ته صفحه می‌آید؛ کم‌اطمینان‌ها (نویز) فقط در `raw_text` و `low_confidence_lines` می‌مانند. روی ۸ سند: ۱۷۵۳ خطِ با اطمینان بالا، ۱۴ مورد (تقریباً همه خوانش‌های تکراری با یک رقم یا نویسه اختلاف) در `text_dedup` نیستند.
- `_build_page(idx, page, config)`: برای یک صفحه:
  - `raw` = متن همه خطوط غیرخالی؛ `raw_outside` = فقط خطوط بیرون جدول.
  - `invoice` = اولین جدولی که `parse_invoice` برایش خروجی بدهد (`page_text=raw` برای سربرگ‌های بیرون جدول).
  - در `engineered`: `postprocess_text` روی `raw` و `raw_outside`. در خط پایه: متن خام.
  - `text_dedup` = `_compose_text`: متن کامل و مرتب (هر چیز یک بار، به‌علاوه‌ی خطوط تکمیلی).
  - `low_confidence_lines` = خطوطی با `conf < low_conf`.
- `process_document(engine, path, config, on_page=None)`: `ocr_document` ← `_build_page` برای هر صفحه ← `reconcile_document` روی فاکتورهای همه صفحه‌ها.

## `cli.py`
- `COMMANDS = {"run", "debug", "serve"}`.
- `_build_parser()`: زیردستورها. `run`: `file`، `--out`، `--no-lexicon`، `--no-html`، `--no-tables` (بدون جدول و فاکتور، برای آزمون)، `--max-pages`. `debug`: `file`، `--page`. `serve`: `--host`، `--port`.
- `_run(args)`: فایل را چک می‌کند، `OcrEngine.load()`، `process_document`، `write_outputs`، و خلاصه (اصلاح خودکار، نیازمند بررسی، خطوط کم‌اطمینان) چاپ می‌شود. فایل ناموجود ← کد ۱.
- `_debug(args)`: یک صفحه را با `load_gray_page` می‌گیرد، داخل `force_rtl` صاف و جدول‌هایش را استخراج می‌کند و markdown جدول + JSON فاکتور را در `.cache/debug/<نام>_p<N>.md` می‌نویسد.
- `_serve(args)`: `api.server.serve` را با میزبان و پورت اجرا می‌کند.
- `main(argv)`: خروجی کنسول UTF-8 (ویندوز). اگر آرگومان اول نه دستور است نه گزینه، `run` به ابتدایش اضافه می‌شود (`python -m persian_ocr فایل.pdf`).

---

## `vision/` — بهبودهای تصویری

### `watermark.py`
`watermark_suppress(gray, threshold=135)`: کپی تصویر؛ پیکسل‌های روشن‌تر از آستانه سفید (۲۵۵) می‌شوند؛ سپس Gaussian blur ‏3×3. لوگوی خاکستری و خط تای کاغذ حذف می‌شود، متن تیره می‌ماند.

### `footer.py`
`recover_footer_segments(ort, gray)`: نوار ۱۰٪ پایین صفحه را تشخیص می‌دهد. برای هر باکس عریض (عرض ≥ ۳۵٪ صفحه): باکس را به پنجره‌های افقی با گام نصف پنجره (پنجره = بزرگ‌ترین مقدار از ۱۲۰ پیکسل و یک‌ششم عرض) می‌شکند. برای هر پنجره، ارتفاع محلی را از ردیف‌هایی که بیش از ۲٪ پیکسل تیره (< ۲۱۰) دارند «تنگ» می‌کند؛ فقط ارتفاع ۱۴ تا ۳۶ پیکسل پذیرفته می‌شود (غیر این یعنی متن نیست یا هنوز کج است). هر پنجره جدا خوانده می‌شود و اگر اطمینانش ≥ ۰.۴۸ باشد، متن اضافه می‌شود. متن‌ها با ` | ` به یک `Line` با `conf=0.82` تبدیل می‌شوند.

### `stamps.py`
- `_read_strip(ort, strip)`: روی نوار افقیِ حلقه، پنجره‌هایی به عرض ۲۲٪ و گام یک‌چهارم پنجره (حداقل ۷۰) از ۱۵٪ تا ۸۵٪ طول می‌لغزاند. دو چیز برمی‌گرداند: بهترین پنجره متنی (اطمینان ≥ ۰.۵۲ و طول ≥ ۸ نویسه) و پنجره‌ای که بیشترین رقم (≥ ۳) را دارد (اطمینان ≥ ۰.۴۸)، اگر با اولی فرق دارد.
- `unwrap_circular_stamps(ort, gray)`: در ۶۵٪ پایین صفحه با `HoughCircles` (شعاع ۱۳۰ تا ۲۳۰) حداکثر ۲ دایره می‌یابد. دایره بدون حلقه جوهر (کمتر از ۵٪ پیکسل تیره‌تر از ۱۸۰) تشخیص کاذب است و رد می‌شود. ناحیه با `cv2.warpPolar` به مختصات قطبی تبدیل، دو بار پشت هم چسبانده (تا متنی که از مرز ۰/۳۶۰ درجه می‌گذرد پیوسته بماند) و حلقه ۷۰٪ تا ۹۱٪ شعاع بریده می‌شود. نیم‌دایره بالایی با چرخش خلاف عقربه و پایینی در جهت عقربه صاف و خوانده می‌شود. خروجی `Line` با متن `[مهر دایره‌ای: ...]` و `conf=0.78`.

---

## `tables/` — جدول‌های خط‌دار

### `models.py`
- `BBox = (x0, y0, x1, y1)`.
- `Cell`: `box`، `text`، `conf`. `Table`: `box` (کل جدول) و `rows` (لیست ردیف‌ها، هر ردیف لیست `Cell`).

### `cells.py`
- `_line_masks(gray)`: آستانه‌گذاری تطبیقی (میانگین، بلوک ۲۵، ثابت ۱۵، معکوس). خطوط افقی با `MORPH_OPEN` و هسته‌ای به عرض `max(40, W//35)`، خطوط عمودی با هسته‌ای به ارتفاع `max(30, H//70)`. سپس هر دو با `dilate` (۹×۳ و ۳×۹) ضخیم می‌شوند تا شکاف‌های کوچک خط اسکن‌شده بسته شود.
- `find_cells(gray, min_w=40, min_h=28)`: اجتماع خطوط افقی و عمودی معکوس می‌شود؛ هر ناحیه سفیدِ همبند (connected component، ۴-همسایگی) یک سلول کاندید است. رد می‌شود اگر: کوچک‌تر از حداقل باشد؛ پس‌زمینه بیرون جدول باشد (عرض > ۹۷٪ صفحه و ارتفاع > ۵۰٪)؛ یا نامنظم باشد (مساحت < ۶۰٪ مستطیل محیطی).
- `group_rows(cells)`: سلول‌ها بر اساس مرکز عمودی مرتب می‌شوند. سلول جدید به ردیف آخر می‌پیوندد اگر فاصله مرکزش از میانگین مرکز ردیف < ۰.۵ × کمینه (ارتفاع سلول، میانگین ارتفاع ردیف) باشد. هر ردیف راست به چپ مرتب می‌شود (`-x1`).

### `dark.py`
- `DARK_CELL_MEDIAN = 150`: سلولی با میانه روشنایی کمتر از این «تیره» است (سرستون هاف‌تون).
- `_variants(reg)`: دو نسخه از سلول: «متن تیره روی زمینه تیره» (کشش کنتراست بین صدک ۲ و ۸۵٪ میانه) و «متن روشن» (وارون با مرجع صدک ۹۸). قبل از هر دو median blur ۳.
- `_line_boxes_by_projection(img)`: خطوط را از پروجکشن افقی جوهر پیدا می‌کند (ردیف با > ۱٪ پیکسل تیره؛ فاصله تا ۶ ردیف خالی پل می‌شود). فقط ارتفاع ۱۲ تا ۹۰ و حداقل ۵ ستون جوهری (> ۲٪) پذیرفته می‌شود.
- `read_dark_cell(ort, region)`: هر دو نسخه (با حاشیه سفید ۱۰ پیکسل) را می‌خواند و نسخه‌ای را برمی‌گرداند که میانگین اطمینانش بیشتر است.
- `blank_dark_cells(gray, cells, pad=5)`: سلول‌های تیره را در کپیِ تصویر سفید می‌کند (تا detector صفحه گیج نشود) و اندیس‌شان را برمی‌گرداند.

### `lines.py`
- `_tight_y(gray, x0, y0, x1, y1)`: بالا و پایین واقعی جوهر (ردیف‌های با > ۱٪ پیکسل < ۲۰۰).
- `assign_lines_to_cells(gray, page_boxes, cells, pad=6)`: هر خط تشخیص‌داده‌شده صفحه به سلولی تعلق می‌گیرد که مرکز عمودی‌اش در آن است. جعبه با مرز داخلی سلول بریده می‌شود (خط‌کشی جدول جزو متن نشود)، حداقل ۱۲ پیکسل عرض و ۸ ارتفاع، و عمودی تنگ می‌شود. سلول بدون خط تشخیص‌داده‌شده به `_ink_fallback` می‌رود.
- `_ink_fallback(gray, ix0, iy0, ix1, iy1)`: اگر بیش از ۱۵ پیکسل جوهر (< ۱۵۰) هست، کل ناحیه جوهر یک خط است (ارتفاع ۱۰ تا ۷۰). عرض حداقل ±۱۴ پیکسل دور مرکز؛ برای رقم تک «۱» که چند ده پیکسل بیشتر جوهر ندارد.

### `extract.py`
- `extract_tables(ort, gray, min_cells=6)`: ۱) `find_cells`؛ کمتر از ۶ سلول ⇒ جدولی نیست. ۲) سلول‌های تیره سفید می‌شوند. ۳) تشخیص خطوط **یک بار** روی کل صفحه. ۴) تخصیص خطوط به سلول‌ها. ۵) همه برش‌ها یکجا (batch) به recognizer؛ متن با `flip` به ترتیب منطقی. ۶) سلول‌های تیره جدا با `read_dark_cell`. ۷) متن هر سلول از برش‌هایش (مرتب بر اساس ردیف، سپس راست به چپ) ساخته می‌شود؛ `conf` میانگین اطمینان. ۸) `Table` با ردیف‌های `group_rows`. خروجی همیشه لیستی با حداکثر یک جدول.
- `row_to_markdown(row)`: یک ردیف ← `| a | b |`؛ سلول خالی حذف و `|` داخل متن به `/` تبدیل می‌شود؛ ردیف تماماً خالی ← `None`.
- `table_to_markdown(table)`: ردیف‌های `row_to_markdown` با خط جدید.

---

## `text/` — قواعد متنی تعیینی

### `normalize.py`
- `_PERSIAN_DIGITS`، `_ARABIC_TO_PERSIAN`: جدول‌های ترجمه (ارقام فارسی/عربی ← لاتین؛ `ي`←`ی`، `ك`←`ک`، `ۀ`←`ه`، `ٱ`←`آ`).
- `_INVISIBLE`: نیم‌فاصله (ZWNJ)، ZWSP، کنترل‌های جهت و BOM. `_DECORATIVE`: ایموجی‌های سربرگ/پاورقی. `_SPACES`: انواع فاصله و tab.
- `normalize_digits(text)`: ارقام فارسی و عربی به لاتین.
- `normalize(text)`: NFC، ترجمه حروف عربی، حذف نامرئی‌ها، ایموجی به فاصله، یکسان‌سازی فاصله‌ها، فاصله‌های تکراری به یکی، trim. ساختار خطوط تغییر نمی‌کند.

### `validators.py`
- `is_valid_nid(nid10)`: کد ملی. ۱۰ رقم، همه رقم‌ها یکسان رد. `r = (Σ digit[i] × (10−i)) mod 11` برای ۹ رقم اول؛ رقم آخر باید `r` باشد اگر `r < 2`، وگرنه `11 − r`.
- `is_valid_legal_id(legal11)`: شناسه ملی حقوقی. هر یک از ۱۰ رقم اول با (رقم دهم + ۲) جمع و در ضریب `[29, 27, 23, 19, 17, 29, 27, 23, 19, 17]` ضرب می‌شود؛ مجموع mod 11؛ باقیمانده ۱۰ ⇒ ۰؛ رقم آخر باید برابر باشد.
- `is_valid_ir_iban(iban)`: شبا. `IR` و فاصله و خط‌تیره حذف؛ ۲۴ رقم؛ دو رقم کنترل به انتهای رشته منتقل و `1827` (= I=18, R=27) پیش از آن گذاشته می‌شود؛ باقیمانده mod 97 باید ۱ باشد (محاسبه رقم‌به‌رقم).
- `is_valid_postal_code(code)`: ۱۰ رقم که با صفر شروع نشود.

### `correction.py`
- `CONFUSION_PAIRS` و `CONFUSION_MAP`: جفت ارقامی که در فونت چاپی فارسی شبیه‌اند (مثلاً `4↔6↔9`، `2↔3`). نگاشت **متقارن** ساخته می‌شود (`_symmetric`): اگر `9` ممکن است `4` خوانده شود، `4` هم کاندید `9` دارد؛ وگرنه رقم درست هیچ‌وقت کاندید نمی‌شد و یک کاندید معتبرِ غلط «یکتا» حساب می‌شد.
- `_CHECKERS`: برای هر نوع (`nid`، `legal`، `iban`) طول انتظار و تابع اعتبارسنج.
- `variants_confusion(s)`: همه رشته‌هایی که یک رقم را با رقم‌های درهم‌تنمه عوض می‌کنند. هر سه تابع `variants_*` تکراری‌ها را با `dict.fromkeys` با حفظ ترتیب حذف می‌کنند.
- `variants_dup_insert(s)`: هر رقم را در جای خودش تکرار می‌کند (طول L ← L+1)؛ برای خطای CTC که `99` را `9` می‌کند.
- `variants_dup_delete(s)`: یکی از دو رقم تکراری مجاور را حذف می‌کند (L ← L−1).
- `_result(...)`: ساخت dict `{input, output, status, candidates[, note]}`.
- `correct_by_checksum(candidate, kind)`: وضعیت‌ها:
  - طول یکی کم (نامعتبر ⇒ `wrong_length`): کاندیدهای `dup_insert` معتبر؛ **دقیقاً یکی** ⇒ `auto_corrected`، چندتا ⇒ `ambiguous_review`.
  - طول یکی زیاد: کاندیدهای `dup_delete`؛ دقیقاً یکی ⇒ اصلاح.
  - طول درست و معتبر ⇒ `valid`.
  - طول درست و نامعتبر: کاندیدهای `confusion` معتبر؛ دقیقاً یکی ⇒ `auto_corrected`، بیش از یکی ⇒ `ambiguous_review` (**بدون حدس**).
  - غیر از این ⇒ `invalid_review`. نوع ناشناخته ⇒ `unknown_kind`. برای `iban` فقط اعتبارسنجی (بدون حدس).

### `dates.py`
`normalize_jalali_dates(text, corrections, review)` به ترتیب (ماه ۱ تا ۱۲ و روز ۱ تا ۳۱ وگرنه دست نمی‌خورد):
1. فاصله/نقطه به جای اسلش: `1402/ 11/ 12` و `1405.3/30` ← `1405/03/30` (سال ۱۳xx/۱۴xx؛ ماه و روز دو رقمی می‌شوند).
2. اسلش دوم افتاده: `1402/1115` ← `1402/11/15` اگر ماه ۱ تا ۱۲ و روز ۱ تا ۳۱.
3. «مورخ» + روز یک‌رقمی با نقطه: `مورخ .1405/033` **اصلاح نمی‌شود**؛ چون `03`، `30` و `31` همه ممکن‌اند، با وضعیت `ambiguous_review` و همه کاندیدها به `review` می‌رود.
4. صفر اضافه در سال: `14020/11/12` ← `1402/11/12`.
مواردی که بند ۲ و ۴ اصلاح می‌کنند در `corrections` ثبت می‌شوند.

### `accounting.py`
`reconcile_capital_shares(text, corrections)`: عبارت «مبلغ X میلیارد ریال منقسم به Y سهم با نام Z ریالی» را با regex می‌یابد. ارزش اسمی `10000` فقط وقتی به `1000` اصلاح می‌شود (جداکننده هزارگان رقم خوانده شده) که Y با `10000` **نخورد** و با `1000` **دقیقاً** بخورد؛ این اصلاح هم ثبت می‌شود. `انتظار = X × ۱۰⁹ ÷ Z`. اگر `Y ≠ انتظار` **و** ۳ رقم اول یکی است (خطا فقط در صفرها/جداکننده)، Y با `انتظار` جایگزین و اصلاح ثبت می‌شود. در غیر این صورت دست نمی‌خورد.

### `lexicon.py`
- `_load()`: فایل دیکشنری را یک بار (با `lru_cache`) می‌خواند؛ خطا ⇒ دیکشنری خالی.
- `apply_domain_lexicon(text, corrections)`: برای هر موجودیت: اگر هیچ `trigger` در متن نیست رد. برای هر فیلد، اگر مقدار ثبت‌شده از قبل در متن هست رد؛ وگرنه اولین `context_pattern` که در متن بخورد یعنی «نشانه‌ای از همان فیلد دیده شد» و اصلاح ثبت می‌شود. در پایان برچسب `[تطبیق دیکشنری سازمان: ...]` به انتهای متن افزوده می‌شود.
- ساختار `data/domain_lexicon.json`: `entities[]` با `triggers`، `canonical_name` و `fields{نام: {value, context_patterns[]}}`.

### `postprocess.py`
- `_CONTEXT_NID`: «شماره/کد ملی» + ۹ تا ۱۱ رقم. `_CONTEXT_LEGAL`: «شناسه ملی» + ۱۰ تا ۱۲ رقم (دامنه یکی کم/زیاد برای خطای CTC).
- `_fix_ids(text, pattern, kind, corrections, review)`: روی هر تطبیق `correct_by_checksum`؛ `auto_corrected` ⇒ جایگزین و ثبت؛ وضعیت‌های `ambiguous_review`/`invalid_review`/`wrong_length` ⇒ به `review_queue`.
- `postprocess_text(raw_text, use_lexicon)`: به ترتیب: `normalize` + ارقام لاتین ← کد ملی ← شناسه ملی ← تاریخ‌ها ← معادله حسابداری ← (اختیاری) دیکشنری. خروجی `{text, corrections, review_queue}`.

---

## `invoice/` — فاکتور

### `numbers.py`
- `parse_number(s)`: ارقام لاتین و حذف فاصله. جداکننده‌های `, ، ٬ ٫ . /` فقط وقتی هزارگان حساب و حذف می‌شوند که ارقام **سه‌تایی گروه‌بندی** شده باشند (`12.500.000`، `350/000/000`؛ فقط نقطه: دست‌کم ۵ رقم). اعشار (`۲٫۵`، `1234.5`) و تاریخ (`1402/05/12`) ⇒ `None`. فقط کاما و گروه‌بندی نامنظم ⇒ کاماها حذف. متنِ فقط «•»، «·»، «.» یعنی صفر. متن غیرعددی ⇒ `None`.
- `digit_edit_distance(a, b)`: فاصله ویرایشی (درج، حذف، جایگزینی)؛ اگر اختلاف طول > ۲ ⇒ ۹۹.
- `is_close(ocr_value, expected)`: فاصله ویرایشی رقمی ≤ ۱.

### `columns.py`
- `COLUMN_ROLES`: لیست مرتب (الگوی خاص‌تر اول) از نقش‌ها: `after_discount`، `net`، `tax`، `discount`، `additions`، `unit_price`، `amount`، `qty`، `unit`، `description`، `code`، `row_no` با regexهای فارسی سرستون. `NUMERIC_ROLES`: نقش‌های عددی.
- `role_of(text)`: اولین نقشی که الگویش در متن (با ارقام لاتین) می‌خورد.
- `x_overlap(a, b)`: هم‌پوشانی افقی دو جعبه نسبت به عرض کوچک‌تر.
- `find_item_header(table)`: ردیفی که **حداقل ۳ ستون عددی** شناخته‌شده دارد (بیشترین ستون عددی برنده). خروجی (اندیس ردیف، `{نقش: جعبه سرستون}`) یا `None`.
- `assign_cells(row, col_boxes)`: متن هر سلول به ستونی می‌رود که هم‌پوشانی افقی‌اش با سرستون بیش از ۰.۵ و بیشینه است؛ چند سلول یک ستون به هم چسبانده می‌شوند.

### `equations.py`
- `VAT_RATES = (10, 9)` (درصد)، `CHECK_STATUSES`.
- `vat(base, pct)`: مالیات با ریاضی صحیح و گرد کردن نصف به بالا (`round` پایتون نصف را به زوج گرد می‌کند).
- `reconcile_by_rate(values, key, expected_by_pct, checks, label)`: اگر با یکی از نرخ‌ها برابر است ⇒ ok؛ اگر **فقط یک** مقدار انتظار با یک ویرایش نزدیک است ⇒ اصلاح؛ چند تا ⇒ `mismatch` با `candidates`.
- `reconcile(values, key, expected, checks, label)`: اگر مقدار نیست ⇒ `filled`؛ برابر ⇒ `ok`؛ با یک ویرایش رقمی نزدیک ⇒ جایگزین + `corrected`؛ وگرنه `mismatch` (بدون تغییر).
- `sum_check(totals, key, col, page_sum, checks)`: جمع صفحه را با سطر جمع مقایسه می‌کند. برابر ⇒ ok؛ نزدیک ⇒ corrected؛ دور ⇒ `deferred` (احتمالاً فاکتور چندصفحه‌ای؛ بعداً در سطح سند).
- `summarize(checks)`: تعداد هر وضعیت.
- `verify_item(vals, checks, row_idx)`: معادلات یک ردیف:
  1. `qty × unit_price = amount`. اگر نمی‌خورد، **کدام عدد** غلط است؟ همه‌ی اصلاح‌های یک‌رقمی (`amount`، `unit_price = amount ÷ qty`، `qty = amount ÷ unit_price`) جمع می‌شوند. اگر بیش از یکی است، با `_downstream_support` (چند معادله‌ی `after_discount`/`tax`/`net` با مبلغ حاصل برقرار است) بهترین انتخاب می‌شود. فقط اصلاح **یکتا** اعمال می‌شود؛ وگرنه `mismatch` با `candidates`.
  2. `amount − discount + additions = after_discount` (اگر ستون هست).
  3. پایه = `after_discount` یا `amount`؛ `tax` با `reconcile_by_rate` روی ۱۰٪ و ۹٪ پایه مقایسه می‌شود (مستقل از خالص، وگرنه خالص با مالیات غلط «سازگار» به نظر می‌آید).
  4. `net = base + tax`؛ اگر مالیات نیست، `net = base × (1 + نرخ)`؛ هیچ نرخی نخورد ⇒ `mismatch`.

### `header.py`
- `HEADER_FIELDS`، `PARTY_FIELDS`: regexهای تاریخ، شماره فاکتور، شناسه مالیاتی؛ و شماره اقتصادی، شناسه ملی، شماره ثبت، کدپستی، تلفن. `_ANY_DATE`: هر تاریخ جلالی (جایگزین اگر تاریخ برچسب‌دار نبود).
- `flat_rows(table)`: متن هر ردیف جدول (سلول‌ها با فاصله، ارقام لاتین).
- `extract_header(rows_flat, page_text)`: روی متن جدول **و** متن کل صفحه می‌گردد (سربرگ معمولاً بیرون شبکه است).
- `party_sections(rows)`: متن بخش فروشنده/خریدار. اگر عنوان ندارد و دو ردیف «شماره اقتصادی» هست: اولی فروشنده، دومی خریدار (قالب رسمی). وگرنه از عنوان «فروشنده/خریدار» تا «مشخصات کالا/شرح کالا/ردیف».
- `_validate_id(value, kind, checks, label)`: checksum؛ `valid` ⇒ ok، `auto_corrected` ⇒ مقدار اصلاح‌شده، غیر این ⇒ mismatch با کاندیدها.
- `_fix_legal_ids(party, side, checks)`: برای شخص حقوقی شماره اقتصادی = شناسه ملی. اگر یکی از ۱۱ رقمی‌ها معتبر است و دیگری فقط یک رقم فاصله دارد، به آن یکی می‌شود؛ وگرنه checksum عادی.
- `extract_parties(rows_flat, checks)`: فیلدهای هر طرف + `_fix_legal_ids` + بررسی قالب کدپستی.

### `parser.py`
- `TOTAL_LABELS`: برچسب‌های جمع‌ها (جمع کل، تخفیفات، کرایه، ارزش افزوده، قابل پرداخت).
- `_parse_items(table, header_idx, col_boxes, rows_flat, checks)`: ردیف‌های بعد از سرستون تا اولین ردیف حاوی «جمع». هر ردیف: سلول‌ها به ستون‌ها، مقادیر عددی با `parse_number`، رد ردیف بدون `amount`/`unit_price`/`net`؛ سپس `verify_item`. خروجی (اقلام، اندیس ردیف جمع).
- `_parse_totals(table, totals_row, col_boxes)`: دو سبک: (۱) سطر جمع هم‌ستون سرستون‌ها ← کلیدهای `sum_<نقش>`؛ (۲) «برچسب | مقدار» در ردیف‌های پایین (بزرگ‌ترین عدد ≥ ۱۰۰۰ ردیف). اگر سبک ۱ بود، «جمع کل» سبک ۲ نادیده می‌شود.
- `_check_totals(items, totals, checks)`: جمع هر ستون و `total` با جمع اقلام صفحه؛ و در صورت وجود ارزش افزوده و قابل‌پرداخت: `vat` ≈ ۱۰٪/۹٪ (جمع − تخفیفات + کرایه)، و `payable = پایه + vat`.
- `parse_invoice(table, page_text="")`: `None` اگر سرستون اقلام نیست. وگرنه dict با `header`، `parties`، `items`، `totals`، `checks`، `check_summary`.

### `document.py`
- `_vote_headers(invoices)`: اگر ≥ ۳ صفحه؛ برای تاریخ، شماره فاکتور و شناسه مالیاتی، مقدار اکثریت (حداقل ۶۰٪) جایگزین مقادیر مخالف می‌شود (مثلاً `1402` به جای `1403` در یک صفحه).
- `_repair_row_scale(invoices)`: وقتی جمع کل سند با جمع اقلام نمی‌خورد، ممکن است یک ردیف فی و مبلغش (هر دو) یک صفر کم/زیاد باشد (ردیف خودش سازگار است!). اگر ×۱۰ یا ÷۱۰ ستون‌های مالی **دقیقاً یک** ردیف جمع سند را **دقیقاً** برابر کند، اعمال می‌شود. ستون‌ها به ترتیب `net`، `amount`، `after_discount`، `tax`.
- `reconcile_document(invoices)`: رأی سربرگ ← تعمیر مقیاس ← جمع هر ستون در کل سند. چک‌های `deferred` بسته می‌شوند: برابر ⇒ ok؛ نزدیک ⇒ corrected؛ دور ⇒ mismatch؛ سند تک‌صفحه‌ای ⇒ mismatch. `check_summary` به‌روز می‌شود.

---

## `report/` — خروجی

### `html.py`
- `ITEM_COLS`، `STATUS_STYLE`، `CSS`: ستون‌های جدول اقلام، رنگ هر وضعیت، و استایل صفحه (راست‌به‌چپ).
- `_esc(v)`: escape HTML. `_fmt(v)`: عدد با جداکننده هزارگان. `_kv(pairs)`: «کلید: `مقدار`» با `|`.
- `render_invoice(inv)`: کادر فاکتور: سربرگ، فروشنده/خریدار، جدول اقلام، جمع‌ها، خلاصه و فهرست چک‌ها با رنگ وضعیت.
- `page_notes(p)` (عمومی؛ داشبورد هم از آن استفاده می‌کند): سه کادر: اصلاح‌های خودکار (سبز)، نیازمند مرور (نارنجی)، خطوط کم‌اطمینان (قرمز).
- `build_review_html(result, source)`: صفحه کامل: تصویر هر صفحه (base64) کنار یادداشت‌ها، فاکتور و متن کامل (جمع‌شونده).

### `files.py`
- `MEDIA_TYPES`: نوع محتوای هر قالب (txt، json، html، zip).
- `render_text(result)`: `text_dedup` هر صفحه (متن کامل و مرتب) با سرتیتر `=== صفحه N ===`. `render_json(result)`: JSON فارسی (بدون escape).
- `render_bundle(result, source, stem, html=True)`: فایل‌ها را در حافظه می‌سازد: `{قالب: (نام، بایت‌ها)}` با نام `<stem>.txt|json|html`. هم CLI و هم API از همین استفاده می‌کنند تا نام‌ها هیچ‌وقت ناهماهنگ نشوند.
- `write_outputs(result, source, out_dir, html=True)`: پوشه را می‌سازد و خروجی `render_bundle` را با `stem` فایل ورودی روی دیسک می‌نویسد؛ مسیرها را برمی‌گرداند. فایل HTML دیگر `_review` ندارد.

---

## `api/` — سرویس HTTP و Swagger

اجرا: `python -m persian_ocr serve` (پیش‌فرض `0.0.0.0:8000`). آدرس‌ها: `/docs` (Swagger UI)، `/openapi.json`، `/` (ریدایرکت به `/docs`).
فایل‌های Swagger UI در `api/static/swagger/` ذخیره‌اند (swagger-ui-dist 5.x، مجوز Apache-2.0)، پس بدون اینترنت کار می‌کند.

| متغیر محیطی | کار | پیش‌فرض |
|---|---|---|
| `PERSIAN_OCR_HOST` | میزبان (برای فقط محلی: `127.0.0.1`) | `0.0.0.0` |
| `PERSIAN_OCR_PORT` | پورت | `8000` |
| `PERSIAN_OCR_API_KEY` | اگر تنظیم شود، هدر `X-API-Key` برای همه endpointها (جز `/health`) لازم است | خاموش |
| `PERSIAN_OCR_MAX_UPLOAD_MB` | حداکثر حجم آپلود | `100` |

| Endpoint | کار |
|---|---|
| `GET /health` | وضعیت، نسخه، بارگذاری مدل، فعال بودن کلید |
| `POST /ocr` | OCR کامل یک PDF/تصویر (متن، جدول، فاکتور، اصلاح‌ها، صف مرور) |
| `POST /ocr/text` | فقط متن |
| `POST /ocr/download?format=txt\|json\|html\|zip` | دانلود با همان نام فایل ورودی (`18185.pdf` ← `18185.txt`) |
| `POST /ocr/review` | گزارش HTML مرور انسانی |
| `POST /validate/national-id`، `/legal-id`، `/iban`، `/postal-code` | checksum و اصلاح محافظه‌کارانه |
| `POST /text/postprocess`، `/text/normalize` | قواعد متنی بدون OCR |
| `POST /invoice/verify-item` | معادلات یک ردیف فاکتور |
| `GET /app`، `POST /app/run` | وب‌اپ آزمون دستی با تصویر خودت (در Swagger نیست) |

### `app.py`
- `STATIC_DIR`، `DESCRIPTION`، `TAGS`: مسیر فایل‌های ایستا، توضیح فارسی صفحه Swagger و توضیح گروه‌ها.
- `create_app(preload=True)`: برنامه FastAPI را می‌سازد. `docs_url=None` تا صفحه `/docs` پیش‌فرض (که از CDN اینترنتی می‌خواند) خاموش شود. فایل‌های ایستا را روی `/static` سوار می‌کند، شش router (از جمله `webapp`) را اضافه می‌کند و `/docs` را با فایل‌های محلی و تنظیمات `persistAuthorization`، `displayRequestDuration`، `tryItOutEnabled` می‌سازد. در `lifespan` اگر `preload` باشد، مدل هنگام شروع بارگذاری می‌شود (درخواست اول کند نشود).
- `swagger_ui()`: HTML صفحه Swagger با آدرس‌های محلی. `root()`: ریدایرکت `/` به `/docs`.

### `deps.py`
- `get_engine()`: موتور OCR را **تنبل** و فقط یک بار (singleton با قفل) بارگذاری می‌کند. `engine_loaded()`: آیا بارگذاری شده؟
- `ocr_lock`: قفل سراسری؛ `force_rtl` وضعیت مشترک موتور را عوض می‌کند و OCR روی CPU هم‌زمان سودی ندارد، پس درخواست‌ها پشت سر هم اجرا می‌شوند.
- `API_KEY_ENV`، `api_key_header`: نام متغیر محیطی و تعریف هدر `X-API-Key` (دکمه Authorize در Swagger).
- `auth_required()`: کلید تنظیم شده است؟
- `require_api_key(key)`: اگر کلید تنظیم شده باشد و هدر نبود یا نخواند ⇒ ۴۰۱. مقایسه با `secrets.compare_digest` (ایمن در برابر حمله زمانی). متغیر محیطی در هر درخواست خوانده می‌شود.

### `uploads.py`
- `ALLOWED_SUFFIXES`، `MAX_UPLOAD_ENV`، `CHUNK`: pdf + پسوندهای تصویر، نام متغیر حجم، و اندازه خواندن (۱ MB).
- `max_upload_mb()`: حد حجم از محیط (پیش‌فرض ۱۰۰ برای PDFهای ۵۰ MB اسکن).
- `original_name(file)`: فقط نام فایل (`Path.name`) تا مسیر دلخواه کلاینت نفوذ نکند.
- `saved_upload(file)`: context manager. پسوند نامجاز ⇒ ۴۱۵. فایل به‌صورت تکه‌تکه در `.cache/tmp/upload_<uuid><پسوند>` نوشته می‌شود؛ بیش از حد ⇒ ۴۱۳ (وسط نوشتن قطع می‌شود، نه بعد از ذخیره کل فایل)؛ خالی ⇒ ۴۲۲؛ PDF بدون `%PDF` در ۱۰۲۴ بایت اول ⇒ ۴۲۲. در `finally` فایل **همیشه** پاک می‌شود، حتی با خطا. نام فایل کلاینت هرگز مسیر دیسک را نمی‌سازد.

### `downloads.py`
- `output_stem(file)`: نام فایل ورودی بدون پسوند. مسیر (`../`) حذف می‌شود، نویسه‌های ممنوع (`" \ / : * ? < > |` و کنترلی) به `_` تبدیل می‌شوند، حداکثر ۱۵۰ نویسه، و اگر چیزی نماند `document`. نام فارسی دست‌نخورده می‌ماند.
- `content_disposition(filename, disposition)`: هدر دانلود. نام ASCII عادی در `filename=`؛ برای نام فارسی `filename*=UTF-8''<درصدی>` طبق RFC 5987 (و `filename=` جایگزین ASCII) تا مرورگر نام را خراب نکند.
- `zip_bundle(files)`: فایل‌ها را در حافظه zip می‌کند (نام داخل zip = همان نام‌ها).
- `build_download(result, source, stem, fmt)`: `(نام، نوع محتوا، بایت‌ها)`. `zip` ← `<stem>.zip` با سه فایل `<stem>.txt|json|html`؛ بقیه یک فایل. پسوند `.pdf` عمداً نگه داشته نمی‌شود چون خروجی PDF نیست.

### `schemas.py`
مدل‌های Pydantic درخواست و پاسخ: `HealthResponse`، `ValueRequest`، `ChecksumResponse` (`valid`، `status`، `output`، `candidates`، `note`)، `PostalResponse`، `TextRequest`، `PostprocessResponse`، `NormalizeRequest`، `NormalizeResponse`، `InvoiceItemRequest` (همه فیلدها اختیاری)، `InvoiceItemResponse`، `PageResult`، `OcrResponse`، `TextPage`، `OcrTextResponse`. توضیح و مثال هر فیلد در Swagger دیده می‌شود.

### `server.py`
- `lan_addresses()`: آدرس‌های IPv4 غیرمحلی ماشین.
- `banner(host, port)`: آدرس‌های Swagger (محلی و شبکه)، حد آپلود، و وضعیت احراز هویت. اگر روی شبکه باز و بدون کلید باشد هشدار می‌دهد.
- `serve(host, port)`: میزبان و پورت از آرگومان، وگرنه `PERSIAN_OCR_HOST`/`PERSIAN_OCR_PORT`، وگرنه `0.0.0.0:8000`؛ سپس `uvicorn.run`.

### `routes/health.py`
`health()`: `GET /health`؛ بدون احراز هویت (برای پایش).

### `routes/ocr.py`
- `router`: پیشوند `/ocr`، همه با `require_api_key`.
- `run_ocr(path, lexicon, max_pages, tables=True)`: (عمومی؛ وب‌اپ هم از آن استفاده می‌کند) داخل `ocr_lock` `process_document` را اجرا می‌کند. خطای پردازش (مثل PDF خراب) به ۴۲۲ با پیام فارسی تبدیل می‌شود.
- همه‌ی endpointهای OCR پارامتر `tables` (پیش‌فرض `true`) دارند؛ `false` یعنی `PipelineConfig(tables=False)`: جدول و فاکتور استخراج نمی‌شوند و متن جدول مثل خطوط عادی خوانده می‌شود (برای آزمون).
- `ocr(file, lexicon, max_pages)`: `POST /ocr`. فایل را ذخیره، پردازش و نام اصلی (نه نام موقت) را در `file` می‌گذارد. `max_pages` بین ۰ تا ۵۰۰.
- `ocr_text(...)`: `POST /ocr/text`؛ `text_dedup` هر صفحه و متن یکپارچه.
- `ocr_review(...)`: `POST /ocr/review`؛ HTML مرور انسانی. ساخت HTML **داخل** بلوک `saved_upload` است چون پیش‌نمایش تصویر صفحه از فایل موقت گرفته می‌شود. هدر `Content-Disposition: inline` با نام `<stem>.html` می‌فرستد.
- `DownloadFormat`: enum قالب‌ها (`txt`، `json`، `html`، `zip`)؛ قالب نامعتبر ⇒ ۴۲۲ و فایلی روی دیسک نمی‌ماند.
- `ocr_download(file, format, lexicon, max_pages)`: `POST /ocr/download`. خروجی را **داخل** `saved_upload` می‌سازد و با `Content-Disposition: attachment` و نام `<stem>.<قالب>` برمی‌گرداند. `POST /ocr` هم هدر `inline` با `<stem>.json` دارد.

### `routes/webapp.py` و `static/app.html`
وب‌اپ آزمون دستی روی `/app`؛ هر دو route با `include_in_schema=False` (در Swagger و `/openapi.json` نمی‌آیند).
- `app_page()`: `GET /app`؛ فایل `static/app.html` را می‌دهد (بدون کلید API، چون داده‌ای ندارد؛ `Cache-Control: no-store`).
- `run(file, lexicon=False, max_pages=0, tables=True)`: `POST /app/run` (در صفحه: تیک «جدول و فاکتور»، پیش‌فرض روشن) با `require_api_key`. فایل را با `saved_upload` می‌گیرد، `run_ocr` اجرا می‌کند و **داخل** بلوک آپلود با `evaluation.dashboard.build_doc` همان ساختار داشبورد را می‌سازد (تصویر صفحه base64، متن هایلایت‌شده، یادداشت‌ها، فاکتور، آمار؛ بدون GT). نام سند را با `output_stem` (نام فایل ورودی بدون پسوند) جایگزین نام موقت می‌کند. پاسخ: `{doc, txt, json}`؛ `txt` و `json` همان `render_text`/`render_json`ِ دانلود هستند. `lexicon` پیش‌فرضش **false** است (برخلاف `/ocr`) تا دقت واقعی دیده شود. **وابستگی:** این route از بسته‌ی `evaluation` (در همین ریشه‌ی مخزن) import می‌کند؛ اگر روزی `api/` جدا بسته‌بندی شود، `build_doc`/`Marker`/`render_html` باید به `persian_ocr/report/` بروند.
- `app.html` (یک فایل، بدون CDN و کتابخانه): صف چندفایلی (انداختن، انتخاب یا paste تصویر)، پردازش **یکی‌یکی** با `fetch`، وضعیت هر فایل (در صف / در حال پردازش با شمارنده‌ی ثانیه / تمام / خطا)، پیام خطای سرور یا «اتصال برقرار نشد»، نمایشگر مثل داشبورد (تصویر قابل چرخش ۹۰/۱۸۰ و zoom کنار خروجی، چرخش هر صفحه جدا، هایلایت، اندازه‌ی متن، حالت تمرکز، میان‌برهای `←/→ R F + -`)، دانلود `txt`/`json` با نام فایل ورودی (ساخته‌شده در مرورگر، بدون درخواست دوم)، حذف از صف. گزینه‌ها: دیکشنری سازمان، حداکثر صفحه، و فیلد کلید API که فقط وقتی `/health` بگوید `auth_required` ظاهر می‌شود. گزینه‌ها (و کلید) در `localStorage` می‌مانند. HTML خروجی سرور از قبل escape شده است (`html.escape` در `render_html`/`page_notes`)؛ نام فایل در مرورگر escape می‌شود.

### `routes/validate.py`
- `_check(kind, value)`: `correct_by_checksum` را به `ChecksumResponse` تبدیل می‌کند؛ `valid` یعنی `status == "valid"`.
- `national_id`، `legal_id`، `iban`: سه endpoint بالا. اصلاح فقط وقتی کاندید یکتاست؛ چند کاندید ⇒ `ambiguous_review` بدون تغییر ورودی.
- `postal_code`: ۱۰ رقم بدون صفر ابتدایی.

### `routes/text.py`
- `postprocess(body)`: `postprocess_text` با گزینه `use_lexicon` (پیش‌فرض خاموش).
- `normalize_text(body)`: `normalize` و در صورت `latin_digits` (پیش‌فرض روشن) ارقام فارسی به لاتین.

### `routes/invoice.py`
`verify(body)`: فیلدهای غیر `None` را به `verify_item` می‌دهد و ردیف اصلاح‌شده، فهرست چک‌ها و خلاصه را برمی‌گرداند.

---

# بسته `evaluation/`

## `metrics.py` (توابع خالص، بدون مدل)
- `prep(text)`: نرمال‌سازی + ارقام لاتین + حذف جداکننده هزارگان بین رقم‌ها + تبدیل علائم نگارشی فارسی (`، ؛ ؟ ٪ ٫ ٬ ۔`) به فاصله تا جزو واژه نباشند.
- `tokens(text)`: واژه‌ها: دنباله حروف فارسی، لاتین، یا رقم.
- `has_invalid_id(line)`: خطی که برچسب شناسه دارد (`شناسه/کد/شماره ملی` یا `کد اقتصادی`) و عدد ۱۰/۱۱ رقمی جدا (نه بخشی از مبلغ کاماگذاری‌شده) با checksum نامعتبر دارد (احتمال خطای خود GT). مبلغ، موبایل و کدپستی حساب نمی‌شوند.
- `f1(precision, recall)`.
- `document_metrics(gt, hyp)`: یک سند. با N=واژه‌های GT، H=واژه‌های خروجی، M=واژه‌های مشترک (multiset):
  - `word_acc = M/N`، `word_prec = M/H`
  - `wer_ordered`: فاصله ویرایشی دنباله واژه‌ها ÷ N (به ترتیب خطوط حساس)
  - `wer_free = ((N−M) + max(0, H−N)) / N`
  - `cer`: فاصله ویرایشی کاراکتری ÷ طول GT
  - `ser`: سهم خطوط GT که حداقل یک واژه/عددشان در خروجی (پس از مصرف توسط خطوط قبلی) نیست؛ `ser_adj` همان بدون خطوط دارای شناسه نامعتبر
  - `num_acc`: سهم اعداد ≥ ۴ رقمی GT که در خروجی هستند
- `aggregate(docs)`: جمع شمارنده‌ها روی چند سند (micro)؛ WER/CER ترتیب‌دار به وزن اندازه GT؛ `wer_free` از جمع خطاهای **هر سند** (`wer_free_errors`) تا واژه‌ی اضافه‌ی یک سند، واژه‌ی جاافتاده‌ی سند دیگر را خنثی نکند. تقسیم بر صفر (حتی فهرست خالی) محافظت شده است.

## `hypotheses.py`
- `MODES = (single_page, tiled, engineered)`، `CACHE = .cache/hyps`.
- `flat_text(pages)`: متن همه خطوط همه صفحه‌ها.
- `collect(loader, pdf, refresh)`: `loader` تابعی است که موتور را برمی‌گرداند و **فقط هنگام نبودن کش** صدا زده می‌شود (`report.run` آن را با `functools.cache` می‌سازد)، پس گزارش با کش معتبر اصلاً مدل را بارگذاری نمی‌کند و در کمبود رم هم کار می‌کند. اگر کش هست و `signature` آن (اندازه و زمان PDF + اثر انگشت کد `persian_ocr`) با فعلی برابر است، آن را برمی‌گرداند. وگرنه سه حالت را اجرا می‌کند: خط پایه بدون Tiling، خط پایه با Tiling، و مهندسی‌شده (بدون دیکشنری، با `text_dedup`). زمان، تعداد صفحه و خلاصه چک‌های فاکتور را هم ذخیره می‌کند.

## `cache.py`
- `code_fingerprint()`: sha256 همه‌ی فایل‌های `.py` و `.json` بسته‌ی `persian_ocr` به‌جز `api/` که روی خروجی OCR اثری ندارد (۱۶ نویسه).
- `source_signature(path)`: `{size, mtime, code}`؛ کلید مشترک کش `hypotheses.py` و `dashboard.py`.

## `report.py`
- `ROWS`، `MULTI_PAGE_LIMIT = 2`، `NOTES`: ردیف‌های جدول، حد «سند کم‌صفحه» و توضیحات.
- `_summary_table(agg)`، `_per_doc_table(docs)`، `_invoice_table(docs)`: جدول‌های markdown.
- `build_markdown(docs)`: گزارش کامل: نتیجه کلی، فقط اسناد ≤ ۲ صفحه، به تفکیک سند، سازگاری فاکتورها، تعریف‌ها.
- `run(refresh, data_dir)`: هر `X.pdf` با `X.txt` در `eval_data/`؛ خروجی `reports/metrics_report.md` و `.json`.

## `fields.py`
- `GROUND_TRUTH_DIR`، `SEARCH_DIRS` (`files/` و `eval_data/`)، `MODES` (چهار حالت).
- `evaluate_fields(fields, hyp_text)`: فیلد درست است اگر مقدارش (دقیق، یا بدون فاصله/جداکننده) در **یک خط** خروجی باشد؛ مقدار عددی باید مرز رقمی داشته باشد (`1234` داخل `51234` حساب نمی‌شود).
- `_find_pdf(name)`: پیدا کردن PDF در پوشه‌های جست‌وجو.
- `run()`: برای هر JSON در `ground_truth/`: چهار حالت (معمولی، Tiling، مهندسی‌شده، مهندسی‌شده + دیکشنری). حالت دیکشنری با `postprocess_text` روی متن خام همان اجرا ساخته می‌شود (OCR دوباره لازم نیست). خروجی `reports/fields_report.md`.

## `compare.py`
مقایسه‌ی Indra پروژه با Claude، Gemini، Chandra و Lift روی `eval_data/eval-data-compare/` (۱۶ سند). خروجی `reports/model_comparison.md`.
- منبع متن: **Indra** = `Indra/Main/<سند>.json` (خروجی واقعی API؛ `text_dedup` همه‌ی صفحه‌ها). Claude، Gemini، Chandra = `<مدل>/Normalized/<سند>.json` (chunkهای HTML). `Indra/Normalized` عمداً استفاده نمی‌شود: برای هر ۱۶ سند دقیقاً `1075 → 1062` توکن مصرف شده، یعنی نرمال‌ساز محتوا را ندیده و قالب خالی ساخته است.
- `html_to_text(content)`: برچسب‌ها حذف، سلول‌های جدول با فاصله و بلوک‌ها با خط جدید جدا، entityها decode.
- `chunks_text(path)`، `indra_text(path)`، `lift_fields(path)`: متن chunkها / `text_dedup` صفحه‌ها / فیلدهای استخراج‌شده. فایل ناموجود یا اجرای شکست‌خورده (مثل `bad allocation`) ← `None`.
- `current_indra_text(name)`: خروجی کد **فعلی** از کش `.cache/hyps` (برای سه سند دارای GT)، چون فایل‌های `Main` با نسخه‌ی قدیمی‌تر کد و دیکشنری روشن ساخته شده‌اند.
- `load_documents(root)`: `{سند: {Indra، Claude، Gemini، Chandra، Lift، «Indra (کد فعلی)»}}`.
- `numbers(bag)`، `overlap(ref, hyp)`، `pair_agreement(a, b)`: توکن‌های ≥۴ رقمی؛ recall/precision/F1 بسته‌ی واژه‌ها؛ هم‌خوانی واژه‌ای و عددی دو متن (ارقام و جداکننده‌ها نرمال).
- `consensus(entry)`: اشتراک بسته‌ی واژه‌های Claude و Gemini (هر دو تولید کرده‌اند) به‌عنوان مرجع تقریبی. `vs_consensus(entry, provider)`: بازیابی واژه/عدد یک مدل نسبت به آن.
- `gt_results(docs)`: `document_metrics` همه‌ی مدل‌ها روی اسنادی که `<سند>.txt` در `eval_data/` دارند (۳ سند). `lift_vs_gt(fields, gt)`: اعداد (شماره، جمع، تعداد، فی، مبلغ) و نام‌های Lift که در GT هستند.
- `build_markdown(docs)`: چهار بخش: ۱) با GT، ۲) هم‌خوانی دوبه‌دو، ۳) اجماع Claude ∩ Gemini به‌ازای هر سند (با سقف Claude↔Gemini)، ۴) Lift؛ و محدودیت‌ها. `run()`: ساخت و نوشتن گزارش.
- محدودیت‌ها: GT فقط ۳ سند است و منشأش معلوم نیست؛ Indra روی این سندها in-sample است؛ هم‌خوانی و اجماع دقت نیستند (دو مدل هر دو می‌توانند غلط باشند).

## `dashboard.py` و `dashboard.html`
`python -m evaluation dashboard [--refresh] [--lexicon] [--dir پوشه]` ← `reports/dashboard.html`: **یک فایل مستقل** (تصویر صفحه‌ها base64 داخلش است، بدون اینترنت و بدون سرور). برای هر PDF یا تصویر پوشه (پیش‌فرض `eval_data`) فقط **تصویر اصلی هر صفحه (قابل چرخش)** و **خروجی مدل ما** را کنار هم نشان می‌دهد. ground truth و متریک‌های مبتنی بر آن عمداً در داشبورد نیستند (برای آن‌ها `python -m evaluation`).
- `source_files(data_dir)`: فقط فایل‌های PDF و تصویر (پوشه‌ها مثل `eval-data-compare` و `.txt` نه).
- `load_result(loader, path, lexicon, refresh)`: نتیجه‌ی `process_document` را در `.cache/dashboard/<نام>.<lex|nolex>.json` کش می‌کند. امضای کش (`evaluation/cache.py`: `source_signature`) اندازه و زمان تغییر فایل منبع و اثر انگشت کد `persian_ocr` است؛ اگر PDF یا کد عوض شود کش خودکار باطل می‌شود. مدل فقط وقتی لازم باشد بارگذاری می‌شود (`functools.cache` روی `OcrEngine.load`).
- `mark_tokens(values)`: توکن‌های ≥۴ نویسه‌ی مقدارهای کوتاه (≤۴۰ نویسه) برای رنگ کردن خروجی اصلاح‌ها و موارد مرور.
- `Marker(fix, review)`: هر واژه را HTML می‌کند. واژه‌ای که توکنش در خروجی اصلاح خودکار باشد کلاس `fix` (سبز)، و اگر در موارد مرور انسانی (ورودی یا کاندیدها) باشد `rev` (نارنجی) می‌گیرد؛ `fix` بر `rev` مقدم است. بقیه متن escape‌شده‌ی ساده‌اند.
- `render_html(text, marker, low)`: هر خط یک `div`؛ خط `| الف | ب |` به ردیف جدول HTML (سلول‌های خالی حذف)؛ خط کم‌اطمینان کلاس `low`؛ عنوان `[خطوط تکمیلی از ناحیه جدول]` کلاس `sup`.
- `build_doc(path, result)`: برای هر صفحه: تصویر JPEG رنگی با dpi ۱۰۰ و کیفیت ۷۰ (base64) و **ابعاد پیکسلی** (برای چرخش)، متن هایلایت‌شده، یادداشت‌ها با `page_notes`، فاکتور با `render_invoice` و آمار (واژه، جدول، اصلاح، مرور، کم‌اطمینان). برای سند: زمان، مجموع ناهماهنگی معادلات فاکتور و `focus` (صفحه‌ای با بیشترین «مرور + کم‌اطمینان»؛ سند روی همان باز می‌شود).
- `render_page(data)`: JSON را جای `__DATA__` می‌گذارد و `</` را escape می‌کند تا `</script>` داخل داده صفحه را نشکند.
- `run(refresh, lexicon, data_dir)`: دیکشنری به‌طور پیش‌فرض **خاموش** است.
- **قالب `dashboard.html`:** دو تب. «نمای کلی»: کارت‌های خلاصه (اسناد، واژه، اصلاح خودکار، مرور انسانی، کم‌اطمینان، زمان)، نکته‌ی «رنگ‌ها اطمینان‌اند نه درستی»، راهنمای رنگ و جدول قابل مرتب‌سازی و جست‌وجو. «تصویر و خروجی»: دو ستون (تصویر اصلی، خروجی مدل) با هایلایت، اندازه‌ی متن، zoom تصویر، کپی متن و حالت تمرکز.
- **چرخش تصویر:** دکمه‌های ⟲ (۹۰ چپ)، ⟳ (۹۰ راست)، ⇅ (۱۸۰) و «اصلی»، و کلیدهای `R` و `Shift+R`. تصویر با `transform: rotate` می‌چرخد و **کادر دور آن هم ابعادش را عوض می‌کند** (با ابعاد پیکسلی صفحه)، پس تصویر چرخیده بریده نمی‌شود و در zoom ۱۰۰٪ همیشه به عرض ستون جا می‌شود. چرخش **هر صفحه جداگانه** در `localStorage` (`ocrdash-rot`) نگه داشته می‌شود.
- میان‌برها: `←`/`→` صفحه (راست‌به‌چپ: `←` بعدی)، `N`/`P` سند، `R` چرخش، `F` تمرکز، `+`/`-` اندازه‌ی متن. چون صفحه‌ها در مرورگر این ماشین رندر نمی‌شدند، رفتار JS با `tools/dashboard_smoke.js` در jsdom تست شده است؛ ظاهر (رنگ و چیدمان) تست نشده است.
- **محدودیت‌ها:** رنگ‌ها فقط وضعیت اطمینان مدل‌اند؛ درستی متن را داشبورد نمی‌سنجد. چرخش فقط نمایشی است و روی OCR اثر ندارد (pipeline خودش جهت صفحه را تشخیص می‌دهد).

## `groundtruth.py` و `number_verdicts.json`
ground truth با **ماسک اعداد قضاوت‌شده**؛ فایل‌های `eval_data` هرگز تغییر نمی‌کنند.
- `number_verdicts.json`: قضاوت‌های خام گالری اعداد اشتباه (۶۵ مورد؛ `doc`، `gt`، `ocr`، `kind`، `verdict`)، همان‌طور که از «کپی قضاوت‌ها (JSON)» آمده. مسیر ممیزی است و دست‌کاری نمی‌شود. `verdict`: `ocr` (خطای واقعی OCR)، `gt` (GT اشتباه)، `image` (تصویر نامفهوم یا عدد روی سند چاپ نشده).
- `load_verdicts()`، `masks_for(doc)`: شمارنده‌ی `{عدد: تعداد}` برای قضاوت‌های `gt` و `image` (`MASKED_VERDICTS`)؛ قضاوت `ocr` ماسک نمی‌شود چون خطای واقعی است.
- `mask_numbers(text, numbers)`: هر خط را با `prep` نرمال می‌کند (ارقام لاتین، بدون جداکننده‌ی هزارگان) و دقیقاً به تعداد قضاوت‌شده عدد را با مرز رقمی (`(?<!\d)…(?!\d)`، پس `1000` داخل `10000` نمی‌خورد) حذف می‌کند؛ خط‌های بدون تغییر دست‌نخورده می‌مانند.
- `load_gt(path, masked=True)`: متن GT با ماسک. در `report.py` (متریک‌ها)، `compare.py` (مقایسه‌ی مدل‌ها) و `errors.py --remaining` استفاده می‌شود. اثر روی ۸ سند: ۳۰ از ۵۰۶ عدد کنار رفت؛ تطبیق‌ها ۴۴۰ ⇐ ۴۴۰؛ دقت اعداد ۸۷٫۰٪ ⇐ ۹۲٫۴٪ (اسناد ≤۲ صفحه ۶۸٫۱٪ ⇐ ۷۸٫۴٪).
- **محدودیت:** یک ردیف گالری (تکرار دوم یک شناسه‌ی ملی حقوقی در سند `24286`) قضاوت نشده و ماسک نمی‌شود. ماسک اعتبارش را از قضاوت چشمی می‌گیرد؛ اگر قضاوتی اشتباه بود، همان ردیف را در فایل اصلاح کن.

## `errors.py` و `errors.html`
`python -m evaluation errors [--lexicon] [--remaining]` (با `--remaining` اعداد ماسک‌شده نشان داده نمی‌شوند و فقط خطاهای باقی‌مانده می‌ماند) ← `reports/number_errors.html`: **گالری اعداد اشتباه**. برای هر عدد ≥۴ رقمیِ GT که در خروجی نیست (۶۴ مورد از ۸ سند)، برش تصویر همان محل، خوانش ما و GT کنار هم است تا آدم با چشم تعیین کند خطا از OCR است، از GT، یا از تصویر.
- `number_tokens(text)`، `missed_numbers(gt, hyp)`: همان تعریف `num_acc` در `metrics.py` (توکن‌های ≥۴ رقمی، جداکننده و سبک ارقام نادیده)؛ اعداد GT که در خروجی نیستند، به ترتیب ظهور در GT.
- `classify(gt, reading)`: `missing` (خوانشی نیست)، `dropped` / `dropped_zero` (یک رقم افتاده؛ اگر در رشته‌ی صفرها باشد `zero`)، `added` / `added_zero`، `replaced` (یک رقم عوض شده)، `multi` (چند ویرایش). `diff_html(a, b)`: ارقام متفاوت دو طرف با `<mark>`.
- `collect_items(pages)`: همه‌ی اعداد خطوط و سلول‌ها با جعبه و صفحه. `nearest_item(number, items, pool)`: نزدیک‌ترین خوانش اضافی (فقط از اعدادی که در GT نبودند؛ اختلاف طول ≤۳ و فاصله ≤ `max(3, طول/3)`) و مصرف آن.
- **مکان‌یابی اعداد پیدانشده:** `label_key` کلید قبل از «:» در خط GT را می‌گیرد؛ `label_line` آن را با خط‌های OCR مقایسه می‌کند (شباهت ≥۷۵ و خط OCR دست‌کم ۸۰٪ طول کلید، تا خط‌های یک‌نویسه‌ای که داخل برچسب هستند نخورند). خط‌های GT که با `[` شروع می‌شوند (مثل `[تطبیق دیکشنری سازمان: …]`) **توضیح خود GT‌اند و روی سند چاپ نشده‌اند**؛ مکان‌یابی نمی‌شوند و با برچسب «خط توضیحی GT» نشان داده می‌شوند.
- `make_crop(page_jpeg, box, wide)`: برش از تصویر هم‌جهت‌شده‌ی OCR با حاشیه‌ی ۶۰٪ ارتفاع خط، بزرگ‌نمایی تا ارتفاع ≥۱۰۰ پیکسل، و کادر قرمز دور محل. برای مکان‌یابی با برچسب (`wide`) افقی به اندازه‌ی عرض خط و **به پایین تا ۶ برابر ارتفاع** بلندتر است، چون مقدار معمولاً زیر سرستون جدول است.
- `build_rows(doc, gt, hyp, pages, jpegs)`: ردیف‌ها با `doc`، `page`، `gt`، `ocr`، نوع خطا، محل، خط GT و برش. `run()`: برای هر سند `process_document` را با `on_page` اجرا می‌کند؛ تصویر هر صفحه را JPEG فشرده نگه می‌دارد (نه آرایه‌ی خام) تا رم نخورد.
- **صفحه:** فیلتر نوع خطا و سند و قضاوت. برای هر مورد سه دکمه: «OCR اشتباه»، «GT اشتباه»، «تصویر نامفهوم». قضاوت‌ها در `localStorage` (`ocrerr-verdicts`) می‌مانند و «کپی قضاوت‌ها (JSON)» آن‌ها را (`doc`، `gt`، `ocr`، `kind`، `verdict`) صادر می‌کند.
- **محدودیت‌ها:** برش‌ها از تصویر هم‌جهت‌شده‌ی OCR‌اند و ممکن است ۹۰ یا ۱۸۰ درجه با PDF فرق کنند. مکان‌یابی با برچسب تقریبی است. فایل‌های `eval_data` عمداً **تغییر نمی‌کنند**؛ اصلاح GT بعداً با یک فایل اصلاحیه‌ی جدا و قابل ممیزی انجام می‌شود.

## `__main__.py`
`python -m evaluation` ← `metrics` (پیش‌فرض، با `--refresh`)، `fields`، `compare`، `dashboard` یا `errors`.

---

# `tools/`
- `build_code_reference.py`: همین مرجع را به `docs/code-reference.html` تبدیل می‌کند.
- `errors_smoke.js`: گالری اعداد اشتباه را در jsdom اجرا می‌کند و ۲۲ بررسی انجام می‌دهد: یک کارت برای هر ردیف، برش‌ها data URL، ردیف بدون برش پیام می‌دهد، علامت‌های تفاوت رقم، فیلتر نوع خطا و سند، اعمال و ذخیره و پاک شدن قضاوت، فیلتر قضاوت، خروجی JSON و نبودن خطای اسکریپت.
- `dashboard_smoke.js`: داشبورد را در jsdom (با آدرس `http://localhost` تا `localStorage` کار کند) اجرا می‌کند و ۵۲ بررسی انجام می‌دهد: نبودن GT در داده و صفحه، ردیف‌های نمای کلی، مرتب‌سازی، جست‌وجو، باز شدن سند و صفحه‌ی مشکوک‌ترین، تصویر و متن و جدول، **چرخش** (۰/۹۰/۱۸۰/۲۷۰، پیچیدن به ۰، جابه‌جایی نسبت ابعاد کادر، کلید `R` و `Shift+R`، بازنشانی، یادآوری چرخش هر صفحه، ذخیره در `localStorage`، zoom)، میان‌برهای صفحه‌کلید و مرزها، کلیدهای نمایش و نبودن خطای اسکریپت. نیاز: `npm install jsdom` داخل `.cache/nodetools`؛ اجرا: `node tools/dashboard_smoke.js` بعد از ساخت داشبورد.
- `app_smoke.js`: وب‌اپ `/app` را در jsdom با `fetch` جعلی اجرا می‌کند (۳۴ بررسی): حالت خالی، وضعیت سلامت و فیلد کلید، رد نوع فایل نامجاز، صف سه‌فایله و **اجرای یکی‌یکی** (حداکثر یک درخواست هم‌زمان)، رسیدن گزینه‌ها و کلید در درخواست، حالت‌های تمام/خطا، پیام خطای سرور و قطع اتصال، نمایشگر (تصویر، متن، یادداشت‌ها، چرخش هر صفحه)، دانلود با نام ورودی، حالت تمرکز، حذف از صف (حفظ انتخاب)، بازگشت به حالت خالی، یادآوری گزینه‌ها و نبودن خطای اسکریپت. اجرا: `node tools/app_smoke.js`. ظاهر (رنگ و چیدمان) در مرورگر واقعی دیده نشده است.

---

# `tests/`
| فایل | چه چیزی را تست می‌کند |
|---|---|
| `test_text.py` | نرمال‌سازی (ارقام، حروف عربی، نیم‌فاصله)؛ checksum کد ملی و شناسه ملی واقعی؛ رد رقم تکراری و checksum غلط؛ اصلاح رقم ادغام‌شده CTC (`349838389`← `3499838389`)؛ **حدس نزدن** وقتی اصلاح یکتا نیست؛ تقارن `CONFUSION_MAP` و اینکه رقم درهم‌خوانده هرگز به شناسه‌ی دیگری اصلاح نشود؛ پس‌پردازش تاریخ (روز ناقص به مرور، تاریخ خارج از بازه، صفر اضافه‌ی سال)؛ معادله سرمایه (ارزش اسمی درست `10000` دست‌نخورده)؛ خاموش بودن دیکشنری |
| `test_invoice.py` | `parse_number` (گروه‌بندی هر جداکننده، رد اعشار و تاریخ)؛ فاصله ویرایشی؛ اصلاح مبلغ از روی `مقدار × فی` فقط با شاهد مالیات/خالص؛ `mismatch` وقتی دو اصلاح ممکن است؛ گرد کردن نصف به بالای مالیات؛ ردیف سازگار دست‌نخورده؛ اعداد نامرتبط فقط `mismatch`؛ جدول مصنوعی فاکتور؛ بسته شدن چک `deferred` با جمع سند |
| `test_groundtruth.py` | `mask_numbers` (حذف عدد و ماندن بقیه‌ی خط، ارقام فارسی و جداکننده، فقط به تعداد قضاوت‌شده، `1000` داخل `10000` نمی‌خورد، خط‌های دیگر دست‌نخورده، عدد داخل کد با حروف)؛ `masks_for` (فقط `gt` و `image`، مستقل بودن اسناد)؛ فایل ممیزی: ساختار هر ورودی، وجود سندها، حضور هر عدد قضاوت‌شده در GT واقعی، و اینکه ماسک روی فایل‌های واقعی **دقیقاً** همان تعداد عدد را برمی‌دارد |
| `test_errors.py` | `number_tokens` و `missed_numbers` (حداقل ۴ رقم، ترتیب، تکرار، جداکننده و سبک ارقام)؛ `classify` (نخوانده، افتاده/اضافه، صفر در رشته‌ی صفرها، رقم تکی صفر، جایگزین، چند خطا)؛ `diff_html`؛ مکان‌یابی (آیتم‌های خط و سلول، نزدیک‌ترین خوانش و مصرف آن، خوانش دور، برچسب با کلید قبل از «:»، خط یک‌نویسه‌ای داخل برچسب نخورد، خط توضیحی GT مکان‌یابی نمی‌شود)؛ برش (ارتفاع خوانا، لبه‌ی صفحه، رسیدن به مقدار کنار و زیر برچسب)؛ `build_rows` و `summarize`؛ قالب و JSON |
| `test_dashboard.py` | `mark_tokens`؛ `Marker` (سبک ارقام، تقدم `fix` بر `rev`، escape)؛ رندر: خط ساده، جدول و رنگ واژه‌های سلول، اصلاح/مرور، خط کم‌اطمینان، عنوان تکمیلی، escape؛ `preview_jpeg` (ابعاد برابر تصویر دیکد‌شده)؛ `build_doc` (داده‌ی صفحه با ابعاد، **نبودن داده‌ی GT**، صفحه‌ی `focus`، جمع ناهماهنگی فاکتور)؛ قالب: درج داده و escape `</script>`، یک جایگاه `__DATA__`، نبودن ستون GT و بودن دکمه‌ی چرخش؛ فهرست منابع فقط سند |
| `test_compare.py` | `html_to_text` (برچسب، سلول، entity)؛ `overlap` (یکسان، recall/precision متفاوت، خالی)؛ اعداد ≥۴ رقم؛ هم‌خوانی بی‌اعتنا به سبک ارقام و جداکننده؛ اجماع و بازیابی نسبت به آن؛ مدل/مرجع ناموجود؛ فیلدهای Lift در برابر GT؛ بارگذاری (اجرای شکست‌خورده ← `None`، `text_dedup` همه‌ی صفحه‌ها)؛ ساخت گزارش |
| `test_metrics.py` | توکن‌سازی؛ خروجی کامل و خالی؛ جابه‌جایی خطوط (WER ترتیب‌دار بد، بدون‌ترتیب صفر)؛ یک رقم غلط کل خط را در SER خراب می‌کند؛ Precision؛ SER تعدیل‌شده (مبلغ، موبایل و کدپستی شناسه نیستند)؛ مصرف یک‌باره‌ی توکن‌ها در SER؛ علائم نگارشی؛ میانگین وزنی؛ خنثی نشدن خطاها بین اسناد؛ ورودی خالی؛ فیلدها (نه بین خطوط، نه داخل عدد بزرگ‌تر) |
| `test_pipeline.py` | `_cell_of`: خط داخل سلول متن‌دار پیدا می‌شود، خط بین سلول‌ها/سلول خالی/بالای جدول نه؛ `_covered`: ارقام لاتین/فارسی، عدد با یک رقم اضافه (پوشش)، عدد کاملاً متفاوت (بدون پوشش)؛ `text_dedup`: عنوان بین سلول‌ها یک بار می‌ماند، ترتیب خواندن حفظ می‌شود، ردیف جدول سر جای عمودی‌اش می‌نشیند، خط مطمئن پوشش‌داده‌نشده ← «خطوط تکمیلی»، خط کم‌اطمینان اضافه نمی‌شود، صفحه‌ی بدون جدول بی‌تغییر؛ **تعارض خوانش**: اختلاف چند رقم (`٣,٢٠٠,٠٠٠` در برابر `٢,٢٠٠,٠٠٠`) گزارش می‌شود و متن عوض نمی‌شود، سبک ارقام/جداکننده تعارض نیست، رقم اضافه تعارض است، عدد کاملاً متفاوت تعارض نیست (به «خطوط تکمیلی» می‌رود)، عددهای کوتاه (<۳ رقم) و واژه‌ها نادیده، نزدیک‌ترین عدد در سلول چندعددی، گزارش تکراری یک بار، خط کم‌اطمینان هم گزارش می‌شود، صفحه‌ی بدون جدول بی‌تعارض، و موارد مرور قبلی (مثل `legal`) حفظ می‌شوند |
| `test_api.py` | (با `TestClient`، بدون مدل) Swagger با فایل‌های **محلی** و بدون CDN؛ فهرست کامل endpointها؛ validation و حدس‌نزدن؛ قواعد متنی؛ معادلات ردیف؛ **کلید API** (باز بدون کلید، ۴۰۱ با کلید غلط، `/health` همیشه باز)؛ آپلود: ۴۱۵ و ۴۲۲ و ۴۱۳؛ نبودن فایل آپلودی روی دیسک بعد از خطا؛ **نام دانلود**: stem بدون پسوند، نام فارسی، حذف مسیر و نویسه‌های ناامن، هدر RFC 5987 (رفت‌وبرگشت)، نام فایل‌های داخل zip، و `/ocr/download` واقعی با `samples/invoice-sample.png` (فاکتور مصنوعی) |
| `test_webapp.py` | وب‌اپ `/app`: صفحه بدون کلید و بدون هیچ آدرس اینترنتی باز می‌شود؛ مسیرهای `/app*` در Swagger نیستند؛ `/app/run` (با OCR جعلی): داده‌ی نمایشگر (نام سند از نام فایل فارسی، تصویر، متن، یادداشت `reading_conflict`، آمار)، `txt` و `json` دانلودی، دیکشنری **خاموش** به‌طور پیش‌فرض و رسیدن گزینه‌ها به پایپ‌لاین، نبودن داده‌ی GT، ۴۱۵ و ۴۲۲، خطای پردازش با پیام فارسی، پاک شدن آپلود در موفقیت و خطا، و ۴۰۱ با کلید غلط |
| `test_tables.py` | تشخیص سلول از شبکه مصنوعی (۲۰ سلول)؛ ترتیب راست به چپ ردیف‌ها؛ صفحه خالی؛ markdown؛ حد تایل‌ها؛ IoU؛ ادغام خطوط (نگه‌داشتن اطمینان بالاتر) |

اجرا: `python -m unittest discover -s tests -t .` (بدون نیاز به مدل).
