from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.historical import DailyOHLCV, AggregatedOHLCV
from app.models.index import Index
from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)
from app.schemas.market import (
    AggregatedHistoryRecord,
    DailyHistoryRecord,
    MarketHistoryResponse,
)
from app.services.api_errors import InstrumentNotFoundError
from app.services.batch_service import resolve_import_batch


Timeframe = Literal["1D", "1W", "1M", "1Y"]


def get_market_history(
    db: Session,
    *,
    instrument_code: str,
    timeframe: Timeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
    sort_order: Literal["asc", "desc"] = "asc",
) -> MarketHistoryResponse:
    """
    Read historical OHLCV records without calculating or modifying data.

    Daily records come from daily_ohlcv.
    Higher-timeframe records come from aggregated_ohlcv.
    """

    code = instrument_code.strip().upper()

    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date.")

    if not 1 <= limit <= 2000:
        raise ValueError("limit must be between 1 and 2000.")

    if offset < 0:
        raise ValueError("offset must not be negative.")

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

    batch = resolve_import_batch(
        db,
        import_batch_id=import_batch_id,
    )

    if timeframe == "1D":
        model = DailyOHLCV
        date_column = DailyOHLCV.candle_date
    else:
        model = AggregatedOHLCV
        date_column = AggregatedOHLCV.period_start

    base_conditions = [
        model.import_batch_id == batch.id,
        model.instrument_code == code,
    ]

    filtered_conditions = list(base_conditions)

    if timeframe != "1D":
        filtered_conditions.append(
            model.timeframe == timeframe
        )

    if start_date is not None:
        filtered_conditions.append(
            date_column >= start_date
        )

    if end_date is not None:
        filtered_conditions.append(
            date_column <= end_date
        )

    # Total records matching the requested filters.
    total_records = db.scalar(
        select(func.count())
        .select_from(model)
        .where(*filtered_conditions)
    ) or 0

    # Overall availability and latest date are independent of
    # the requested date range.
    dataset_count = db.scalar(
        select(func.count())
        .select_from(model)
        .where(*base_conditions)
        if timeframe == "1D"
        else select(func.count())
        .select_from(model)
        .where(
            *base_conditions,
            AggregatedOHLCV.timeframe == timeframe,
        )
    ) or 0

    availability_conditions = (
        base_conditions
        if timeframe == "1D"
        else base_conditions + [AggregatedOHLCV.timeframe == timeframe]
    )

    latest_date = db.scalar(
        select(func.max(date_column))
        .select_from(model)
        .where(*availability_conditions)
    )

    order_column = (
        date_column.desc()
        if sort_order == "desc"
        else date_column.asc()
    )

    statement = (
        select(model)
        .where(*filtered_conditions)
        .order_by(order_column)
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(statement).all()

    if timeframe == "1D":
        records = [
            DailyHistoryRecord.model_validate(row)
            for row in rows
        ]
    else:
        records = [
            AggregatedHistoryRecord.model_validate(row)
            for row in rows
        ]

    if total_records > 0:
        availability_status = "available"
        message = None
    elif dataset_count > 0:
        availability_status = "no_records_in_range"
        message = "No records match the requested date range."
    else:
        availability_status = "no_data"
        message = "No historical records are available for this instrument and timeframe."

    return MarketHistoryResponse(
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
        availability=DataAvailability(
            status=availability_status,
            is_available=total_records > 0,
            record_count=total_records,
            latest_date=latest_date,
            message=message,
        ),
    )

