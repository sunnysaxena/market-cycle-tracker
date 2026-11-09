from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.index import Index
from app.models.historical import MarketCycleClassification
from app.schemas.cycles import (
    ClassificationBasis,
    CycleClassification,
    CycleTimeframe,
    MarketCycleRecord,
    MarketCycleResponse,
)
from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)
from app.services.api_errors import InstrumentNotFoundError
from app.services.batch_service import resolve_import_batch


def _validate_query(
    start_date: date | None,
    end_date: date | None,
    limit: int,
    offset: int,
) -> None:
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must not be after end_date.")

    if not 1 <= limit <= 2000:
        raise ValueError("limit must be between 1 and 2000.")

    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")


def _get_active_instrument(db: Session, instrument: str) -> Index:
    instrument_code = instrument.strip().upper()

    index = db.scalar(
        select(Index).where(
            Index.code == instrument_code,
            Index.is_active.is_(True),
        )
    )

    if index is None:
        raise InstrumentNotFoundError(
            f"Active instrument '{instrument_code}' was not found."
        )

    return index


def get_market_cycles(
    db: Session,
    instrument: str,
    timeframe: CycleTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    classification: CycleClassification | None = None,
    classification_basis: ClassificationBasis | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MarketCycleResponse:
    """Retrieve stored market-cycle classifications without recalculation."""

    _validate_query(start_date, end_date, limit, offset)

    index = _get_active_instrument(db, instrument)
    batch = resolve_import_batch(db, import_batch_id)

    base_filters = [
        MarketCycleClassification.import_batch_id == batch.id,
        MarketCycleClassification.instrument_code == index.code,
        MarketCycleClassification.timeframe == timeframe,
    ]

    base_count = db.scalar(
        select(func.count())
        .select_from(MarketCycleClassification)
        .where(*base_filters)
    ) or 0

    latest_date = db.scalar(
        select(func.max(MarketCycleClassification.period_end))
        .where(*base_filters)
    )

    filters = list(base_filters)

    if start_date is not None:
        filters.append(
            MarketCycleClassification.period_start >= start_date
        )

    if end_date is not None:
        filters.append(
            MarketCycleClassification.period_start <= end_date
        )

    if classification is not None:
        filters.append(
            MarketCycleClassification.cycle_classification == classification
        )

    if classification_basis is not None:
        filters.append(
            MarketCycleClassification.classification_basis
            == classification_basis
        )

    total_records = db.scalar(
        select(func.count())
        .select_from(MarketCycleClassification)
        .where(*filters)
    ) or 0

    statement = (
        select(MarketCycleClassification)
        .where(*filters)
        .order_by(MarketCycleClassification.period_start.asc())
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(statement).all()

    records = [
        MarketCycleRecord.model_validate(row)
        for row in rows
    ]

    if total_records > 0:
        availability_status = "available"
        availability_message = None
    elif base_count > 0:
        availability_status = "no_records_in_range"
        availability_message = (
            "No market-cycle records match the supplied filters."
        )
    else:
        availability_status = "no_data"
        availability_message = (
            "No market-cycle classifications are available "
            "for this instrument, timeframe, and batch."
        )

    return MarketCycleResponse(
        instrument_code=index.code,
        timeframe=timeframe,
        batch=BatchMetadata.model_validate(batch),
        records=records,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(records),
            total_records=total_records,
        ),
        availability=DataAvailability(
            status=availability_status,
            is_available=total_records > 0,
            record_count=total_records,
            latest_date=latest_date,
            message=availability_message,
        ),
    )
