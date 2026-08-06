from fastapi import APIRouter

from app.schemas.misc import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus, operation_id="healthz")
def healthz() -> HealthStatus:
    return HealthStatus(status="ok")
