from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .deps import get_engine
from .routes import health, invoice, ocr, text, validate, webapp

STATIC_DIR = Path(__file__).resolve().parent / "static"

DESCRIPTION = """
OCR فارسی اسناد ساخت‌دار (Indra OCR + مهندسی تصویر + قواعد تعیینی)، فقط روی CPU.

- **OCR**: آپلود PDF یا تصویر ← متن، جدول، فاکتور ساختاریافته، اصلاح‌های خودکار و صف مرور انسانی.
- **Validation / Text rules / Invoice**: قواعد تعیینی (checksum، تاریخ، معادلات فاکتور) بدون نیاز به مدل؛ برای آزمایش سریع.
- **وب‌اپ آزمون:** صفحه‌ی `/app` برای آزمایش با تصویر خودت (تصویر کنار خروجی).
- **اصل طراحی:** حدس نزن. اگر اصلاح یکتا و قطعی نباشد، مورد به مرور انسانی می‌رود.

اگر متغیر محیطی `PERSIAN_OCR_API_KEY` تنظیم شده باشد، دکمه **Authorize** را بزن و کلید را در `X-API-Key` وارد کن.
"""

TAGS = [
    {"name": "OCR", "description": "پردازش فایل (کند: چند ثانیه برای هر صفحه؛ درخواست‌ها پشت سر هم اجرا می‌شوند)."},
    {"name": "Validation", "description": "اعتبارسنجی و اصلاح محافظه‌کارانه شناسه‌ها با checksum."},
    {"name": "Text rules", "description": "نرمال‌سازی و پس‌پردازش متن بدون OCR."},
    {"name": "Invoice", "description": "معادلات فاکتور."},
    {"name": "Health", "description": "وضعیت سرویس."},
]


def create_app(preload: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if preload:
            await run_in_threadpool(get_engine)
        yield

    app = FastAPI(
        title="Persian OCR API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for module in (health, ocr, validate, text, invoice, webapp):
        app.include_router(module.router)

    @app.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} — Swagger UI",
            swagger_js_url="/static/swagger/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger/swagger-ui.css",
            swagger_favicon_url="/static/swagger/favicon-32x32.png",
            swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True, "docExpansion": "list", "tryItOutEnabled": True},
        )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app
