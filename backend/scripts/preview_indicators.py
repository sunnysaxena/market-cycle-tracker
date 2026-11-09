
"""Read-only preview of historical technical-indicator calculations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.database import SessionLocal
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
from app.services.indicator_service import _load_candles


BATCH_ID = 5

FIRST_VALUE_FIELDS = {
    "EMA 9": "ema_9",
    "EMA 20": "ema_20",
    "EMA 50": "ema_50",
    "EMA 100": "ema_100",
    "EMA 200": "ema_200",
    "SMA 222": "sma_222",
    "RSI 14": "rsi_14",
    "ADX 14": "adx_14",
    "MACD signal": "macd_signal_9",
    "ATR 14": "atr_14",
    "Bollinger": "bollinger_middle_20_2",
}


def format_date(value):
    return value.isoformat() if value is not None else "N/A"


def main():

    print("=" * 75)
    print("MARKET CYCLE TRACKER - INDICATOR PREVIEW")
    print("=" * 75)

    print("Snapshot:", BATCH_ID)
    print("Calculation version:", CALCULATION_VERSION)
    print("Instruments:", ", ".join(PRICE_INDEX_CODES))
    print("Timeframes:", ", ".join(SUPPORTED_TIMEFRAMES))
    print("India VIX: EXCLUDED")
    print("Mode: READ ONLY - NO DATABASE INSERTS")

    totals = Counter()
    first_ready_dates = {}

    session = SessionLocal()

    try:

        snapshot_exists = session.scalar(
            select(HistoricalSnapshot.id).where(
                HistoricalSnapshot.id == BATCH_ID
            )
        )

        if snapshot_exists is None:
            raise RuntimeError(
                f"Historical snapshot {BATCH_ID} does not exist."
            )

        existing_count = session.scalar(
            select(func.count())
            .select_from(TechnicalIndicatorValue)
            .where(
                TechnicalIndicatorValue.import_batch_id == BATCH_ID
            )
        ) or 0

        print("\nExisting indicator rows:", existing_count)

        if existing_count:
            raise RuntimeError(
                "Indicator table is not empty. Preview stopped "
                "to avoid confusing existing and preview results."
            )

        generated_at = datetime.now(timezone.utc)

        print("\n" + "=" * 75)
        print("INSTRUMENT / TIMEFRAME RESULTS")
        print("=" * 75)

        for instrument in PRICE_INDEX_CODES:

            print(f"\n### {instrument}")

            for timeframe in SUPPORTED_TIMEFRAMES:

                candles = _load_candles(
                    session,
                    import_batch_id=BATCH_ID,
                    instrument_code=instrument,
                    timeframe=timeframe,
                )

                if not candles:
                    raise RuntimeError(
                        f"No source candles for {instrument} {timeframe}."
                    )

                results = calculate_indicator_series(
                    candles,
                    instrument_code=instrument,
                    timeframe=timeframe,
                    import_batch_id=BATCH_ID,
                    generated_at_utc=generated_at,
                )

                if not results:
                    raise RuntimeError(
                        f"No eligible candles for {instrument} {timeframe}."
                    )

                statuses = Counter(
                    row["calculation_status"]
                    for row in results
                )

                source_count = len(candles)
                eligible_count = len(results)
                excluded_count = source_count - eligible_count

                totals["source"] += source_count
                totals["eligible"] += eligible_count
                totals["excluded"] += excluded_count
                totals["warming_up"] += statuses["warming_up"]
                totals["partial"] += statuses["partial"]
                totals["ready"] += statuses["ready"]

                print(
                    f"\n{timeframe}: "
                    f"Source={source_count:,} | "
                    f"Eligible={eligible_count:,} | "
                    f"Excluded={excluded_count:,}"
                )

                print(
                    f"  Status: "
                    f"Warming={statuses['warming_up']:,}, "
                    f"Partial={statuses['partial']:,}, "
                    f"Ready={statuses['ready']:,}"
                )

                print(
                    f"  Period: "
                    f"{format_date(results[0]['period_start'])}"
                    f" to "
                    f"{format_date(results[-1]['period_end'])}"
                )

                available = {}

                for label, field in FIRST_VALUE_FIELDS.items():

                    first_row = next(
                        (
                            row
                            for row in results
                            if row[field] is not None
                        ),
                        None,
                    )

                    available[label] = (
                        first_row["period_start"]
                        if first_row else None
                    )

                first_ready = next(
                    (
                        row["period_start"]
                        for row in results
                        if row["calculation_status"] == "ready"
                    ),
                    None,
                )

                first_ready_dates[(instrument, timeframe)] = first_ready

                print("  First available indicator values:")

                for label, first_date in available.items():
                    print(
                        f"    {label:16}: {format_date(first_date)}"
                    )

                print(
                    "  First fully READY period:",
                    format_date(first_ready),
                )

        print("\n" + "=" * 75)
        print("OVERALL PREVIEW SUMMARY")
        print("=" * 75)

        print("Source candles:", f"{totals['source']:,}")
        print("Eligible candles:", f"{totals['eligible']:,}")
        print("Excluded candles:", f"{totals['excluded']:,}")
        print("Indicator rows expected:", f"{totals['eligible']:,}")

        print("\nCalculation status:")
        print("Warming up:", f"{totals['warming_up']:,}")
        print("Partial:", f"{totals['partial']:,}")
        print("Ready:", f"{totals['ready']:,}")

        print("\n" + "=" * 75)
        print("DATABASE SAFETY CHECK")
        print("=" * 75)

        final_count = session.scalar(
            select(func.count())
            .select_from(TechnicalIndicatorValue)
            .where(
                TechnicalIndicatorValue.import_batch_id == BATCH_ID
            )
        ) or 0

        print("Indicator rows before preview:", existing_count)
        print("Indicator rows after preview:", final_count)

        if final_count != existing_count:
            raise RuntimeError(
                "Unexpected database row-count change during read-only preview."
            )

        print("\nPREVIEW COMPLETED SUCCESSFULLY")
        print("No historical or indicator records were modified.")

    finally:
        session.close()


if __name__ == "__main__":
    main()
