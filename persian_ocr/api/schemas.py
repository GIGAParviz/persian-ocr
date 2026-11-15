from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    version: str
    model_dir: str
    model_loaded: bool
    auth_required: bool
    max_upload_mb: float


class ValueRequest(BaseModel):
    value: str = Field(description="مقدار برای اعتبارسنجی؛ ارقام فارسی، عربی و لاتین پذیرفته می‌شود.", examples=["3499838389"])


class ChecksumResponse(BaseModel):
    kind: str
    input: str
    valid: bool
    status: str = Field(description="valid | auto_corrected | ambiguous_review | invalid_review | wrong_length")
    output: str = Field(description="مقدار نهایی؛ فقط وقتی اصلاح یکتا وجود دارد با ورودی فرق می‌کند.")
    candidates: list[str]
    note: str | None = None


class PostalResponse(BaseModel):
    value: str
    valid: bool


class TextRequest(BaseModel):
    text: str = Field(examples=["با شماره ملی ۳۴۹۸۳۸۳۸۹ به عنوان رئیس جلسه، مورخ ۱۴۰۵/۰۳۱۷"])
    use_lexicon: bool = Field(False, description="دیکشنری موجودیت‌های سازمان (master data) هم اعمال شود.")


class PostprocessResponse(BaseModel):
    text: str
    corrections: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]


class NormalizeRequest(BaseModel):
    text: str = Field(examples=["كتاب يك ۱۲۳"])
    latin_digits: bool = Field(True, description="ارقام فارسی هم به لاتین تبدیل شوند.")


class NormalizeResponse(BaseModel):
    text: str


class InvoiceItemRequest(BaseModel):
    qty: int | None = Field(None, examples=[5])
    unit_price: int | None = Field(None, examples=[70000000])
    amount: int | None = Field(None, description="مبلغ کل ردیف", examples=[250000000])
    discount: int | None = None
    additions: int | None = None
    after_discount: int | None = None
    tax: int | None = Field(None, examples=[35000000])
    net: int | None = Field(None, examples=[385000000])


class InvoiceItemResponse(BaseModel):
    item: dict[str, int]
    checks: list[dict[str, Any]]
    check_summary: dict[str, int]


class PageResult(BaseModel):
    page: int
    raw_text: str
    text: str
    text_dedup: str
    corrections: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]
    low_confidence_lines: list[dict[str, Any]]
    tables_markdown: list[str]
    invoice: dict[str, Any] | None = None


class OcrResponse(BaseModel):
    file: str
    time_sec: float
    pages: list[PageResult]


class TextPage(BaseModel):
    page: int
    text: str


class OcrTextResponse(BaseModel):
    file: str
    time_sec: float
    text: str
    pages: list[TextPage]
