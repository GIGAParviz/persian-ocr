from fastapi import APIRouter

from ... import __version__
from ...config import MODEL_DIR
from ..deps import auth_required, engine_loaded
from ..schemas import HealthResponse
from ..uploads import max_upload_mb

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="وضعیت سرویس")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        model_dir=str(MODEL_DIR),
        model_loaded=engine_loaded(),
        auth_required=auth_required(),
        max_upload_mb=max_upload_mb(),
    )
