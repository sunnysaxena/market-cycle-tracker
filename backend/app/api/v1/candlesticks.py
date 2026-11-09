from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.candlestick import (
    CandlestickPatternResponse,
    CandlestickTimeframe,
)
from app.services.candlestick_query_service import (
    get_candlestick_patterns,
)


router = APIRouter(
    prefix="/market",
    tags=["Candlestick Patterns"],
)


@router.get(
    "/{instrument}/candlestick-patterns",
    response_model=CandlestickPatternResponse,
)
def read_candlestick_patterns(
    instrument: str,
    timeframe: Annotated[CandlestickTimeframe, Query(...)],
    import_batch_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
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

    return get_candlestick_patterns(
        db,
        instrument_code=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
