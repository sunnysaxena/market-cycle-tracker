"""Database service for calculating and storing technical indicators."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.engines.indicator_engine import (
    CALCULATION_VERSION,
    PRICE_INDEX_CODES,
    SUPPORTED_TIMEFRAMES,
    calculate_indicator_series,
)
from app.models.historical import HistoricalSnapshot, TechnicalIndicatorValue


def _load_candles(session: Session, *, import_batch_id: int, instrument_code: str, timeframe: str) -> list[dict[str, Any]]:
    if timeframe == "1D":
        statement = text("""
            SELECT candle_date AS period_start, candle_date AS period_end,
                   close, quality_status AS source_status,
                   NULL::VARCHAR(40) AS boundary_alignment_status,
                   NULL::VARCHAR(40) AS session_coverage_status
            FROM daily_ohlcv
            WHERE import_batch_id = :batch_id AND instrument_code = :instrument_code
            ORDER BY candle_date
        """)
    else:
        statement = text("""
            SELECT period_start, period_end, close,
                   period_status AS source_status,
                   boundary_alignment_status, session_coverage_status
            FROM aggregated_ohlcv
            WHERE import_batch_id = :batch_id
              AND instrument_code = :instrument_code
              AND timeframe = :timeframe
            ORDER BY period_start
        """)
    params: dict[str, Any] = {"batch_id": import_batch_id, "instrument_code": instrument_code}
    if timeframe != "1D":
        params["timeframe"] = timeframe
    return [dict(row) for row in session.execute(statement, params).mappings().all()]


def calculate_and_store_indicators(
    session: Session,
    *,
    import_batch_id: int = 5,
    replace_existing: bool = False,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Calculate all indicators for five indices and four timeframes.

    The caller owns the transaction. Recommended:
        with SessionLocal.begin() as session:
            summary = calculate_and_store_indicators(session, import_batch_id=5)

    Existing rows are protected unless replace_existing=True. Replacement only
    deletes rows for this snapshot and the five standard price indices.
    """
    snapshot_exists = session.scalar(select(HistoricalSnapshot.id).where(HistoricalSnapshot.id == import_batch_id))
    if snapshot_exists is None:
        raise ValueError(f"Historical snapshot {import_batch_id} does not exist.")

    existing_count = session.scalar(
        select(func.count()).select_from(TechnicalIndicatorValue)
        .where(TechnicalIndicatorValue.import_batch_id == import_batch_id)
        .where(TechnicalIndicatorValue.instrument_code.in_(PRICE_INDEX_CODES))
    ) or 0
    if existing_count and not replace_existing:
        raise ValueError(
            f"Found {existing_count} indicator rows for snapshot {import_batch_id}. "
            "Pass replace_existing=True only for an intentional recalculation."
        )
    if existing_count and replace_existing:
        session.execute(
            delete(TechnicalIndicatorValue)
            .where(TechnicalIndicatorValue.import_batch_id == import_batch_id)
            .where(TechnicalIndicatorValue.instrument_code.in_(PRICE_INDEX_CODES))
        )

    generated = generated_at_utc or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        raise ValueError("generated_at_utc must be timezone-aware.")

    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "import_batch_id": import_batch_id,
        "calculation_version": CALCULATION_VERSION,
        "instruments": {},
        "total_rows": 0,
    }

    for instrument_code in PRICE_INDEX_CODES:
        instrument_summary: dict[str, Any] = {}
        for timeframe in SUPPORTED_TIMEFRAMES:
            candles = _load_candles(
                session, import_batch_id=import_batch_id,
                instrument_code=instrument_code, timeframe=timeframe,
            )
            if not candles:
                raise ValueError(f"No source candles for {instrument_code} {timeframe} in snapshot {import_batch_id}.")
            calculated = calculate_indicator_series(
                candles,
                instrument_code=instrument_code,
                timeframe=timeframe,
                import_batch_id=import_batch_id,
                generated_at_utc=generated,
            )
            if not calculated:
                raise ValueError(f"No eligible source candles for {instrument_code} {timeframe}.")

            status_counts = {"warming_up": 0, "partial": 0, "ready": 0}
            for row in calculated:
                status_counts[row["calculation_status"]] += 1
            ready_dates = [row["period_end"] for row in calculated if row["calculation_status"] == "ready"]
            instrument_summary[timeframe] = {
                "source_rows": len(candles),
                "calculated_rows": len(calculated),
                **status_counts,
                "first_period": calculated[0]["period_start"],
                "last_period": calculated[-1]["period_end"],
                "first_ready_period": ready_dates[0] if ready_dates else None,
            }
            all_rows.extend(calculated)
        summary["instruments"][instrument_code] = instrument_summary

    if all_rows:
        session.execute(pg_insert(TechnicalIndicatorValue), all_rows)
    session.flush()
    summary["total_rows"] = len(all_rows)
    return summary
