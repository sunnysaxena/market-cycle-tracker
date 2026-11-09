
"""PostgreSQL service for calculating and storing V1 technical indicators.

The caller controls the SQLAlchemy transaction. This service never commits
independently and never modifies historical OHLC source tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import Session
# Register index_master on the shared SQLAlchemy metadata.
import app.models.index  # noqa: F401

from app.engines.indicator_engine import (
    CALCULATION_VERSION,
    PRICE_INDEX_CODES,
    SUPPORTED_TIMEFRAMES,
    calculate_indicator_series,
)
from app.models.historical import (
    HistoricalSnapshot,
    TechnicalIndicatorValue,
)


def _load_candles(
    session: Session,
    *,
    import_batch_id: int,
    instrument_code: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    """Load OHLC candles from the appropriate historical source table."""

    if timeframe == "1D":
        statement = text(
            """
            SELECT
                candle_date AS period_start,
                candle_date AS period_end,
                open,
                high,
                low,
                close,
                quality_status AS source_status,
                NULL::VARCHAR(40) AS boundary_alignment_status,
                NULL::VARCHAR(40) AS session_coverage_status
            FROM daily_ohlcv
            WHERE import_batch_id = :batch_id
              AND instrument_code = :instrument_code
            ORDER BY candle_date
            """
        )
        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
        }

    elif timeframe in ("1W", "1M", "1Y"):
        statement = text(
            """
            SELECT
                period_start,
                period_end,
                open,
                high,
                low,
                close,
                period_status AS source_status,
                boundary_alignment_status,
                session_coverage_status
            FROM aggregated_ohlcv
            WHERE import_batch_id = :batch_id
              AND instrument_code = :instrument_code
              AND timeframe = :timeframe
            ORDER BY period_start
            """
        )
        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
            "timeframe": timeframe,
        }

    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    result = session.execute(statement, params).mappings().all()
    return [dict(row) for row in result]


def calculate_and_store_indicators(
    session: Session,
    *,
    import_batch_id: int = 5,
    replace_existing: bool = False,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Calculate and insert all standard indicators for five price indices.

    Timeframes: 1D, 1W, 1M and 1Y.

    Existing rows cause an error by default. When replace_existing=True,
    existing indicator rows for the five standard instruments in this
    snapshot are deleted before recalculation.

    Transaction ownership remains with the caller.

    Example:
        with SessionLocal.begin() as session:
            summary = calculate_and_store_indicators(
                session,
                import_batch_id=5,
            )
    """

    if import_batch_id <= 0:
        raise ValueError("import_batch_id must be positive.")

    # Confirm that the requested historical snapshot exists.
    snapshot_exists = session.scalar(
        select(HistoricalSnapshot.id).where(
            HistoricalSnapshot.id == import_batch_id
        )
    )

    if snapshot_exists is None:
        raise ValueError(
            f"Historical snapshot {import_batch_id} does not exist."
        )

    # Prevent accidental duplicate insertion or partial recalculation.
    existing_count = (
        session.scalar(
            select(func.count())
            .select_from(TechnicalIndicatorValue)
            .where(
                TechnicalIndicatorValue.import_batch_id
                == import_batch_id
            )
            .where(
                TechnicalIndicatorValue.instrument_code.in_(
                    PRICE_INDEX_CODES
                )
            )
        )
        or 0
    )

    if existing_count > 0 and not replace_existing:
        raise ValueError(
            f"Found {existing_count} existing indicator rows for "
            f"snapshot {import_batch_id}. "
            "Use replace_existing=True only for an intentional "
            "full recalculation."
        )

    if existing_count > 0 and replace_existing:
        session.execute(
            delete(TechnicalIndicatorValue)
            .where(
                TechnicalIndicatorValue.import_batch_id
                == import_batch_id
            )
            .where(
                TechnicalIndicatorValue.instrument_code.in_(
                    PRICE_INDEX_CODES
                )
            )
        )

    generated = generated_at_utc or datetime.now(timezone.utc)

    if generated.tzinfo is None:
        raise ValueError(
            "generated_at_utc must be timezone-aware."
        )

    summary: dict[str, Any] = {
        "import_batch_id": import_batch_id,
        "calculation_version": CALCULATION_VERSION,
        "instruments": {},
        "total_source_rows": 0,
        "total_eligible_rows": 0,
        "total_excluded_rows": 0,
        "total_indicator_rows": 0,
    }

    all_rows: list[dict[str, Any]] = []

    for instrument_code in PRICE_INDEX_CODES:

        instrument_summary: dict[str, Any] = {}

        for timeframe in SUPPORTED_TIMEFRAMES:

            # Load the source candles.
            candles = _load_candles(
                session,
                import_batch_id=import_batch_id,
                instrument_code=instrument_code,
                timeframe=timeframe,
            )

            if not candles:
                raise ValueError(
                    f"No source candles found for "
                    f"{instrument_code} {timeframe} "
                    f"in snapshot {import_batch_id}."
                )

            # Calculate all indicators.
            calculated = calculate_indicator_series(
                candles,
                instrument_code=instrument_code,
                timeframe=timeframe,
                import_batch_id=import_batch_id,
                generated_at_utc=generated,
            )

            if not calculated:
                raise ValueError(
                    f"No eligible source candles for "
                    f"{instrument_code} {timeframe}."
                )

            # Count calculation availability.
            status_counts = {
                "warming_up": 0,
                "partial": 0,
                "ready": 0,
            }

            for row in calculated:
                status = row["calculation_status"]

                if status not in status_counts:
                    raise ValueError(
                        f"Unexpected calculation status: {status}"
                    )

                status_counts[status] += 1

            first_ready_period = next(
                (
                    row["period_start"]
                    for row in calculated
                    if row["calculation_status"] == "ready"
                ),
                None,
            )

            instrument_summary[timeframe] = {
                "source_rows": len(candles),
                "eligible_rows": len(calculated),
                "excluded_rows": len(candles) - len(calculated),
                **status_counts,
                "first_period": calculated[0]["period_start"],
                "last_period": calculated[-1]["period_end"],
                "first_ready_period": first_ready_period,
                "source_table": calculated[0]["source_table"],
            }

            summary["total_source_rows"] += len(candles)
            summary["total_eligible_rows"] += len(calculated)
            summary["total_excluded_rows"] += (
                len(candles) - len(calculated)
            )

            all_rows.extend(calculated)

        summary["instruments"][instrument_code] = (
            instrument_summary
        )

    # Insert in batches. The caller still controls commit/rollback.
    if all_rows:

        statement = insert(TechnicalIndicatorValue)

        for start in range(0, len(all_rows), 1000):
            chunk = all_rows[start:start + 1000]
            session.execute(statement, chunk)

    session.flush()

    summary["total_indicator_rows"] = len(all_rows)

    return summary


def calculate_and_update_sideways_indicators(
    session: Session,
    *,
    import_batch_id: int = 5,
    apply: bool = False,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """
    Calculate CHOP 14 and Bollinger BandWidth for existing indicator rows.

    Preview mode is the default. When apply=False, no database records
    are modified.

    When apply=True, only these columns are updated:
        - chop_14
        - bollinger_bandwidth_20_2
        - calculation_version
        - generated_at_utc

    All other indicator fields and calculation statuses are preserved.

    The function verifies that calculated source keys exactly match
    existing indicator primary keys before performing any updates.

    The caller controls transaction commit/rollback.
    """

    if import_batch_id <= 0:
        raise ValueError("import_batch_id must be positive.")

    snapshot_exists = session.scalar(
        select(HistoricalSnapshot.id).where(
            HistoricalSnapshot.id == import_batch_id
        )
    )

    if snapshot_exists is None:
        raise ValueError(
            f"Historical snapshot {import_batch_id} does not exist."
        )

    generated = generated_at_utc or datetime.now(timezone.utc)

    if generated.tzinfo is None:
        raise ValueError(
            "generated_at_utc must be timezone-aware."
        )

    # -----------------------------------------------------
    # LOAD EXISTING PRIMARY KEYS
    # -----------------------------------------------------

    existing_rows = session.execute(
        select(
            TechnicalIndicatorValue.import_batch_id,
            TechnicalIndicatorValue.instrument_code,
            TechnicalIndicatorValue.timeframe,
            TechnicalIndicatorValue.period_start,
        ).where(
            TechnicalIndicatorValue.import_batch_id
            == import_batch_id
        ).where(
            TechnicalIndicatorValue.instrument_code.in_(
                PRICE_INDEX_CODES
            )
        )
    ).all()

    existing_keys = {
        tuple(row)
        for row in existing_rows
    }

    if not existing_keys:
        raise ValueError(
            "No existing technical indicator records found."
        )

    updates: list[dict[str, Any]] = []
    calculated_keys: set[tuple] = set()

    summary: dict[str, Any] = {
        "import_batch_id": import_batch_id,
        "calculation_version": CALCULATION_VERSION,
        "mode": "APPLY" if apply else "PREVIEW",
        "existing_rows": len(existing_keys),
        "calculated_rows": 0,
        "chop_available": 0,
        "chop_null": 0,
        "bandwidth_available": 0,
        "bandwidth_null": 0,
        "instruments": {},
        "applied": False,
    }

    # -----------------------------------------------------
    # RECALCULATE FROM ORIGINAL OHLC SOURCES
    # -----------------------------------------------------

    for instrument_code in PRICE_INDEX_CODES:

        instrument_summary: dict[str, Any] = {}

        for timeframe in SUPPORTED_TIMEFRAMES:

            candles = _load_candles(
                session,
                import_batch_id=import_batch_id,
                instrument_code=instrument_code,
                timeframe=timeframe,
            )

            if not candles:
                raise ValueError(
                    f"No source candles found for "
                    f"{instrument_code} {timeframe}."
                )

            calculated = calculate_indicator_series(
                candles,
                instrument_code=instrument_code,
                timeframe=timeframe,
                import_batch_id=import_batch_id,
                generated_at_utc=generated,
            )

            if not calculated:
                raise ValueError(
                    f"No eligible candles calculated for "
                    f"{instrument_code} {timeframe}."
                )

            chop_available = 0
            bandwidth_available = 0

            for row in calculated:

                key = (
                    row["import_batch_id"],
                    row["instrument_code"],
                    row["timeframe"],
                    row["period_start"],
                )

                if key in calculated_keys:
                    raise ValueError(
                        f"Duplicate calculated key: {key}"
                    )

                calculated_keys.add(key)

                chop_value = row.get("chop_14")
                bandwidth_value = row.get(
                    "bollinger_bandwidth_20_2"
                )

                if chop_value is not None:
                    chop_available += 1

                if bandwidth_value is not None:
                    bandwidth_available += 1

                # Only the two new indicators and calculation
                # metadata are included in the update mapping.
                updates.append({
                    "import_batch_id": row["import_batch_id"],
                    "instrument_code": row["instrument_code"],
                    "timeframe": row["timeframe"],
                    "period_start": row["period_start"],
                    "chop_14": chop_value,
                    "bollinger_bandwidth_20_2": bandwidth_value,
                    "calculation_version": CALCULATION_VERSION,
                    "generated_at_utc": generated,
                })

            instrument_summary[timeframe] = {
                "source_rows": len(candles),
                "eligible_rows": len(calculated),
                "excluded_rows": len(candles) - len(calculated),
                "chop_available": chop_available,
                "chop_null": len(calculated) - chop_available,
                "bandwidth_available": bandwidth_available,
                "bandwidth_null": (
                    len(calculated) - bandwidth_available
                ),
            }

            summary["calculated_rows"] += len(calculated)
            summary["chop_available"] += chop_available
            summary["chop_null"] += (
                len(calculated) - chop_available
            )
            summary["bandwidth_available"] += bandwidth_available
            summary["bandwidth_null"] += (
                len(calculated) - bandwidth_available
            )

        summary["instruments"][instrument_code] = (
            instrument_summary
        )

    # -----------------------------------------------------
    # VERIFY EXACT PRIMARY KEY MATCH
    # -----------------------------------------------------

    missing_existing = calculated_keys - existing_keys
    orphan_existing = existing_keys - calculated_keys

    summary["calculated_rows"] = len(calculated_keys)
    summary["missing_existing_keys"] = len(missing_existing)
    summary["orphan_existing_keys"] = len(orphan_existing)
    summary["keys_match"] = (
        calculated_keys == existing_keys
    )

    if calculated_keys != existing_keys:
        raise ValueError(
            "Safety check failed. Calculated source keys do not "
            "exactly match existing indicator records. "
            f"Missing existing keys: {len(missing_existing)}. "
            f"Orphan existing keys: {len(orphan_existing)}. "
            "No updates were performed."
        )

    # -----------------------------------------------------
    # APPLY TARGETED UPDATE
    # -----------------------------------------------------

    if apply:

        statement = update(TechnicalIndicatorValue)

        for start in range(0, len(updates), 1000):

            chunk = updates[start:start + 1000]

            session.execute(
                statement,
                chunk,
            )

        session.flush()

        summary["applied"] = True

    return summary
