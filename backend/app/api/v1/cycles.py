from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.cycles import (
    ClassificationBasis,
    CycleClassification,
    CycleTimeframe,
    MarketCycleResponse,
)
from app.services.cycle_query_service import get_market_cycles


cycles_router = APIRouter(
    prefix="/market",
    tags=["Market Cycles"],
)


@cycles_router.get(
    "/{instrument}/cycles",
    response_model=MarketCycleResponse,
)
def read_market_cycles(
    instrument: str,
    timeframe: CycleTimeframe = Query(...),
    import_batch_id: int | None = Query(default=None, ge=1),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    classification: CycleClassification | None = Query(default=None),
    classification_basis: ClassificationBasis | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must not be after end_date.",
        )

    return get_market_cycles(
        db=db,
        instrument=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
        classification=classification,
        classification_basis=classification_basis,
        limit=limit,
        offset=offset,
    )
