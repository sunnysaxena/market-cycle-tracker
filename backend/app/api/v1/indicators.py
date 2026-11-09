
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.indicators import (
    IndicatorTimeframe,
    TechnicalIndicatorResponse,
)
from app.services.indicator_query_service import (
    get_technical_indicators,
)

router = APIRouter(
    prefix="/market",
    tags=["Technical Indicators"],
)


@router.get(
    "/{instrument}/indicators",
    response_model=TechnicalIndicatorResponse,
)
def technical_indicators(
    instrument: str,
    timeframe: IndicatorTimeframe = Query(...),
    import_batch_id: int | None = Query(default=None, ge=1),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise HTTPException(
                status_code=422,
                detail="start_date must not be after end_date.",
            )

    return get_technical_indicators(
        db,
        instrument_code=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
