import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from ..config import IMAGE_SUFFIXES, TMP_DIR

ALLOWED_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES
MAX_UPLOAD_ENV = "PERSIAN_OCR_MAX_UPLOAD_MB"
CHUNK = 1 << 20


def max_upload_mb() -> float:
    return float(os.environ.get(MAX_UPLOAD_ENV, "100"))


def original_name(file: UploadFile) -> str:
    return Path(file.filename or "upload").name


@contextmanager
def saved_upload(file: UploadFile) -> Iterator[Path]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"نوع فایل پشتیبانی نمی‌شود: «{suffix or 'بدون پسوند'}». مجاز: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    limit = int(max_upload_mb() * CHUNK)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TMP_DIR / f"upload_{uuid4().hex}{suffix}"
    try:
        size = 0
        with path.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"حجم فایل بیشتر از {max_upload_mb():g} مگابایت است.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="فایل خالی است.")
        if suffix == ".pdf" and b"%PDF" not in path.read_bytes()[:1024]:
            raise HTTPException(status_code=422, detail="فایل PDF معتبر نیست.")
        yield path
    finally:
        path.unlink(missing_ok=True)
