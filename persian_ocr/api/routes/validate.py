from fastapi import APIRouter, Depends

from ...text import correct_by_checksum, is_valid_postal_code, normalize_digits
from ..deps import require_api_key
from ..schemas import ChecksumResponse, PostalResponse, ValueRequest

router = APIRouter(prefix="/validate", tags=["Validation"], dependencies=[Depends(require_api_key)])


def _check(kind: str, value: str) -> ChecksumResponse:
    res = correct_by_checksum(value, kind=kind)
    return ChecksumResponse(kind=kind, valid=res["status"] == "valid", **res)


@router.post(
    "/national-id",
    response_model=ChecksumResponse,
    summary="کد ملی (شخص حقیقی)",
    description="checksum رسمی. اگر یک رقم ادغام/تکرار شده و دقیقاً یک کاندید معتبر وجود دارد اصلاح می‌شود؛ اگر چند کاندید است، حدس نمی‌زند (`ambiguous_review`).",
)
def national_id(body: ValueRequest) -> ChecksumResponse:
    return _check("nid", body.value)


@router.post("/legal-id", response_model=ChecksumResponse, summary="شناسه ملی / کد اقتصادی (شخص حقوقی، ۱۱ رقم)")
def legal_id(body: ValueRequest) -> ChecksumResponse:
    return _check("legal", body.value)


@router.post("/iban", response_model=ChecksumResponse, summary="شبا (IR + ۲۴ رقم، mod-97)")
def iban(body: ValueRequest) -> ChecksumResponse:
    return _check("iban", body.value)


@router.post("/postal-code", response_model=PostalResponse, summary="کدپستی (۱۰ رقم، بدون صفر ابتدایی)")
def postal_code(body: ValueRequest) -> PostalResponse:
    return PostalResponse(value=normalize_digits(body.value).strip(), valid=is_valid_postal_code(body.value))
