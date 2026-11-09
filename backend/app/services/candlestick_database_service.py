
"""Read-only database service for unified candlestick pattern analysis.

Loads eligible completed OHLC candles from existing historical tables
and delegates pattern recognition to the pure analysis service.

Each loaded candle retains its period boundaries and OHLC values so
API consumers can identify the dates associated with pattern matches.

No database records are inserted, updated, or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.engines.indicator_engine import (
    PRICE_INDEX_CODES,
    SUPPORTED_TIMEFRAMES,
)
from app.models.index import Index
from app.services.api_errors import (
    InstrumentNotFoundError,
    UnsupportedInstrumentCategoryError,
)
from app.services.batch_service import resolve_import_batch
from app.services.candlestick_analysis_service import (
    CandlestickAnalysisResult,
    analyze_candlestick_patterns,
)


@dataclass(frozen=True)
class CandlestickDatabaseCandle:
    """One eligible historical candle with its period boundaries."""

    period_start: date | datetime
    period_end: date | datetime
    open: Any
    high: Any
    low: Any
    close: Any


@dataclass(frozen=True)
class CandlestickDatabaseResult:
    """Database metadata, source candles, and unified analysis."""

    instrument_code: str
    timeframe: str
    import_batch_id: int
    source_table: str
    candle_count: int
    first_period_start: date | datetime
    last_period_end: date | datetime
    candles: tuple[CandlestickDatabaseCandle, ...]
    analysis: CandlestickAnalysisResult


def _resolve_active_price_index(
    session: Session,
    instrument_code: str,
) -> str:
    """Validate and normalize an active supported price index."""

    if (
        not isinstance(instrument_code, str)
        or not instrument_code.strip()
    ):
        raise ValueError(
            "instrument_code must be a non-empty string."
        )

    code = instrument_code.strip().upper()

    if code not in PRICE_INDEX_CODES:
        raise ValueError(
            f"Unsupported candlestick instrument: {code}. "
            f"Supported instruments: {PRICE_INDEX_CODES}."
        )

    index = session.scalar(
        select(Index).where(
            Index.code == code,
            Index.is_active.is_(True),
        )
    )

    if index is None:
        raise InstrumentNotFoundError(
            f"Active instrument '{code}' was not found."
        )

    if index.category != "market_index":
        raise UnsupportedInstrumentCategoryError(
            f"Instrument '{code}' has category '{index.category}'. "
            "Candlestick analysis supports market indices only."
        )

    return code


def _load_eligible_candles(
    session: Session,
    *,
    import_batch_id: int,
    instrument_code: str,
    timeframe: str,
) -> tuple[
    list[dict[str, Any]],
    str,
    date | datetime,
    date | datetime,
]:
    """
    Load eligible OHLC candles and their date boundaries.

    Daily records must have accepted quality status.

    Aggregate records must be completed and boundary-aligned.

    Records are returned oldest to newest.
    """

    if timeframe == "1D":
        statement = text(
            """
            SELECT
                candle_date AS period_start,
                candle_date AS period_end,
                open,
                high,
                low,
                close
            FROM daily_ohlcv
            WHERE import_batch_id = :batch_id
              AND instrument_code = :instrument_code
              AND quality_status = 'accepted'
            ORDER BY candle_date ASC
            """
        )

        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
        }

        source_table = "daily_ohlcv"

    elif timeframe in ("1W", "1M", "1Y"):
        statement = text(
            """
            SELECT
                period_start,
                period_end,
                open,
                high,
                low,
                close
            FROM aggregated_ohlcv
            WHERE import_batch_id = :batch_id
              AND instrument_code = :instrument_code
              AND timeframe = :timeframe
              AND period_status = 'completed'
              AND boundary_alignment_status = 'aligned'
            ORDER BY period_start ASC
            """
        )

        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
            "timeframe": timeframe,
        }

        source_table = "aggregated_ohlcv"

    else:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}. "
            f"Supported timeframes: {SUPPORTED_TIMEFRAMES}."
        )

    rows = (
        session.execute(statement, params)
        .mappings()
        .all()
    )

    if not rows:
        raise ValueError(
            "No eligible candles were found for "
            f"{instrument_code}, timeframe {timeframe}, "
            f"batch {import_batch_id}."
        )

    candles = [
        {
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        }
        for row in rows
    ]

    return (
        candles,
        source_table,
        rows[0]["period_start"],
        rows[-1]["period_end"],
    )


def get_candlestick_analysis(
    session: Session,
    *,
    instrument_code: str,
    timeframe: str,
    import_batch_id: int | None = None,
) -> CandlestickDatabaseResult:
    """
    Load eligible historical candles and run unified pattern analysis.

    If import_batch_id is omitted, the latest completed batch is used.

    The complete chronological candle sequence is analyzed before
    any API-level date filtering or pagination.

    This service is read-only. Transaction ownership remains with
    the caller.
    """

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError(
            "timeframe must be a non-empty string."
        )

    normalized_timeframe = timeframe.strip().upper()

    if normalized_timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe: {normalized_timeframe}. "
            f"Supported timeframes: {SUPPORTED_TIMEFRAMES}."
        )

    code = _resolve_active_price_index(
        session,
        instrument_code,
    )

    batch = resolve_import_batch(
        session,
        import_batch_id=import_batch_id,
    )

    (
        candle_records,
        source_table,
        first_period_start,
        last_period_end,
    ) = _load_eligible_candles(
        session,
        import_batch_id=batch.id,
        instrument_code=code,
        timeframe=normalized_timeframe,
    )

    # Preserve dates and OHLC values for the database/API result.
    database_candles = tuple(
        CandlestickDatabaseCandle(
            period_start=candle["period_start"],
            period_end=candle["period_end"],
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
        )
        for candle in candle_records
    )

    # Pattern engines receive OHLC only. Dates remain external metadata.
    analysis_input = [
        {
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
        for candle in database_candles
    ]

    # Analyze the entire chronological sequence.
    analysis = analyze_candlestick_patterns(analysis_input)

    return CandlestickDatabaseResult(
        instrument_code=code,
        timeframe=normalized_timeframe,
        import_batch_id=batch.id,
        source_table=source_table,
        candle_count=len(database_candles),
        first_period_start=first_period_start,
        last_period_end=last_period_end,
        candles=database_candles,
        analysis=analysis,
    )
