# TradePilot AI — GET /health.
#
# In plain terms: a quick "is the service up, and can it reach the
# database" check, with nothing else attached to it.

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.schemas import HealthResponse
from database.database import get_session

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_session)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        database_status = "error"

    return HealthResponse(status="ok", database=database_status)
