import io
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import UploadFile

from ..report import MEDIA_TYPES, build_docx, render_bundle

MAX_STEM = 150
UNSAFE = re.compile(r'[\x00-\x1f"\\/:*?<>|]')


def clean_stem(filename: str | None) -> str:
    stem = UNSAFE.sub("_", Path(filename or "").stem).strip(" .")[:MAX_STEM]
    return stem or "document"


def output_stem(file: UploadFile) -> str:
    return clean_stem(file.filename)


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    fallback = filename if filename.isascii() else f"download{Path(filename).suffix}"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def zip_bundle(files: dict[str, tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.values():
            archive.writestr(name, data)
    return buffer.getvalue()


def build_download(result: dict, source: Path, stem: str, fmt: str) -> tuple[str, str, bytes]:
    if fmt == "docx":
        return f"{stem}.docx", MEDIA_TYPES["docx"], build_docx(result["pages"])
    files = render_bundle(result, source, stem, html=fmt in ("html", "zip"))
    if fmt == "zip":
        return f"{stem}.zip", MEDIA_TYPES["zip"], zip_bundle(files)
    name, data = files[fmt]
    return name, MEDIA_TYPES[fmt], data
