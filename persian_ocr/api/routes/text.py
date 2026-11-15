from fastapi import APIRouter, Depends

from ...text import normalize, normalize_digits, postprocess_text
from ..deps import require_api_key
from ..schemas import NormalizeRequest, NormalizeResponse, PostprocessResponse, TextRequest

router = APIRouter(prefix="/text", tags=["Text rules"], dependencies=[Depends(require_api_key)])


@router.post(
    "/postprocess",
    response_model=PostprocessResponse,
    summary="پس‌پردازش قاعده‌ای متن OCR",
    description="نرمال‌سازی، اصلاح کد ملی/شناسه ملی با checksum، تاریخ جلالی، معادله سرمایه/سهام و (اختیاری) دیکشنری سازمان. بدون نیاز به مدل OCR.",
)
def postprocess(body: TextRequest) -> dict:
    return postprocess_text(body.text, use_lexicon=body.use_lexicon)


@router.post("/normalize", response_model=NormalizeResponse, summary="نرمال‌سازی متن فارسی")
def normalize_text(body: NormalizeRequest) -> NormalizeResponse:
    text = normalize(body.text)
    return NormalizeResponse(text=normalize_digits(text) if body.latin_digits else text)
