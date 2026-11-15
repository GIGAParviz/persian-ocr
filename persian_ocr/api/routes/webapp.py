from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import HTMLResponse

from evaluation.dashboard import build_doc

from ...report.files import render_json, render_text
from ..deps import require_api_key
from ..downloads import output_stem
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
) -> dict:
    with saved_upload(file) as path:
        result = run_ocr(path, lexicon, max_pages, tables)
        result["file"] = original_name(file)
        doc = build_doc(path, result)
    doc["name"] = output_stem(file)
    doc["file"] = result["file"]
    return {"doc": doc, "txt": render_text(result), "json": render_json(result)}
