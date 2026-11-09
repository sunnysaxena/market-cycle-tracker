
import sqlite3
import sys

from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.engines.ohlcv_aggregator import (
    aggregate_all_timeframes,
    get_period_bounds,
)

DATABASE = (
    BACKEND_DIR / "data" / "historical_staging.db"
)

INDIA_TZ = timezone(
    timedelta(hours=5, minutes=30),
    name="IST"
)

TIMEFRAMES = ("1W", "1M", "1Y")
ENGINE_VERSION = "1.0"


def get_reference_date():
    return datetime.now(INDIA_TZ).date()


def get_period_status(period_end, reference_date):
    return (
        "completed"
        if period_end < reference_date
        else "provisional"
    )


def create_tables(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS aggregated_ohlcv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            import_batch_id INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            timeframe TEXT NOT NULL,

            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,

            first_session_date TEXT NOT NULL,
            last_session_date TEXT NOT NULL,

            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,

            volume INTEGER,
            volume_status TEXT NOT NULL,

            session_count INTEGER NOT NULL,
            period_status TEXT NOT NULL,

            boundary_alignment_status TEXT NOT NULL,
            session_coverage_status TEXT NOT NULL,

            aggregation_version TEXT NOT NULL,
            generated_at_utc TEXT NOT NULL,

            UNIQUE (
                import_batch_id,
                instrument_code,
                timeframe,
                period_start
            ),

            FOREIGN KEY (import_batch_id)
                REFERENCES import_batches(id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_aggregated_ohlcv_lookup
        ON aggregated_ohlcv (
            instrument_code,
            timeframe,
            period_start
        );

        CREATE TABLE IF NOT EXISTS aggregated_close_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            import_batch_id INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            timeframe TEXT NOT NULL,

            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,

            first_session_date TEXT NOT NULL,
            last_session_date TEXT NOT NULL,

            close REAL NOT NULL,
            session_count INTEGER NOT NULL,

            period_status TEXT NOT NULL,

            aggregation_version TEXT NOT NULL,
            generated_at_utc TEXT NOT NULL,

            UNIQUE (
                import_batch_id,
                instrument_code,
                timeframe,
                period_start
            ),

            FOREIGN KEY (import_batch_id)
                REFERENCES import_batches(id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_aggregated_close_lookup
        ON aggregated_close_series (
            instrument_code,
            timeframe,
            period_start
        );
    """)


def build_close_aggregates(
    records,
    timeframe,
    reference_date,
):
    groups = defaultdict(list)

    for record in records:
        session_date = date.fromisoformat(
            record["candle_date"]
        )

        period_start, period_end = get_period_bounds(
            session_date,
            timeframe,
        )

        groups[(period_start, period_end)].append(record)

    result = []

    for (period_start, period_end), group in sorted(
        groups.items()
    ):
        group.sort(
            key=lambda item: item["candle_date"]
        )

        first_record = group[0]
        last_record = group[-1]

        result.append({
            "timeframe": timeframe,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "first_session_date": first_record["candle_date"],
            "last_session_date": last_record["candle_date"],
            "close": float(last_record["close"]),
            "session_count": len(group),
            "period_status": get_period_status(
                period_end,
                reference_date,
            ),
        })

    return result


def run_builder():
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    connection = sqlite3.connect(
        DATABASE,
        timeout=60,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        create_tables(connection)
        connection.commit()

        batch = connection.execute("""
            SELECT id
            FROM import_batches
            WHERE status = 'completed'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if batch is None:
            raise RuntimeError(
                "No completed historical import batch found."
            )

        batch_id = batch["id"]
        reference_date = get_reference_date()
        generated_at = datetime.now(
            INDIA_TZ
        ).isoformat()

        instruments = [
            row["instrument_code"]
            for row in connection.execute("""
                SELECT DISTINCT instrument_code
                FROM daily_ohlcv_analytical
                WHERE import_batch_id = ?
                ORDER BY instrument_code
            """, (batch_id,)).fetchall()
        ]

        if not instruments:
            raise RuntimeError(
                "No curated Daily OHLC records found."
            )

        connection.execute("BEGIN IMMEDIATE")

        # Idempotent rebuild: generated data only.
        # Original and curated Daily records are untouched.
        connection.execute("""
            DELETE FROM aggregated_ohlcv
            WHERE import_batch_id = ?
        """, (batch_id,))

        connection.execute("""
            DELETE FROM aggregated_close_series
            WHERE import_batch_id = ?
        """, (batch_id,))

        ohlcv_inserted = 0
        close_inserted = 0

        for instrument in instruments:
            print(f"\nProcessing {instrument}...")

            daily_ohlcv = connection.execute("""
                SELECT
                    candle_date AS timestamp,
                    open,
                    high,
                    low,
                    close,
                    volume
                FROM daily_ohlcv_analytical
                WHERE import_batch_id = ?
                  AND instrument_code = ?
                ORDER BY candle_date
            """, (batch_id, instrument)).fetchall()

            daily_close = connection.execute("""
                SELECT
                    candle_date,
                    close
                FROM daily_close_series
                WHERE import_batch_id = ?
                  AND instrument_code = ?
                ORDER BY candle_date
            """, (batch_id, instrument)).fetchall()

            # Convert SQLite rows into ordinary dictionaries.
            ohlcv_records = [
                dict(row)
                for row in daily_ohlcv
            ]

            close_records = [
                dict(row)
                for row in daily_close
            ]

            aggregated = aggregate_all_timeframes(
                ohlcv_records,
                as_of_date=reference_date,
            )

            ohlcv_lookup = {}

            for timeframe in TIMEFRAMES:
                for candle in aggregated[timeframe]:
                    ohlcv_lookup[
                        (timeframe, candle.period_start)
                    ] = candle

            close_lookup = {}

            close_aggregates = {}

            for timeframe in TIMEFRAMES:
                close_aggregates[timeframe] = (
                    build_close_aggregates(
                        close_records,
                        timeframe,
                        reference_date,
                    )
                )

                for candle in close_aggregates[timeframe]:
                    close_lookup[
                        (timeframe, candle["period_start"])
                    ] = candle

            ohlcv_values = []

            for timeframe in TIMEFRAMES:
                for candle in aggregated[timeframe]:

                    close_candle = close_lookup.get((
                        timeframe,
                        candle.period_start.isoformat(),
                    ))

                    # Flag periods where the first or last
                    # full-OHLC session differs from the
                    # wider eligible closing-price series.
                    boundary_status = (
                        "aligned"
                        if close_candle is not None
                        and close_candle["first_session_date"]
                        == candle.first_session_date.isoformat()
                        and close_candle["last_session_date"]
                        == candle.last_session_date.isoformat()
                        else "quality_limited"
                    )

                    ohlcv_values.append((
                        batch_id,
                        instrument,
                        timeframe,
                        candle.period_start.isoformat(),
                        candle.period_end.isoformat(),
                        candle.first_session_date.isoformat(),
                        candle.last_session_date.isoformat(),
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                        candle.volume_status,
                        candle.session_count,
                        candle.period_status,
                        boundary_status,
                        "not_checked",
                        ENGINE_VERSION,
                        generated_at,
                    ))

            close_values = []

            for timeframe in TIMEFRAMES:
                for candle in close_aggregates[timeframe]:
                    close_values.append((
                        batch_id,
                        instrument,
                        timeframe,
                        candle["period_start"],
                        candle["period_end"],
                        candle["first_session_date"],
                        candle["last_session_date"],
                        candle["close"],
                        candle["session_count"],
                        candle["period_status"],
                        ENGINE_VERSION,
                        generated_at,
                    ))

            connection.executemany("""
                INSERT INTO aggregated_ohlcv (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    period_start,
                    period_end,
                    first_session_date,
                    last_session_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    volume_status,
                    session_count,
                    period_status,
                    boundary_alignment_status,
                    session_coverage_status,
                    aggregation_version,
                    generated_at_utc
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, ohlcv_values)

            connection.executemany("""
                INSERT INTO aggregated_close_series (
                    import_batch_id,
                    instrument_code,
                    timeframe,
                    period_start,
                    period_end,
                    first_session_date,
                    last_session_date,
                    close,
                    session_count,
                    period_status,
                    aggregation_version,
                    generated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, close_values)

            ohlcv_inserted += len(ohlcv_values)
            close_inserted += len(close_values)

            for timeframe in TIMEFRAMES:
                print(
                    f"  {timeframe}: "
                    f"OHLC={len(aggregated[timeframe]):,}, "
                    f"Close={len(close_aggregates[timeframe]):,}"
                )

        connection.commit()

        print("\n========== AGGREGATION SUMMARY ==========")
        print(f"Import batch: {batch_id}")
        print(f"Reference date: {reference_date}")
        print(f"Instruments: {len(instruments)}")
        print(f"OHLC aggregates: {ohlcv_inserted:,}")
        print(f"Close aggregates: {close_inserted:,}")

        print("\n========== STORED CANDLE COUNTS ==========")

        results = connection.execute("""
            SELECT
                instrument_code,
                timeframe,
                COUNT(*) AS candle_count
            FROM aggregated_ohlcv
            WHERE import_batch_id = ?
            GROUP BY instrument_code, timeframe
            ORDER BY instrument_code, timeframe
        """, (batch_id,)).fetchall()

        for row in results:
            print(
                f"{row['instrument_code']:12} "
                f"{row['timeframe']:4} "
                f"{row['candle_count']:,}"
            )

        connection.commit()

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print(f"\nSQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(foreign_keys)}")

        output = (
            PROJECT_ROOT
            / "docs"
            / "multi_timeframe_summary.txt"
        )

        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", encoding="utf-8") as file:
            file.write("MULTI-TIMEFRAME AGGREGATION SUMMARY\n")
            file.write("=" * 60 + "\n")
            file.write(f"Import batch: {batch_id}\n")
            file.write(f"Reference date: {reference_date}\n")
            file.write(f"Instruments: {len(instruments)}\n")
            file.write(f"OHLC aggregates: {ohlcv_inserted}\n")
            file.write(f"Close aggregates: {close_inserted}\n\n")

            for row in results:
                file.write(
                    f"{row['instrument_code']} "
                    f"{row['timeframe']}: "
                    f"{row['candle_count']}\n"
                )

            file.write(f"\nSQLite integrity: {integrity}\n")
            file.write(
                f"Foreign-key errors: {len(foreign_keys)}\n"
            )

            file.write(
                "\nSession coverage status: NOT CHECKED\n"
            )

        print(f"Summary saved to: {output}")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    run_builder()
