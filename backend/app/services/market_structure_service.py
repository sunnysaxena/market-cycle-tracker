"""PostgreSQL persistence service for Market Structure Engine V1.

Preview is the default. The service verifies calculated snapshots against
existing technical-indicator primary keys before inserting any records.

The caller owns the transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

# Register the shared index metadata.
import app.models.index  # noqa: F401

from app.engines.market_structure_engine import (
    CALCULATION_VERSION,
    DEFAULT_EQUAL_TOLERANCE_PCT,
    DEFAULT_PIVOT_BARS,
    PRICE_INDEX_CODES,
    SUPPORTED_TIMEFRAMES,
    calculate_market_structure,
)

from app.models.historical import (
    HistoricalSnapshot,
    TechnicalIndicatorValue,
    MarketStructureEvent,
    MarketStructureSnapshot,
)

# Reuse the established daily/aggregate OHLC loader.
from app.services.indicator_service import _load_candles


def calculate_and_store_market_structure(
    session: Session,
    *,
    import_batch_id: int = 5,
    apply: bool = False,
    generated_at_utc: datetime | None = None,
    pivot_settings: dict[str, tuple[int, int]] | None = None,
    equal_tolerance_pct: Decimal = DEFAULT_EQUAL_TOLERANCE_PCT,
) -> dict[str, Any]:
    """
    Calculate and optionally insert market-structure events and snapshots.

    Default mode is PREVIEW. No rows are inserted unless apply=True.

    Before insertion, every calculated snapshot key must exactly match
    an existing technical_indicator_values primary key.

    Existing market-structure records are never silently overwritten.

    Transaction ownership remains with the caller.
    """

    if import_batch_id <= 0:
        raise ValueError("import_batch_id must be positive.")

    # -----------------------------------------------------
    # VALIDATE SNAPSHOT
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

    generated = generated_at_utc or datetime.now(timezone.utc)

    if generated.tzinfo is None:
        raise ValueError(
            "generated_at_utc must be timezone-aware."
        )

    tolerance = Decimal(str(equal_tolerance_pct))

    settings = dict(DEFAULT_PIVOT_BARS)

    if pivot_settings is not None:

        unknown_timeframes = (
            set(pivot_settings) - set(SUPPORTED_TIMEFRAMES)
        )

        if unknown_timeframes:
            raise ValueError(
                f"Unsupported pivot timeframes: {unknown_timeframes}"
            )

        settings.update(pivot_settings)

    # -----------------------------------------------------
    # PREVENT ACCIDENTAL DUPLICATE INSERTION
    # -----------------------------------------------------

    existing_event_count = (
        session.scalar(
            select(func.count())
            .select_from(MarketStructureEvent)
            .where(
                MarketStructureEvent.import_batch_id
                == import_batch_id
            )
            .where(
                MarketStructureEvent.instrument_code.in_(
                    PRICE_INDEX_CODES
                )
            )
        )
        or 0
    )

    existing_snapshot_count = (
        session.scalar(
            select(func.count())
            .select_from(MarketStructureSnapshot)
            .where(
                MarketStructureSnapshot.import_batch_id
                == import_batch_id
            )
            .where(
                MarketStructureSnapshot.instrument_code.in_(
                    PRICE_INDEX_CODES
                )
            )
        )
        or 0
    )

    if existing_event_count or existing_snapshot_count:
        raise ValueError(
            "Market-structure records already exist for this snapshot. "
            f"Events: {existing_event_count}; "
            f"snapshots: {existing_snapshot_count}. "
            "No records were changed."
        )

    # -----------------------------------------------------
    # LOAD EXPECTED INDICATOR PRIMARY KEYS
    # -----------------------------------------------------

    indicator_key_rows = session.execute(
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

    expected_keys = {
        tuple(row)
        for row in indicator_key_rows
    }

    if not expected_keys:
        raise ValueError(
            "No existing technical-indicator records found."
        )

    # -----------------------------------------------------
    # CALCULATE ALL INSTRUMENTS AND TIMEFRAMES
    # -----------------------------------------------------

    event_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []

    calculated_keys: set[tuple] = set()
    event_keys: set[tuple] = set()

    summary: dict[str, Any] = {
        "import_batch_id": import_batch_id,
        "calculation_version": CALCULATION_VERSION,
        "mode": "APPLY" if apply else "PREVIEW",
        "existing_indicator_rows": len(expected_keys),
        "total_source_rows": 0,
        "total_eligible_rows": 0,
        "total_excluded_rows": 0,
        "total_events": 0,
        "total_snapshots": 0,
        "instruments": {},
        "missing_indicator_keys": 0,
        "orphan_indicator_keys": 0,
        "keys_match": False,
        "applied": False,
    }

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

            left_bars, right_bars = settings[timeframe]

            result = calculate_market_structure(
                candles,
                instrument_code=instrument_code,
                timeframe=timeframe,
                left_bars=left_bars,
                right_bars=right_bars,
                equal_tolerance_pct=tolerance,
            )

            calculated_for_group = 0

            for snapshot in result["snapshots"]:

                key = (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    snapshot["period_start"],
                )

                if key in calculated_keys:
                    raise ValueError(
                        f"Duplicate market-structure snapshot key: {key}"
                    )

                calculated_keys.add(key)
                calculated_for_group += 1

                snapshot_rows.append({
                    **snapshot,
                    "import_batch_id": import_batch_id,
                    "left_bars": left_bars,
                    "right_bars": right_bars,
                    "equal_tolerance_pct": tolerance,
                    "generated_at_utc": generated,
                })

            for event in result["events"]:

                event_key = (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    event["event_type"],
                    event["pivot_date"],
                )

                if event_key in event_keys:
                    raise ValueError(
                        f"Duplicate market-structure event key: {event_key}"
                    )

                event_keys.add(event_key)

                event_rows.append({
                    **event,
                    "import_batch_id": import_batch_id,
                    "left_bars": left_bars,
                    "right_bars": right_bars,
                    "equal_tolerance_pct": tolerance,
                    "calculation_version": CALCULATION_VERSION,
                    "generated_at_utc": generated,
                })

            instrument_summary[timeframe] = {
                "source_rows": result["source_rows"],
                "eligible_rows": result["eligible_rows"],
                "excluded_rows": result["excluded_rows"],
                "segment_count": result["segment_count"],
                "event_count": result["event_count"],
                "snapshot_count": result["snapshot_count"],
                "left_bars": left_bars,
                "right_bars": right_bars,
            }

            summary["total_source_rows"] += result["source_rows"]
            summary["total_eligible_rows"] += result["eligible_rows"]
            summary["total_excluded_rows"] += result["excluded_rows"]

        summary["instruments"][instrument_code] = (
            instrument_summary
        )

    # -----------------------------------------------------
    # VERIFY EXACT SNAPSHOT KEY MATCH
    # -----------------------------------------------------

    missing_indicator_keys = calculated_keys - expected_keys
    orphan_indicator_keys = expected_keys - calculated_keys

    summary["total_events"] = len(event_rows)
    summary["total_snapshots"] = len(snapshot_rows)

    summary["missing_indicator_keys"] = len(
        missing_indicator_keys
    )

    summary["orphan_indicator_keys"] = len(
        orphan_indicator_keys
    )

    summary["keys_match"] = (
        calculated_keys == expected_keys
    )

    if calculated_keys != expected_keys:
        raise ValueError(
            "Market-structure snapshot keys do not match "
            "technical-indicator keys. "
            f"Missing: {len(missing_indicator_keys)}; "
            f"orphaned: {len(orphan_indicator_keys)}. "
            "No records were inserted."
        )

    # -----------------------------------------------------
    # APPLY INSERTION
    # -----------------------------------------------------

    if apply:

        if event_rows:

            statement = insert(MarketStructureEvent)

            for start in range(0, len(event_rows), 1000):
                session.execute(
                    statement,
                    event_rows[start:start + 1000],
                )

        if snapshot_rows:

            statement = insert(MarketStructureSnapshot)

            for start in range(0, len(snapshot_rows), 1000):
                session.execute(
                    statement,
                    snapshot_rows[start:start + 1000],
                )

        session.flush()

        summary["applied"] = True

    return summary
