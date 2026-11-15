import os
import socket

from .deps import API_KEY_ENV, auth_required
from .uploads import max_upload_mb

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def lan_addresses() -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not info[4][0].startswith("127.")})
    except OSError:
        return []


def banner(host: str, port: int) -> str:
    lines = ["", "Persian OCR API", f"  Swagger UI : http://127.0.0.1:{port}/docs"]
    if host in ("0.0.0.0", "::"):
        lines += [f"  از شبکه    : http://{ip}:{port}/docs" for ip in lan_addresses()]
    lines.append(f"  آپلود حداکثر: {max_upload_mb():g} MB")
    if auth_required():
        lines.append(f"  احراز هویت : فعال (هدر X-API-Key از {API_KEY_ENV})")
    elif host in ("0.0.0.0", "::"):
        lines.append(f"  هشدار      : روی شبکه باز است و بدون احراز هویت؛ برای محدود کردن {API_KEY_ENV} را تنظیم کن.")
    return "\n".join(lines) + "\n"


def serve(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from .app import create_app

    host = host or os.environ.get("PERSIAN_OCR_HOST", DEFAULT_HOST)
    port = port or int(os.environ.get("PERSIAN_OCR_PORT", DEFAULT_PORT))
    print(banner(host, port), flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
