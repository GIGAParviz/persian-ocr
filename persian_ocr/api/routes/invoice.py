from fastapi import APIRouter, Depends

from ...invoice.equations import summarize, verify_item
from ..deps import require_api_key
from ..schemas import InvoiceItemRequest, InvoiceItemResponse

router = APIRouter(prefix="/invoice", tags=["Invoice"], dependencies=[Depends(require_api_key)])


@router.post(
    "/verify-item",
    response_model=InvoiceItemResponse,
    summary="راستی‌آزمایی یک ردیف فاکتور با معادلات",
    description="مقدار×فی=مبلغ، مبلغ−تخفیف+اضافات، مالیات ۱۰٪ یا ۹٪ (گرد کردن نصف به بالا) و پایه+مالیات=خالص. عددی اصلاح می‌شود که **تنها** اصلاح یک‌رقمی سازگار باشد؛ اگر چند اصلاح ممکن است (مثلاً مبلغ یا فی)، `mismatch` با `candidates`.",
)
def verify(body: InvoiceItemRequest) -> InvoiceItemResponse:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    checks: list = []
    verify_item(values, checks, 1)
    return InvoiceItemResponse(item=values, checks=checks, check_summary=summarize(checks))
