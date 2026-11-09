from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.multi_timeframe import MultiTimeframeResponse
from app.services.multi_timeframe_query_service import (
    get_multi_timeframe_analysis,
)

router = APIRouter(
    prefix="/market",
    tags=["Multi-Timeframe Analysis"],
)


@router.get(
    "/{instrument}/multi-timeframe",
    response_model=MultiTimeframeResponse,
)
def multi_timeframe_analysis(
    instrument: str,
    import_batch_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return get_multi_timeframe_analysis(
        db,
        instrument_code=instrument,
        import_batch_id=import_batch_id,
    )
