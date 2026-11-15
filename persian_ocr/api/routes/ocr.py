from enum import Enum

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse

from ...config import PipelineConfig
from ...pipeline import process_document
from ...report import build_review_html
from ..deps import get_engine, ocr_lock, require_api_key
from ..downloads import build_download, content_disposition, output_stem
from ..schemas import OcrResponse, OcrTextResponse
from ..uploads import original_name, saved_upload

router = APIRouter(prefix="/ocr", tags=["OCR"], dependencies=[Depends(require_api_key)])

LEXICON_DOC = "دیکشنری موجودیت‌های سازمان (master data) را هم اعمال کن. در ارزیابی عدد را بالا می‌برد؛ برای آزمون دقت واقعی خاموشش کن."
PAGES_DOC = "حداکثر تعداد صفحه (۰ = همه)."
TABLES_DOC = "استخراج جدول و فاکتور. برای آزمون بدون جدول خاموشش کن؛ متن جدول همچنان به صورت خطوط عادی خوانده می‌شود."


class DownloadFormat(str, Enum):
    txt = "txt"
    json = "json"
    html = "html"
    zip = "zip"


def run_ocr(path, lexicon: bool, max_pages: int, tables: bool = True) -> dict:
    try:
        with ocr_lock:
            return process_document(get_engine(), path, PipelineConfig(use_lexicon=lexicon, max_pages=max_pages, tables=tables))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"پردازش فایل ناموفق بود: {exc}") from exc


@router.post(
    "",
    response_model=OcrResponse,
    summary="OCR کامل یک PDF یا تصویر",
    description="متن هر صفحه، اصلاح‌های خودکار، صف مرور انسانی، خطوط کم‌اطمینان، جدول‌ها و فاکتور ساختاریافته (در صورت وجود).",
)
def ocr(
    response: Response,
    file: UploadFile = File(..., description="PDF یا تصویر (png، jpg، tif، bmp، webp)"),
    lexicon: bool = Query(True, description=LEXICON_DOC),
    max_pages: int = Query(0, ge=0, le=500, description=PAGES_DOC),
    tables: bool = Query(True, description=TABLES_DOC),
) -> dict:
    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables)
    result["file"] = original_name(file)
    response.headers["Content-Disposition"] = content_disposition(f"{output_stem(file)}.json", "inline")
    return result


@router.post("/text", response_model=OcrTextResponse, summary="فقط متن استخراج‌شده")
def ocr_text(
    file: UploadFile = File(...),
    lexicon: bool = Query(True, description=LEXICON_DOC),
    max_pages: int = Query(0, ge=0, le=500, description=PAGES_DOC),
    tables: bool = Query(True, description=TABLES_DOC),
) -> dict:
    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables)
    pages = [{"page": p["page"], "text": p["text_dedup"]} for p in result["pages"]]
    return {
        "file": original_name(file),
        "time_sec": result["time_sec"],
        "text": "\n\n".join(p["text"] for p in pages),
        "pages": pages,
    }


@router.post("/review", response_class=HTMLResponse, summary="گزارش HTML مرور انسانی", description="خروجی را مستقیم در مرورگر ببین: تصویر هر صفحه کنار متن، اصلاح‌ها و موارد مشکوک.")
def ocr_review(
    file: UploadFile = File(...),
    lexicon: bool = Query(True, description=LEXICON_DOC),
    max_pages: int = Query(0, ge=0, le=500, description=PAGES_DOC),
    tables: bool = Query(True, description=TABLES_DOC),
) -> HTMLResponse:
    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables)
        result["file"] = original_name(file)
        return HTMLResponse(build_review_html(result, path), headers={"Content-Disposition": content_disposition(f"{output_stem(file)}.html", "inline")})


@router.post(
    "/download",
    response_class=Response,
    summary="OCR و دانلود خروجی با نام همان فایل ورودی",
    description=(
        "نام فایل خروجی همان نام فایل ورودی است با پسوند خروجی: `18185.pdf` ← `18185.txt` یا `18185.json` یا `18185.html`. "
        "با `zip` هر سه فایل با همان نام در `18185.zip` می‌آیند. نام فارسی هم درست دانلود می‌شود (RFC 5987)."
    ),
    responses={200: {"description": "فایل دانلودی", "content": {"text/plain": {}, "application/json": {}, "text/html": {}, "application/zip": {}}}},
)
def ocr_download(
    file: UploadFile = File(..., description="PDF یا تصویر"),
    format: DownloadFormat = Query(DownloadFormat.txt, description="قالب خروجی"),
    lexicon: bool = Query(True, description=LEXICON_DOC),
    max_pages: int = Query(0, ge=0, le=500, description=PAGES_DOC),
    tables: bool = Query(True, description=TABLES_DOC),
) -> Response:
    stem = output_stem(file)
    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables)
        result["file"] = original_name(file)
        name, media_type, data = build_download(result, path, stem, format.value)
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": content_disposition(name)})
