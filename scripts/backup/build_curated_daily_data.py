
import json
import sqlite3

from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATABASE = (
    PROJECT_ROOT
    / "backend"
    / "data"
    / "historical_staging.db"
)


def create_tables(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS daily_close_series (
            import_batch_id INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            candle_date TEXT NOT NULL,

            close REAL NOT NULL,

            raw_record_id INTEGER NOT NULL,
            source_id TEXT,
            source_table TEXT NOT NULL,

            source_quality_status TEXT NOT NULL,
            issue_codes TEXT NOT NULL,

            PRIMARY KEY (
                import_batch_id,
                instrument_code,
                candle_date
            ),

            FOREIGN KEY (raw_record_id)
                REFERENCES raw_daily_records(id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_daily_close_instrument_date
        ON daily_close_series (
            instrument_code,
            candle_date
        );

        CREATE TABLE IF NOT EXISTS daily_ohlcv_analytical (
            import_batch_id INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            candle_date TEXT NOT NULL,

            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,

            -- Volume is intentionally unavailable
            -- for the current historical datasets.
            volume INTEGER NULL,
            volume_status TEXT NOT NULL DEFAULT 'unavailable',

            -- Preserve the original source volume text.
            source_volume_raw TEXT,

            raw_record_id INTEGER NOT NULL,
            source_id TEXT,
            source_table TEXT NOT NULL,

            quality_status TEXT NOT NULL,
            issue_codes TEXT NOT NULL,

            PRIMARY KEY (
                import_batch_id,
                instrument_code,
                candle_date
            ),

            FOREIGN KEY (raw_record_id)
                REFERENCES raw_daily_records(id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_daily_ohlcv_instrument_date
        ON daily_ohlcv_analytical (
            instrument_code,
            candle_date
        );
    """)


def find_batch(connection):
    return connection.execute("""
        SELECT id, imported_rows
        FROM import_batches
        WHERE status = 'completed'
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()


def get_date(timestamp):
    return datetime.fromisoformat(timestamp).date().isoformat()


def build_data():
    if not DATABASE.is_file():
        raise FileNotFoundError(
            f"Staging database not found: {DATABASE}"
        )

    connection = sqlite3.connect(DATABASE, timeout=60)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        create_tables(connection)
        connection.commit()

        batch = find_batch(connection)

        if batch is None:
            raise RuntimeError(
                "No completed import batch was found."
            )

        batch_id = batch["id"]

        raw_count = batch["imported_rows"]

        assessment_count = connection.execute("""
            SELECT COUNT(*)
            FROM daily_quality_assessments
            WHERE import_batch_id = ?
        """, (batch_id,)).fetchone()[0]

        if assessment_count != raw_count:
            raise RuntimeError(
                f"Assessment count mismatch: "
                f"{assessment_count} vs {raw_count}"
            )

        print(f"Import batch: {batch_id}")
        print(f"Raw source rows: {raw_count:,}")
        print("Creating curated datasets...")

        connection.execute("BEGIN IMMEDIATE")

        # Rebuild only this batch. The raw data and
        # quality assessments are never deleted.
        connection.execute("""
            DELETE FROM daily_close_series
            WHERE import_batch_id = ?
        """, (batch_id,))

        connection.execute("""
            DELETE FROM daily_ohlcv_analytical
            WHERE import_batch_id = ?
        """, (batch_id,))

        close_rows = connection.execute("""
            SELECT
                r.id AS raw_record_id,
                r.source_id,
                r.instrument_code,
                r.source_table,
                r.source_timestamp,
                r.close_raw,

                q.record_status,
                q.issue_codes

            FROM raw_daily_records r

            JOIN daily_quality_assessments q
                ON q.raw_record_id = r.id

            WHERE r.import_batch_id = ?
              AND q.close_eligible = 1

            ORDER BY
                r.instrument_code,
                r.source_timestamp,
                r.source_row_number
        """, (batch_id,)).fetchall()

        close_values = []

        for row in close_rows:
            close = float(row["close_raw"])

            if close <= 0:
                raise ValueError(
                    f"Invalid close found for raw record "
                    f"{row['raw_record_id']}"
                )

            close_values.append((
                batch_id,
                row["instrument_code"],
                get_date(row["source_timestamp"]),
                close,
                row["raw_record_id"],
                row["source_id"],
                row["source_table"],
                row["record_status"],
                row["issue_codes"],
            ))

        connection.executemany("""
            INSERT INTO daily_close_series (
                import_batch_id,
                instrument_code,
                candle_date,
                close,
                raw_record_id,
                source_id,
                source_table,
                source_quality_status,
                issue_codes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, close_values)

        ohlcv_rows = connection.execute("""
            SELECT
                r.id AS raw_record_id,
                r.source_id,
                r.instrument_code,
                r.source_table,
                r.source_timestamp,

                r.open_raw,
                r.high_raw,
                r.low_raw,
                r.close_raw,
                r.volume_raw,

                q.record_status,
                q.issue_codes

            FROM raw_daily_records r

            JOIN daily_quality_assessments q
                ON q.raw_record_id = r.id

            WHERE r.import_batch_id = ?
              AND q.full_ohlc_eligible = 1

            ORDER BY
                r.instrument_code,
                r.source_timestamp,
                r.source_row_number
        """, (batch_id,)).fetchall()

        ohlcv_values = []

        for row in ohlcv_rows:
            o, h, l, c = map(
                float,
                (
                    row["open_raw"],
                    row["high_raw"],
                    row["low_raw"],
                    row["close_raw"],
                ),
            )

            if (
                min(o, h, l, c) <= 0
                or h < max(o, c)
                or l > min(o, c)
                or h < l
            ):
                raise ValueError(
                    f"Invalid OHLC found for raw record "
                    f"{row['raw_record_id']}"
                )

            ohlcv_values.append((
                batch_id,
                row["instrument_code"],
                get_date(row["source_timestamp"]),
                o,
                h,
                l,
                c,
                None,
                "unavailable",
                row["volume_raw"],
                row["raw_record_id"],
                row["source_id"],
                row["source_table"],
                row["record_status"],
                row["issue_codes"],
            ))

        connection.executemany("""
            INSERT INTO daily_ohlcv_analytical (
                import_batch_id,
                instrument_code,
                candle_date,
                open,
                high,
                low,
                close,
                volume,
                volume_status,
                source_volume_raw,
                raw_record_id,
                source_id,
                source_table,
                quality_status,
                issue_codes
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
        """, ohlcv_values)

        connection.commit()

        close_count = connection.execute("""
            SELECT COUNT(*)
            FROM daily_close_series
            WHERE import_batch_id = ?
        """, (batch_id,)).fetchone()[0]

        ohlcv_count = connection.execute("""
            SELECT COUNT(*)
            FROM daily_ohlcv_analytical
            WHERE import_batch_id = ?
        """, (batch_id,)).fetchone()[0]

        print("\n========== CURATED DATA SUMMARY ==========")
        print(f"Raw records: {raw_count:,}")
        print(f"Close-series records: {close_count:,}")
        print(f"Full OHLC records: {ohlcv_count:,}")

        print("\n========== INSTRUMENT BREAKDOWN ==========")

        breakdown = connection.execute("""
            SELECT
                c.instrument_code,
                COUNT(c.candle_date) AS close_count,
                (
                    SELECT COUNT(*)
                    FROM daily_ohlcv_analytical a
                    WHERE a.import_batch_id = c.import_batch_id
                      AND a.instrument_code = c.instrument_code
                ) AS ohlcv_count

            FROM daily_close_series c

            WHERE c.import_batch_id = ?

            GROUP BY c.import_batch_id, c.instrument_code

            ORDER BY c.instrument_code
        """, (batch_id,)).fetchall()

        for row in breakdown:
            print(
                f"{row['instrument_code']}: "
                f"Close={row['close_count']:,}, "
                f"OHLC={row['ohlcv_count']:,}"
            )

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
            / "curated_data_summary.txt"
        )

        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", encoding="utf-8") as file:
            file.write("CURATED DAILY DATA SUMMARY\n")
            file.write("=" * 55 + "\n")
            file.write(f"Import batch: {batch_id}\n")
            file.write(f"Raw records: {raw_count}\n")
            file.write(f"Close records: {close_count}\n")
            file.write(f"Full OHLC records: {ohlcv_count}\n\n")

            for row in breakdown:
                file.write(
                    f"{row['instrument_code']}: "
                    f"Close={row['close_count']}, "
                    f"OHLC={row['ohlcv_count']}\n"
                )

            file.write(f"\nSQLite integrity: {integrity}\n")
            file.write(
                f"Foreign-key errors: {len(foreign_keys)}\n"
            )

        print(f"Summary saved to: {output}")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    build_data()
