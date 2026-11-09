
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.structure import (
    EventClassification,
    EventType,
    MarketStructureEventsResponse,
    MarketStructureResponse,
    StructureTimeframe,
)
from app.services.structure_query_service import (
    get_market_structure,
    get_market_structure_events,
)


router = APIRouter(
    prefix="/market",
    tags=["Market Structure"],
)


@router.get(
    "/{instrument}/structure",
    response_model=MarketStructureResponse,
)
def read_market_structure(
    instrument: str,
    timeframe: Annotated[StructureTimeframe, Query(...)],
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

    return get_market_structure(
        db,
        instrument_code=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{instrument}/structure/events",
    response_model=MarketStructureEventsResponse,
)
def read_market_structure_events(
    instrument: str,
    timeframe: Annotated[StructureTimeframe, Query(...)],
    import_batch_id: int | None = Query(default=None, ge=1),
    start_date: date | None = None,
    end_date: date | None = None,
    event_type: EventType | None = None,
    classification: EventClassification | None = None,
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

    return get_market_structure_events(
        db,
        instrument_code=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
        event_type=event_type,
        classification=classification,
        limit=limit,
        offset=offset,
    )
