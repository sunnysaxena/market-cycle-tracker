
"""Read-only query service for candlestick pattern analysis.

Loads and analyzes complete historical candle sequences before
applying API-level date filtering and pagination.

Pattern indices always refer to the original chronological dataset.
"""

from datetime import date, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.engines.indicator_engine import SUPPORTED_TIMEFRAMES
from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)
from app.schemas.candlestick import (
    CandlestickCalculationMetadata,
    CandlestickOHLC,
    CandlestickPatternResponse,
    CandlestickRecord,
    MultiCandlePatternRecord,
    TwoCandlePatternRecord,
)
from app.services.batch_service import resolve_import_batch
from app.services.candlestick_database_service import (
    NoEligibleCandlesError,
    get_candlestick_analysis,
)


CandlestickTimeframe = Literal["1D", "1W", "1M", "1Y"]


def _as_date(value: date | datetime) -> date:
    """Normalize a date or datetime to a calendar date."""

    if isinstance(value, datetime):
        return value.date()

    return value


def get_candlestick_patterns(
    db: Session,
    *,
    instrument_code: str,
    timeframe: CandlestickTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> CandlestickPatternResponse:
    """
    Return unified candlestick pattern analysis.

    Complete historical analysis is performed before date filtering
    and pagination to preserve patterns across page boundaries.

    This service is read-only.
    """

    if not isinstance(instrument_code, str) or not instrument_code.strip():
        raise ValueError("instrument_code must be a non-empty string.")

    code = instrument_code.strip().upper()

    if not isinstance(timeframe, str):
        raise ValueError("timeframe must be a string.")

    normalized_timeframe = timeframe.strip().upper()

    if normalized_timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe: {normalized_timeframe}. "
            f"Supported timeframes: {SUPPORTED_TIMEFRAMES}."
        )

    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError(
                "start_date must not be after end_date."
            )

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")

    if not 1 <= limit <= 2000:
        raise ValueError("limit must be between 1 and 2000.")

    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("offset must be an integer.")

    if offset < 0:
        raise ValueError("offset must not be negative.")

    batch = resolve_import_batch(
        db,
        import_batch_id=import_batch_id,
    )

    try:
        database_result = get_candlestick_analysis(
            db,
            instrument_code=code,
            timeframe=normalized_timeframe,
            import_batch_id=batch.id,
        )

        source_candles = database_result.candles
        analysis = database_result.analysis
        source_table = database_result.source_table

        first_period_start = database_result.first_period_start
        last_period_end = database_result.last_period_end
        dataset_count = database_result.candle_count

    except NoEligibleCandlesError:
        source_candles = ()
        dataset_count = 0

        source_table = (
            "daily_ohlcv"
            if normalized_timeframe == "1D"
            else "aggregated_ohlcv"
        )

        first_period_start = None
        last_period_end = None

        analysis = None

    filtered_indexed_candles = [
        (index, candle)
        for index, candle in enumerate(source_candles)
        if (
            start_date is None
            or _as_date(candle.period_start) >= start_date
        )
        and (
            end_date is None
            or _as_date(candle.period_start) <= end_date
        )
    ]

    total_records = len(filtered_indexed_candles)

    page_indexed_candles = filtered_indexed_candles[
        offset:offset + limit
    ]

    page_indices = {
        index
        for index, _ in page_indexed_candles
    }

    single_patterns_by_index = (
        {
            item.candle_index: list(item.result.patterns)
            for item in analysis.single_candle_results
        }
        if analysis is not None
        else {}
    )

    candle_records = [
        CandlestickRecord(
            candle_index=index,
            period_start=candle.period_start,
            period_end=candle.period_end,
            ohlc=CandlestickOHLC(
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
            ),
            patterns=single_patterns_by_index.get(index, []),
        )
        for index, candle in page_indexed_candles
    ]

    two_candle_patterns = (
        [
            TwoCandlePatternRecord(
                pattern=match.pattern,
                start_index=match.start_index,
                end_index=match.end_index,
            )
            for match in analysis.two_candle_matches
            if match.end_index in page_indices
        ]
        if analysis is not None
        else []
    )

    multi_candle_patterns = (
        [
            MultiCandlePatternRecord(
                pattern=match.pattern,
                candle_count=match.candle_count,
                start_index=match.start_index,
                end_index=match.end_index,
            )
            for match in analysis.multi_candle_matches
            if match.end_index in page_indices
        ]
        if analysis is not None
        else []
    )

    if total_records > 0:
        availability_status = "available"
        message = None
    elif dataset_count > 0:
        availability_status = "no_records_in_range"
        message = (
            "No candlestick records match the requested date range."
        )
    else:
        availability_status = "no_data"
        message = (
            "No eligible candlestick records are available "
            "for this instrument and timeframe."
        )

    latest_date = (
        _as_date(last_period_end)
        if last_period_end is not None
        else None
    )

    if analysis is not None:
        calculation = CandlestickCalculationMetadata(
            single_candle_version=(
                analysis.single_candle_calculation_version
            ),
            two_candle_version=(
                analysis.two_candle_calculation_version
            ),
            multi_candle_version=(
                analysis.multi_candle_calculation_version
            ),
        )
    else:
        from app.engines.candlestick_pattern_config import (
            CALCULATION_VERSION,
        )
        from app.engines.candlestick_multi_candle_engine import (
            MULTI_CANDLE_CALCULATION_VERSION,
        )

        calculation = CandlestickCalculationMetadata(
            single_candle_version=CALCULATION_VERSION,
            two_candle_version=CALCULATION_VERSION,
            multi_candle_version=MULTI_CANDLE_CALCULATION_VERSION,
        )

    return CandlestickPatternResponse(
        instrument_code=code,
        timeframe=normalized_timeframe,
        source_table=source_table,
        batch=BatchMetadata.model_validate(batch),
        first_period_start=first_period_start,
        last_period_end=last_period_end,
        candles=candle_records,
        two_candle_patterns=two_candle_patterns,
        multi_candle_patterns=multi_candle_patterns,
        calculation=calculation,
        pagination=PaginationMetadata(
            limit=limit,
            offset=offset,
            returned_count=len(candle_records),
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
