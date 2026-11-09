
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.historical import (
    MarketStructureEvent,
    MarketStructureSnapshot,
)
from app.models.index import Index
from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)
from app.schemas.structure import (
    MarketStructureResponse,
    MarketStructureEventsResponse,
    StructureSnapshotRecord,
    StructureEventRecord,
    SupportLevel,
    ResistanceLevel,
    StructureTimeframe,
)
from app.services.api_errors import InstrumentNotFoundError
from app.services.batch_service import resolve_import_batch


def _validate_query(
    *,
    start_date: date | None,
    end_date: date | None,
    limit: int,
    offset: int,
) -> None:
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date.")

    if not 1 <= limit <= 2000:
        raise ValueError("limit must be between 1 and 2000.")

    if offset < 0:
        raise ValueError("offset must not be negative.")


def _get_active_instrument(db: Session, instrument_code: str) -> str:
    code = instrument_code.strip().upper()

    index = db.scalar(
        select(Index).where(
            Index.code == code,
            Index.is_active.is_(True),
        )
    )

    if index is None:
        raise InstrumentNotFoundError(
            f"Active instrument '{code}' was not found."
        )

    return code


def _build_availability(
    *,
    total_records: int,
    dataset_count: int,
    latest_date: date | None,
    data_type: str,
) -> DataAvailability:
    if total_records > 0:
        status = "available"
        message = None

    elif dataset_count > 0:
        status = "no_records_in_range"
        message = f"No {data_type} records match the requested date range."

    else:
        status = "no_data"
        message = f"No {data_type} records are available for this instrument and timeframe."

    return DataAvailability(
        status=status,
        is_available=total_records > 0,
        record_count=total_records,
        latest_date=latest_date,
        message=message,
    )


def get_market_structure(
    db: Session,
    *,
    instrument_code: str,
    timeframe: StructureTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MarketStructureResponse:

    _validate_query(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    code = _get_active_instrument(db, instrument_code)
    batch = resolve_import_batch(db, import_batch_id=import_batch_id)

    base_conditions = [
        MarketStructureSnapshot.import_batch_id == batch.id,
        MarketStructureSnapshot.instrument_code == code,
        MarketStructureSnapshot.timeframe == timeframe,
    ]

    filtered_conditions = list(base_conditions)

    if start_date is not None:
        filtered_conditions.append(
            MarketStructureSnapshot.period_start >= start_date
        )

    if end_date is not None:
        filtered_conditions.append(
            MarketStructureSnapshot.period_start <= end_date
        )

    total_records = db.scalar(
        select(func.count())
        .select_from(MarketStructureSnapshot)
        .where(*filtered_conditions)
    ) or 0

    dataset_count = db.scalar(
        select(func.count())
        .select_from(MarketStructureSnapshot)
        .where(*base_conditions)
    ) or 0

    latest_date = db.scalar(
        select(func.max(MarketStructureSnapshot.period_end))
        .where(*base_conditions)
    )

    statement = (
        select(MarketStructureSnapshot)
        .where(*filtered_conditions)
        .order_by(MarketStructureSnapshot.period_start.asc())
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(statement).all()

    records = [
        StructureSnapshotRecord(
            period_start=row.period_start,
            period_end=row.period_end,
            source_close=row.source_close,
            support=SupportLevel(
                price=row.support_price,
                pivot_date=row.support_pivot_date,
                confirmation_date=row.support_confirmation_date,
                classification=row.support_classification,
            ),
            resistance=ResistanceLevel(
                price=row.resistance_price,
                pivot_date=row.resistance_pivot_date,
                confirmation_date=row.resistance_confirmation_date,
                classification=row.resistance_classification,
            ),
            market_structure_state=row.market_structure_state,
            breakout_status=row.breakout_status,
            range_position=row.range_position,
            left_bars=row.left_bars,
            right_bars=row.right_bars,
            equal_tolerance_pct=row.equal_tolerance_pct,
            calculation_version=row.calculation_version,
            generated_at_utc=row.generated_at_utc,
        )
        for row in rows
    ]

    availability = _build_availability(
        total_records=total_records,
        dataset_count=dataset_count,
        latest_date=latest_date,
        data_type="Market structure",
    )

    return MarketStructureResponse(
        instrument_code=code,
        timeframe=timeframe,
        batch=BatchMetadata.model_validate(batch),
        records=records,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(records),
            total_records=total_records,
        ),
        availability=availability,
    )


def get_market_structure_events(
    db: Session,
    *,
    instrument_code: str,
    timeframe: StructureTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    event_type: str | None = None,
    classification: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MarketStructureEventsResponse:

    _validate_query(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    code = _get_active_instrument(db, instrument_code)
    batch = resolve_import_batch(db, import_batch_id=import_batch_id)

    base_conditions = [
        MarketStructureEvent.import_batch_id == batch.id,
        MarketStructureEvent.instrument_code == code,
        MarketStructureEvent.timeframe == timeframe,
    ]

    filtered_conditions = list(base_conditions)

    if start_date is not None:
        filtered_conditions.append(
            MarketStructureEvent.pivot_date >= start_date
        )

    if end_date is not None:
        filtered_conditions.append(
            MarketStructureEvent.pivot_date <= end_date
        )

    if event_type is not None:
        filtered_conditions.append(
            MarketStructureEvent.event_type == event_type
        )

    if classification is not None:
        filtered_conditions.append(
            MarketStructureEvent.classification == classification
        )

    total_records = db.scalar(
        select(func.count())
        .select_from(MarketStructureEvent)
        .where(*filtered_conditions)
    ) or 0

    dataset_count = db.scalar(
        select(func.count())
        .select_from(MarketStructureEvent)
        .where(*base_conditions)
    ) or 0

    latest_date = db.scalar(
        select(func.max(MarketStructureEvent.confirmation_date))
        .where(*base_conditions)
    )

    statement = (
        select(MarketStructureEvent)
        .where(*filtered_conditions)
        .order_by(
            MarketStructureEvent.pivot_date.asc(),
            MarketStructureEvent.event_type.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(statement).all()

    records = [
        StructureEventRecord(
            event_type=row.event_type,
            pivot_date=row.pivot_date,
            pivot_period_end=row.pivot_period_end,
            confirmation_date=row.confirmation_date,
            confirmation_period_end=row.confirmation_period_end,
            pivot_price=row.pivot_price,
            classification=row.classification,
            left_bars=row.left_bars,
            right_bars=row.right_bars,
            equal_tolerance_pct=row.equal_tolerance_pct,
            calculation_version=row.calculation_version,
            generated_at_utc=row.generated_at_utc,
        )
        for row in rows
    ]

    availability = _build_availability(
        total_records=total_records,
        dataset_count=dataset_count,
        latest_date=latest_date,
        data_type="Market structure event",
    )

    return MarketStructureEventsResponse(
        instrument_code=code,
        timeframe=timeframe,
        batch=BatchMetadata.model_validate(batch),
        records=records,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(records),
            total_records=total_records,
        ),
        availability=availability,
    )
