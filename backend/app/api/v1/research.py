
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.cycles import CycleTimeframe
from app.schemas.research import ResearchForwardReturnsResponse
from app.services.research_service import (
    get_forward_returns_by_phase,
)


router = APIRouter(
    prefix="/research",
    tags=["Research Lab"],
)


@router.get(
    "/{instrument}/forward-returns",
    response_model=ResearchForwardReturnsResponse,
)
def forward_returns_by_phase(
    instrument: str,
    timeframe: CycleTimeframe = Query(...),
    import_batch_id: int | None = Query(default=None, ge=1),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return get_forward_returns_by_phase(
        db,
        instrument=instrument,
        timeframe=timeframe,
        import_batch_id=import_batch_id,
        start_date=start_date,
        end_date=end_date,
    )
