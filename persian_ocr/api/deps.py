import os
import secrets
import threading

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from ..engine import OcrEngine

API_KEY_ENV = "PERSIAN_OCR_API_KEY"

_engine: OcrEngine | None = None
_engine_lock = threading.Lock()
ocr_lock = threading.Lock()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="فقط وقتی متغیر محیطی PERSIAN_OCR_API_KEY تنظیم شده باشد لازم است.")


def get_engine() -> OcrEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = OcrEngine.load()
        return _engine


def engine_loaded() -> bool:
    return _engine is not None


def auth_required() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def require_api_key(key: str | None = Security(api_key_header)) -> None:
    expected = os.environ.get(API_KEY_ENV)
    if expected and not (key and secrets.compare_digest(key, expected)):
        raise HTTPException(status_code=401, detail="کلید API نامعتبر است (هدر X-API-Key).")
