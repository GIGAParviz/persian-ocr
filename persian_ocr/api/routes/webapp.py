import base64
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from evaluation.dashboard import build_doc

from ...config import PreprocessMode
from ...report import DOCX_MIME, build_docx
from ...report.files import render_json, render_text
from ..deps import require_api_key
from ..downloads import clean_stem, content_disposition, output_stem
from ..layout import build_layout
from ..uploads import original_name, saved_upload
from .ocr import run_ocr

router = APIRouter(prefix="/app", include_in_schema=False)

PAGE = Path(__file__).resolve().parents[1] / "static" / "app.html"


@router.get("", response_class=HTMLResponse)
def app_page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.post("/run", dependencies=[Depends(require_api_key)])
def run(
    file: UploadFile = File(...),
    lexicon: bool = Query(False),
    max_pages: int = Query(0, ge=0, le=500),
    tables: bool = Query(True),
    preprocess: PreprocessMode = Query(PreprocessMode.original),
) -> dict:
    processed = {}

    def capture(index, gray, page):
        scale = min(1.0, 1600 / max(gray.shape))
        image = gray if scale == 1 else cv2.resize(gray, (round(gray.shape[1] * scale), round(gray.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not success:
            raise ValueError("Cannot encode processed page")
        processed[index] = (base64.b64encode(encoded).decode("ascii"), [gray.shape[1], gray.shape[0]], page)

    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables, preprocess=preprocess, on_page=capture)
        result["file"] = original_name(file)
        for index, result_page in enumerate(result["pages"]):
            if index in processed:
                _, size, page_ocr = processed[index]
                result_page["layout"] = build_layout(tuple(size), page_ocr, result_page["text"])
        doc = build_doc(path, result)
    for index, page in enumerate(doc["pages"]):
        if index in processed:
            page["processed_image"], page["processed_size"], _ = processed[index]
            page["layout"] = result["pages"][index]["layout"]
        page["plain_text"] = result["pages"][index]["text_dedup"]
    doc["name"] = output_stem(file)
    doc["file"] = result["file"]
    return {"doc": doc, "txt": render_text(result), "json": render_json(result)}


class ExportPage(BaseModel):
    page: int = Field(1, ge=1)
    text: str = ""


class ExportRequest(BaseModel):
    name: str = "document"
    pages: list[ExportPage] = Field(min_length=1, max_length=5000)


@router.post("/export", dependencies=[Depends(require_api_key)])
def export_docx(body: ExportRequest) -> Response:
    stem = clean_stem(f"{body.name}.docx")
    data = build_docx([{"page": p.page, "text": p.text} for p in body.pages])
    return Response(content=data, media_type=DOCX_MIME, headers={"Content-Disposition": content_disposition(f"{stem}.docx")})
