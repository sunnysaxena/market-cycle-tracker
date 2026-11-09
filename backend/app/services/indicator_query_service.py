
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.historical import TechnicalIndicatorValue
from app.models.index import Index
from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)
from app.schemas.indicators import (
    IndicatorCalculationMetadata,
    IndicatorOHLC,
    IndicatorSource,
    MACDIndicators,
    MomentumIndicators,
    MovingAverageIndicators,
    TechnicalIndicatorRecord,
    TechnicalIndicatorResponse,
    TrendIndicators,
    VolatilityIndicators,
)
from app.services.api_errors import InstrumentNotFoundError
from app.services.batch_service import resolve_import_batch


IndicatorTimeframe = Literal["1D", "1W", "1M", "1Y"]


def get_technical_indicators(
    db: Session,
    *,
    instrument_code: str,
    timeframe: IndicatorTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> TechnicalIndicatorResponse:
    """
    Read stored technical indicator records.

    This service is read-only. It does not calculate, update,
    or regenerate technical indicators.
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

    base_conditions = [
        TechnicalIndicatorValue.import_batch_id == batch.id,
        TechnicalIndicatorValue.instrument_code == code,
        TechnicalIndicatorValue.timeframe == timeframe,
    ]

    filtered_conditions = list(base_conditions)

    if start_date is not None:
        filtered_conditions.append(
            TechnicalIndicatorValue.period_start >= start_date
        )

    if end_date is not None:
        filtered_conditions.append(
            TechnicalIndicatorValue.period_start <= end_date
        )

    total_records = db.scalar(
        select(func.count())
        .select_from(TechnicalIndicatorValue)
        .where(*filtered_conditions)
    ) or 0

    dataset_count = db.scalar(
        select(func.count())
        .select_from(TechnicalIndicatorValue)
        .where(*base_conditions)
    ) or 0

    latest_date = db.scalar(
        select(func.max(TechnicalIndicatorValue.period_end))
        .where(*base_conditions)
    )

    statement = (
        select(TechnicalIndicatorValue)
        .where(*filtered_conditions)
        .order_by(
            TechnicalIndicatorValue.period_start.asc()
        )
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(statement).all()

    records = [
        TechnicalIndicatorRecord(
            period_start=row.period_start,
            period_end=row.period_end,
            source=IndicatorSource(
                table=row.source_table,
                status=row.source_status,
                boundary_alignment_status=row.boundary_alignment_status,
                session_coverage_status=row.session_coverage_status,
            ),
            ohlc=IndicatorOHLC(
                open=row.source_open,
                high=row.source_high,
                low=row.source_low,
                close=row.source_close,
            ),
            moving_averages=MovingAverageIndicators(
                ema_9=row.ema_9,
                ema_20=row.ema_20,
                ema_50=row.ema_50,
                ema_100=row.ema_100,
                ema_200=row.ema_200,
                sma_222=row.sma_222,
            ),
            momentum=MomentumIndicators(
                rsi_14=row.rsi_14,
            ),
            trend=TrendIndicators(
                adx_14=row.adx_14,
                plus_di_14=row.plus_di_14,
                minus_di_14=row.minus_di_14,
            ),
            macd=MACDIndicators(
                line_12_26=row.macd_line_12_26,
                signal_9=row.macd_signal_9,
                histogram=row.macd_histogram,
            ),
            volatility=VolatilityIndicators(
                atr_14=row.atr_14,
                chop_14=row.chop_14,
                bollinger_bandwidth_20_2=row.bollinger_bandwidth_20_2,
                bollinger_upper_20_2=row.bollinger_upper_20_2,
                bollinger_middle_20_2=row.bollinger_middle_20_2,
                bollinger_lower_20_2=row.bollinger_lower_20_2,
            ),
            calculation=IndicatorCalculationMetadata(
                status=row.calculation_status,
                version=row.calculation_version,
                generated_at_utc=row.generated_at_utc,
            ),
        )
        for row in rows
    ]

    if total_records > 0:
        availability_status = "available"
        message = None
    elif dataset_count > 0:
        availability_status = "no_records_in_range"
        message = "No indicator records match the requested date range."
    else:
        availability_status = "no_data"
        message = (
            "No technical indicator records are available "
            "for this instrument and timeframe."
        )

    return TechnicalIndicatorResponse(
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
