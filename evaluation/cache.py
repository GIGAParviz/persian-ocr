from __future__ import annotations

import functools
import hashlib
from pathlib import Path

from persian_ocr.config import PACKAGE_DIR


@functools.cache
def code_fingerprint(package_dir: Path = PACKAGE_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*")):
        rel = path.relative_to(package_dir)
        if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in rel.parts and rel.parts[0] != "api":
            digest.update(rel.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def source_signature(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime": int(stat.st_mtime), "code": code_fingerprint()}
