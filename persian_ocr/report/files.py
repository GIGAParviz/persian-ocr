import json
from pathlib import Path

from .docx import DOCX_MIME
from .html import build_review_html

MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "json": "application/json",
    "html": "text/html; charset=utf-8",
    "zip": "application/zip",
    "docx": DOCX_MIME,
}


def render_text(result: dict) -> str:
    return "\n\n".join(f"=== صفحه {p['page']} ===\n{p['text_dedup']}" for p in result["pages"])


def render_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def render_bundle(result: dict, source: str | Path, stem: str, html: bool = True) -> dict[str, tuple[str, bytes]]:
    files = {
        "txt": (f"{stem}.txt", render_text(result).encode("utf-8")),
        "json": (f"{stem}.json", render_json(result).encode("utf-8")),
    }
    if html:
        files["html"] = (f"{stem}.html", build_review_html(result, source).encode("utf-8"))
    return files


def write_outputs(result: dict, source: str | Path, out_dir: Path, html: bool = True) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for ext, (name, data) in render_bundle(result, source, Path(source).stem, html).items():
        paths[ext] = out_dir / name
        paths[ext].write_bytes(data)
    return paths
