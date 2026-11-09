"""PostgreSQL persistence service for Market Cycle Engine V1.

Loads every original source candle, including rejected candles, together
with technical indicators and market-structure snapshots.

Preview is the default. The service verifies exact key matching before
inserting any historical classifications.

The caller owns transaction commit and rollback.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

# Register shared SQLAlchemy metadata.
import app.models.index  # noqa: F401

from app.engines.market_cycle_engine import (
    CALCULATION_VERSION,
    DEFAULT_CONFIG,
    PRICE_INDEX_CODES,
    SUPPORTED_TIMEFRAMES,
    CycleConfig,
    calculate_market_cycles,
)

from app.models.historical import (
    HistoricalSnapshot,
    TechnicalIndicatorValue,
    MarketStructureSnapshot,
    MarketCycleClassification,
)


# ---------------------------------------------------------
# SOURCE LOADER
# ---------------------------------------------------------

def _load_market_cycle_candles(
    session: Session,
    *,
    import_batch_id: int,
    instrument_code: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    """
    Load all original source candles, including rejected candles.

    Technical indicators and market structure are LEFT JOINED so
    rejected source candles remain visible to the cycle engine.
    """

    if timeframe == "1D":

        statement = text("""
            SELECT
                c.candle_date AS period_start,
                c.candle_date AS period_end,
                c.close AS source_close,
                c.quality_status AS source_status,

                NULL::VARCHAR(40) AS boundary_alignment_status,

                i.import_batch_id AS indicator_import_batch_id,
                i.ema_20,
                i.ema_50,
                i.ema_200,
                i.rsi_14,
                i.adx_14,
                i.macd_histogram,
                i.chop_14,
                i.bollinger_bandwidth_20_2,

                s.import_batch_id AS structure_import_batch_id,
                s.market_structure_state,
                s.breakout_status

            FROM daily_ohlcv c

            LEFT JOIN technical_indicator_values i
              ON i.import_batch_id = c.import_batch_id
             AND i.instrument_code = c.instrument_code
             AND i.timeframe = '1D'
             AND i.period_start = c.candle_date

            LEFT JOIN market_structure_snapshots s
              ON s.import_batch_id = c.import_batch_id
             AND s.instrument_code = c.instrument_code
             AND s.timeframe = '1D'
             AND s.period_start = c.candle_date

            WHERE c.import_batch_id = :batch_id
              AND c.instrument_code = :instrument_code

            ORDER BY c.candle_date
        """)

        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
        }

    elif timeframe in ("1W", "1M", "1Y"):

        statement = text("""
            SELECT
                c.period_start,
                c.period_end,
                c.close AS source_close,
                c.period_status AS source_status,
                c.boundary_alignment_status,

                i.import_batch_id AS indicator_import_batch_id,
                i.ema_20,
                i.ema_50,
                i.ema_200,
                i.rsi_14,
                i.adx_14,
                i.macd_histogram,
                i.chop_14,
                i.bollinger_bandwidth_20_2,

                s.import_batch_id AS structure_import_batch_id,
                s.market_structure_state,
                s.breakout_status

            FROM aggregated_ohlcv c

            LEFT JOIN technical_indicator_values i
              ON i.import_batch_id = c.import_batch_id
             AND i.instrument_code = c.instrument_code
             AND i.timeframe = c.timeframe
             AND i.period_start = c.period_start

            LEFT JOIN market_structure_snapshots s
              ON s.import_batch_id = c.import_batch_id
             AND s.instrument_code = c.instrument_code
             AND s.timeframe = c.timeframe
             AND s.period_start = c.period_start

            WHERE c.import_batch_id = :batch_id
              AND c.instrument_code = :instrument_code
              AND c.timeframe = :timeframe

            ORDER BY c.period_start
        """)

        params = {
            "batch_id": import_batch_id,
            "instrument_code": instrument_code,
            "timeframe": timeframe,
        }

    else:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    result = session.execute(
        statement,
        params,
    ).mappings().all()

    return [dict(row) for row in result]


# ---------------------------------------------------------
# CONFIGURATION SERIALIZATION
# ---------------------------------------------------------

def _serialize_config(
    config: CycleConfig,
) -> dict[str, Any]:

    result = {}

    for item in fields(config):

        value = getattr(config, item.name)

        if isinstance(value, Decimal):
            result[item.name] = str(value)
        else:
            result[item.name] = value

    return result


# ---------------------------------------------------------
# SOURCE ELIGIBILITY
# ---------------------------------------------------------

def _source_is_eligible(
    row: dict[str, Any],
    timeframe: str,
) -> bool:

    status = str(
        row.get("source_status") or ""
    ).lower()

    if timeframe == "1D":
        return status == "accepted"

    alignment = str(
        row.get("boundary_alignment_status") or ""
    ).lower()

    return (
        status == "completed"
        and alignment == "aligned"
    )


# ---------------------------------------------------------
# MAIN PERSISTENCE SERVICE
# ---------------------------------------------------------

def calculate_and_store_market_cycles(
    session: Session,
    *,
    import_batch_id: int = 5,
    apply: bool = False,
    generated_at_utc: datetime | None = None,
    config: CycleConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """
    Calculate historical market-cycle classifications.

    Default:
        apply=False (read-only preview)

    When apply=True:
        Inserts classifications for eligible source candles.

    Existing classifications cause an error. This function does not
    replace historical results or modify technical indicators,
    market structure, or original OHLC records.

    The caller controls the transaction.
    """

    if import_batch_id <= 0:
        raise ValueError(
            "import_batch_id must be positive."
        )

    # -----------------------------------------------------
    # VERIFY HISTORICAL SNAPSHOT
    # -----------------------------------------------------

    snapshot_exists = session.scalar(
        select(HistoricalSnapshot.id).where(
            HistoricalSnapshot.id == import_batch_id
        )
    )

    if snapshot_exists is None:
        raise ValueError(
            f"Historical snapshot {import_batch_id} does not exist."
        )

    generated = (
        generated_at_utc
        or datetime.now(timezone.utc)
    )

    if generated.tzinfo is None:
        raise ValueError(
            "generated_at_utc must be timezone-aware."
        )

    # -----------------------------------------------------
    # PREVENT DUPLICATE INSERTION
    # -----------------------------------------------------

    existing_count = (
        session.scalar(
            select(func.count())
            .select_from(MarketCycleClassification)
            .where(
                MarketCycleClassification.import_batch_id
                == import_batch_id
            )
            .where(
                MarketCycleClassification.instrument_code.in_(
                    PRICE_INDEX_CODES
                )
            )
        )
        or 0
    )

    if existing_count:
        raise ValueError(
            f"Found {existing_count} existing market-cycle "
            f"classifications for snapshot {import_batch_id}. "
            "No records were changed."
        )

    # -----------------------------------------------------
    # PREPARE CONFIGURATION
    # -----------------------------------------------------

    config_json = _serialize_config(config)

    summary: dict[str, Any] = {
        "import_batch_id": import_batch_id,
        "calculation_version": CALCULATION_VERSION,
        "mode": "APPLY" if apply else "PREVIEW",
        "existing_classifications": existing_count,
        "total_source_rows": 0,
        "total_eligible_rows": 0,
        "total_excluded_rows": 0,
        "total_classifications": 0,
        "classification_counts": {
            "ACCUMULATION": 0,
            "MARKUP": 0,
            "DISTRIBUTION": 0,
            "MARKDOWN": 0,
            "SIDEWAYS_CONSOLIDATION": 0,
            "TRANSITION_UNCERTAIN": 0,
            "INSUFFICIENT_DATA": 0,
        },
        "missing_indicator_keys": 0,
        "missing_structure_keys": 0,
        "duplicate_source_keys": 0,
        "keys_match": False,
        "instruments": {},
        "applied": False,
    }

    all_rows: list[dict[str, Any]] = []

    # -----------------------------------------------------
    # PROCESS ALL INSTRUMENTS AND TIMEFRAMES
    # -----------------------------------------------------

    for instrument_code in PRICE_INDEX_CODES:

        instrument_summary: dict[str, Any] = {}

        for timeframe in SUPPORTED_TIMEFRAMES:

            source_rows = _load_market_cycle_candles(
                session,
                import_batch_id=import_batch_id,
                instrument_code=instrument_code,
                timeframe=timeframe,
            )

            if not source_rows:
                raise ValueError(
                    f"No source candles found for "
                    f"{instrument_code} {timeframe}."
                )

            eligible_keys = set()
            indicator_keys = set()
            structure_keys = set()

            eligible_rows = 0

            # -------------------------------------------------
            # VERIFY ELIGIBLE SOURCE RECORDS HAVE BOTH INPUTS
            # -------------------------------------------------

            for row in source_rows:

                if not _source_is_eligible(row, timeframe):
                    continue

                eligible_rows += 1

                key = (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    row["period_start"],
                )

                if key in eligible_keys:
                    summary["duplicate_source_keys"] += 1

                eligible_keys.add(key)

                if row["indicator_import_batch_id"] is not None:
                    indicator_keys.add(key)

                if row["structure_import_batch_id"] is not None:
                    structure_keys.add(key)

            missing_indicators = (
                eligible_keys - indicator_keys
            )

            missing_structures = (
                eligible_keys - structure_keys
            )

            summary["missing_indicator_keys"] += len(
                missing_indicators
            )

            summary["missing_structure_keys"] += len(
                missing_structures
            )

            if missing_indicators or missing_structures:
                raise ValueError(
                    f"Input integrity failure for "
                    f"{instrument_code} {timeframe}. "
                    f"Missing indicators: {len(missing_indicators)}; "
                    f"missing structure: {len(missing_structures)}. "
                    "No classifications were inserted."
                )

            # -------------------------------------------------
            # CALCULATE MARKET CYCLES
            # -------------------------------------------------

            result = calculate_market_cycles(
                source_rows,
                instrument_code=instrument_code,
                timeframe=timeframe,
                config=config,
            )

            calculated_keys = {
                (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    row["period_start"],
                )
                for row in result["classifications"]
            }

            if calculated_keys != eligible_keys:
                missing = eligible_keys - calculated_keys
                unexpected = calculated_keys - eligible_keys

                raise ValueError(
                    f"Classification key mismatch for "
                    f"{instrument_code} {timeframe}. "
                    f"Missing: {len(missing)}; "
                    f"unexpected: {len(unexpected)}."
                )

            # -------------------------------------------------
            # BUILD INSERT ROWS
            # -------------------------------------------------

            for classification in result["classifications"]:

                all_rows.append({
                    **classification,
                    "import_batch_id": import_batch_id,
                    "instrument_code": instrument_code,
                    "timeframe": timeframe,
                    "config_json": config_json,
                    "generated_at_utc": generated,
                })

            instrument_summary[timeframe] = {
                "source_rows": len(source_rows),
                "eligible_rows": eligible_rows,
                "excluded_rows": (
                    len(source_rows) - eligible_rows
                ),
                "classification_count": (
                    result["classification_count"]
                ),
                "segment_count": result["segment_count"],
                "classification_counts": (
                    result["classification_counts"]
                ),
            }

            summary["total_source_rows"] += len(source_rows)
            summary["total_eligible_rows"] += eligible_rows
            summary["total_excluded_rows"] += (
                len(source_rows) - eligible_rows
            )

            for cycle, count in result[
                "classification_counts"
            ].items():
                summary["classification_counts"][cycle] += count

        summary["instruments"][instrument_code] = (
            instrument_summary
        )

    # -----------------------------------------------------
    # FINAL VALIDATION
    # -----------------------------------------------------

    summary["total_classifications"] = len(all_rows)

    summary["keys_match"] = (
        summary["missing_indicator_keys"] == 0
        and summary["missing_structure_keys"] == 0
        and summary["duplicate_source_keys"] == 0
        and summary["total_classifications"]
        == summary["total_eligible_rows"]
    )

    if not summary["keys_match"]:
        raise ValueError(
            "Final market-cycle integrity check failed. "
            "No records were inserted."
        )

    # -----------------------------------------------------
    # INSERT CLASSIFICATIONS
    # -----------------------------------------------------

    if apply and all_rows:

        statement = insert(MarketCycleClassification)

        for start in range(0, len(all_rows), 1000):

            chunk = all_rows[start:start + 1000]

            session.execute(
                statement,
                chunk,
            )

        session.flush()

        summary["applied"] = True

    return summary
