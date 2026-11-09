from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"

LEGACY_BATCH_ID = 1
EXTERNAL_BATCH_IDS = (1, 2)
REPLACE_FROM = "2015-01-01"
REPLACE_TO = "2016-12-31"
INSTRUMENT = "BANKNIFTY"
NEW_SOURCE_TABLE_PREFIX = "nse_indices_historical"

RAW_FIELDS = (
    "instrument_code",
    "source_table",
    "source_row_number",
    "source_id",
    "source_timestamp",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
    "volume_raw",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def get_preflight(con: sqlite3.Connection) -> dict[str, Any]:
    required_tables = (
        "import_batches",
        "raw_daily_records",
        "daily_quality_assessments",
        "daily_close_series",
        "daily_ohlcv_analytical",
        "external_index_source_batches",
        "external_index_daily_records",
        "exchange_calendar_events",
    )
    missing = [name for name in required_tables if not table_exists(con, name)]
    if missing:
        raise RuntimeError(f"Required tables are missing: {', '.join(missing)}")

    legacy = con.execute(
        "SELECT * FROM import_batches WHERE id=?", (LEGACY_BATCH_ID,)
    ).fetchone()
    if legacy is None or legacy["status"] != "completed":
        raise RuntimeError("Legacy import batch 1 is missing or not completed.")

    # The current project state has one legacy completed batch. Avoid silently
    # composing from an unexpected later snapshot.
    completed = con.execute(
        "SELECT id FROM import_batches WHERE status='completed' ORDER BY id"
    ).fetchall()
    if [row["id"] for row in completed] != [LEGACY_BATCH_ID]:
        raise RuntimeError(
            "Expected only legacy batch 1 to be completed. Found completed "
            f"batches: {[row['id'] for row in completed]}"
        )

    ext_batches = con.execute(
        f"SELECT * FROM external_index_source_batches WHERE id IN ({','.join('?' for _ in EXTERNAL_BATCH_IDS)}) ORDER BY calendar_year",
        EXTERNAL_BATCH_IDS,
    ).fetchall()
    if len(ext_batches) != 2:
        raise RuntimeError("Expected external NSE source batches 1 and 2.")

    expected_years = {2015: 248, 2016: 247}
    for batch in ext_batches:
        year = int(batch["calendar_year"])
        if year not in expected_years:
            raise RuntimeError(f"Unexpected external calendar year: {year}")
        if batch["import_status"] != "staged_validated":
            raise RuntimeError(
                f"External batch {batch['id']} is not staged_validated."
            )
        if batch["instrument_code"] != INSTRUMENT:
            raise RuntimeError(
                f"External batch {batch['id']} is not BANKNIFTY."
            )
        if batch["source_row_count"] != expected_years[year]:
            raise RuntimeError(
                f"External batch {batch['id']} row count mismatch: "
                f"{batch['source_row_count']} vs {expected_years[year]}"
            )
        if batch["unique_date_count"] != expected_years[year]:
            raise RuntimeError(
                f"External batch {batch['id']} unique-date count mismatch."
            )
        if batch["calendar_missing_dates_json"] != "[]" or batch["calendar_unexpected_dates_json"] != "[]":
            raise RuntimeError(
                f"External batch {batch['id']} has calendar mismatch records."
            )

    if {int(row["calendar_year"]) for row in ext_batches} != {2015, 2016}:
        raise RuntimeError("External NSE batches do not cover exactly 2015 and 2016.")

    external_count = con.execute(
        f"SELECT COUNT(*) AS n FROM external_index_daily_records WHERE batch_id IN ({','.join('?' for _ in EXTERNAL_BATCH_IDS)})",
        EXTERNAL_BATCH_IDS,
    ).fetchone()["n"]
    if external_count != 495:
        raise RuntimeError(f"Expected 495 staged NSE rows; found {external_count}.")

    invalid_ext = con.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM external_index_daily_records
        WHERE batch_id IN ({','.join('?' for _ in EXTERNAL_BATCH_IDS)})
          AND (
              instrument_code != 'BANKNIFTY'
              OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
              OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
              OR high < low OR high < open OR high < close
              OR low > open OR low > close
              OR date(candle_date) IS NULL
          )
        """,
        EXTERNAL_BATCH_IDS,
    ).fetchone()["n"]
    if invalid_ext:
        raise RuntimeError(f"Found {invalid_ext} invalid staged NSE records.")

    # Confirm source rows have quality assessments before copying the legacy
    # snapshot. The earlier audit showed one assessment per raw row.
    missing_quality = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM raw_daily_records r
        LEFT JOIN daily_quality_assessments q ON q.raw_record_id=r.id
        WHERE r.import_batch_id=? AND q.raw_record_id IS NULL
        """,
        (LEGACY_BATCH_ID,),
    ).fetchone()["n"]
    if missing_quality:
        raise RuntimeError(
            f"Legacy batch has {missing_quality} raw rows without quality assessments."
        )

    legacy_raw = con.execute(
        "SELECT COUNT(*) AS n FROM raw_daily_records WHERE import_batch_id=?",
        (LEGACY_BATCH_ID,),
    ).fetchone()["n"]
    replaced_raw = con.execute(
        """
        SELECT COUNT(*) AS n FROM raw_daily_records
        WHERE import_batch_id=? AND instrument_code=?
          AND date(source_timestamp) BETWEEN ? AND ?
        """,
        (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO),
    ).fetchone()["n"]
    if (legacy_raw, replaced_raw) != (19875, 221):
        raise RuntimeError(
            "Legacy raw counts differ from the inspected project state: "
            f"total={legacy_raw}, BANKNIFTY rows to replace={replaced_raw}."
        )

    old_close = con.execute(
        "SELECT COUNT(*) AS n FROM daily_close_series WHERE import_batch_id=?",
        (LEGACY_BATCH_ID,),
    ).fetchone()["n"]
    replaced_close = con.execute(
        """
        SELECT COUNT(*) AS n FROM daily_close_series
        WHERE import_batch_id=? AND instrument_code=?
          AND candle_date BETWEEN ? AND ?
        """,
        (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO),
    ).fetchone()["n"]
    old_ohlc = con.execute(
        "SELECT COUNT(*) AS n FROM daily_ohlcv_analytical WHERE import_batch_id=?",
        (LEGACY_BATCH_ID,),
    ).fetchone()["n"]
    replaced_ohlc = con.execute(
        """
        SELECT COUNT(*) AS n FROM daily_ohlcv_analytical
        WHERE import_batch_id=? AND instrument_code=?
          AND candle_date BETWEEN ? AND ?
        """,
        (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO),
    ).fetchone()["n"]

    # Verify the special Saturday and Muhurat dates are included in the staged
    # BANKNIFTY records and explicitly marked special in the exchange calendar.
    special_dates = ("2015-02-28", "2015-11-11", "2016-10-30")
    for special_date in special_dates:
        staged = con.execute(
            f"""
            SELECT COUNT(*) AS n FROM external_index_daily_records
            WHERE batch_id IN ({','.join('?' for _ in EXTERNAL_BATCH_IDS)})
              AND instrument_code=? AND candle_date=?
            """,
            (*EXTERNAL_BATCH_IDS, INSTRUMENT, special_date),
        ).fetchone()["n"]
        event = con.execute(
            """
            SELECT COUNT(*) AS n FROM exchange_calendar_events
            WHERE exchange='NSE' AND market_segment='EQUITY'
              AND session_date=? AND event_type='special_session_open'
            """,
            (special_date,),
        ).fetchone()["n"]
        if staged != 1 or event != 1:
            raise RuntimeError(
                f"Special session {special_date} is not represented exactly once "
                "in both staged prices and exchange calendar."
            )

    # Full-snapshot target counts derived from the inspected current dataset.
    expected = {
        "raw_daily_records": legacy_raw - replaced_raw + external_count,
        "daily_quality_assessments": legacy_raw - replaced_raw + external_count,
        "daily_close_series": old_close - replaced_close + external_count,
        "daily_ohlcv_analytical": old_ohlc - replaced_ohlc + external_count,
    }

    # Calculate the new raw snapshot fingerprint from the exact source values
    # that will be copied into the next batch.
    digest = hashlib.sha256()
    digest.update(b"market-cycle-tracker-composite-raw-snapshot-v1\n")
    raw_query = con.execute(
        """
        SELECT instrument_code, source_table, source_row_number, source_id,
               source_timestamp, open_raw, high_raw, low_raw, close_raw, volume_raw
        FROM raw_daily_records
        WHERE import_batch_id=?
          AND NOT (
              instrument_code=?
              AND date(source_timestamp) BETWEEN ? AND ?
          )
        ORDER BY source_table, source_row_number, id
        """,
        (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO),
    )
    for row in raw_query:
        digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")

    ext_query = con.execute(
        f"""
        SELECT r.id, r.batch_id, b.calendar_year, r.source_row_number,
               r.candle_date, r.open_raw, r.high_raw, r.low_raw, r.close_raw
        FROM external_index_daily_records r
        JOIN external_index_source_batches b ON b.id=r.batch_id
        WHERE r.batch_id IN ({','.join('?' for _ in EXTERNAL_BATCH_IDS)})
        ORDER BY r.candle_date
        """,
        EXTERNAL_BATCH_IDS,
    )
    for row in ext_query:
        ext_id, ext_batch_id, year, source_row_number, candle_date, o, h, l, c = row
        source_table = f"{NEW_SOURCE_TABLE_PREFIX}_{year}"
        source_id = f"NSE_EXT:{ext_id}"
        source_timestamp = f"{candle_date} 00:00:00"
        values = [
            INSTRUMENT, source_table, source_row_number, source_id,
            source_timestamp, o, h, l, c, None,
        ]
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")

    return {
        "legacy": legacy,
        "external_batches": ext_batches,
        "external_count": external_count,
        "legacy_raw": legacy_raw,
        "replaced_raw": replaced_raw,
        "old_close": old_close,
        "replaced_close": replaced_close,
        "old_ohlc": old_ohlc,
        "replaced_ohlc": replaced_ohlc,
        "expected": expected,
        "source_sha256": digest.hexdigest(),
        "source_size_bytes": int(legacy["source_size_bytes"]) + sum(
            int(row["source_size_bytes"]) for row in ext_batches
        ),
    }


def print_plan(plan: dict[str, Any]) -> None:
    print("\nBANKNIFTY NSE HISTORICAL SNAPSHOT PROMOTION")
    print("=" * 78)
    print("Mode:", "APPLY" if APPLY_MODE else "DRY RUN")
    print("Database:", DATABASE)
    print("Legacy batch:", LEGACY_BATCH_ID, "(preserved unchanged)")
    print("External NSE batches:", ", ".join(str(x["id"]) for x in plan["external_batches"]))
    print("Replacement window:", f"{REPLACE_FROM} to {REPLACE_TO}")
    print("\nPROMOTION PLAN")
    print("-" * 78)
    print("Legacy raw rows:", plan["legacy_raw"])
    print("Legacy BANKNIFTY raw rows replaced:", plan["replaced_raw"])
    print("NSE BANKNIFTY rows added:", plan["external_count"])
    print("Expected new raw rows:", plan["expected"]["raw_daily_records"])
    print("Expected new quality assessments:", plan["expected"]["daily_quality_assessments"])
    print("Expected new daily close rows:", plan["expected"]["daily_close_series"])
    print("Expected new full-OHLC rows:", plan["expected"]["daily_ohlcv_analytical"])
    print("\nBANKNIFTY 2015–2016 after promotion:")
    print("  Daily close rows:", plan["external_count"])
    print("  Full OHLC rows:", plan["external_count"])
    print("  Legacy records retained in batch 1: yes")
    print("\nComposite snapshot SHA-256:", plan["source_sha256"])
    print("Composite source size (bytes):", plan["source_size_bytes"])


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"historical_staging_before_banknifty_promotion_{stamp}.db"
    if backup_path.exists():
        raise FileExistsError(backup_path)

    source = sqlite3.connect(DATABASE, timeout=60)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()

    verify = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = verify.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"Backup verification failed: integrity={integrity}, FK errors={len(fk_errors)}"
            )
    finally:
        verify.close()

    return backup_path


def insert_snapshot_manifest(
    con: sqlite3.Connection,
    snapshot_id: int,
    plan: dict[str, Any],
) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS historical_snapshot_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_import_batch_id INTEGER NOT NULL,
            source_kind TEXT NOT NULL,
            source_import_batch_id INTEGER,
            external_source_batch_id INTEGER,
            instrument_code TEXT,
            date_from TEXT,
            date_to TEXT,
            source_filename TEXT,
            source_sha256 TEXT NOT NULL,
            selection_rule TEXT NOT NULL,
            notes TEXT,
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (snapshot_import_batch_id) REFERENCES import_batches(id),
            FOREIGN KEY (source_import_batch_id) REFERENCES import_batches(id),
            FOREIGN KEY (external_source_batch_id) REFERENCES external_index_source_batches(id)
        )
    """)

    now = utc_now()
    legacy = plan["legacy"]
    con.execute("""
        INSERT INTO historical_snapshot_sources (
            snapshot_import_batch_id, source_kind, source_import_batch_id,
            external_source_batch_id, instrument_code, date_from, date_to,
            source_filename, source_sha256, selection_rule, notes, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        snapshot_id,
        "legacy_import_batch",
        LEGACY_BATCH_ID,
        None,
        None,
        None,
        None,
        Path(legacy["source_path"]).name,
        legacy["source_sha256"],
        "Copy all legacy raw, quality and curated daily rows except BANKNIFTY "
        "records dated 2015-01-01 through 2016-12-31.",
        "Original legacy source retained unchanged in import batch 1.",
        now,
    ))

    for batch in plan["external_batches"]:
        year = int(batch["calendar_year"])
        con.execute("""
            INSERT INTO historical_snapshot_sources (
                snapshot_import_batch_id, source_kind, source_import_batch_id,
                external_source_batch_id, instrument_code, date_from, date_to,
                source_filename, source_sha256, selection_rule, notes, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            "nse_indices_csv",
            None,
            int(batch["id"]),
            INSTRUMENT,
            f"{year}-01-01",
            f"{year}-12-31",
            batch["source_filename"],
            batch["source_sha256"],
            "Use all validated NIFTY BANK daily OHLC rows for the calendar year; "
            "replace the corresponding BANKNIFTY legacy daily records in this snapshot only.",
            "NSE Indices historical-data report; original CSV preserved in external staging.",
            now,
        ))


def apply_promotion(plan: dict[str, Any]) -> int:
    backup_path = create_backup()
    print("\nVerified database backup:", backup_path)

    con = sqlite3.connect(DATABASE, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 60000")

    try:
        con.execute("BEGIN IMMEDIATE")

        # Re-check that the source state has not changed since dry-run.
        current_completed = con.execute(
            "SELECT id FROM import_batches WHERE status='completed' ORDER BY id"
        ).fetchall()
        if [r["id"] for r in current_completed] != [LEGACY_BATCH_ID]:
            raise RuntimeError("Completed import batches changed since preflight.")

        source_path = (
            "composite_snapshot://legacy_batch_1+NSE_external_batches_1_2"
            "?policy=replace_BANKNIFTY_2015_2016"
        )
        cursor = con.execute("""
            INSERT INTO import_batches (
                source_path, source_sha256, source_size_bytes,
                status, imported_rows, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            source_path,
            plan["source_sha256"],
            plan["source_size_bytes"],
            "building",
            0,
            utc_now(),
        ))
        snapshot_id = int(cursor.lastrowid)

        insert_snapshot_manifest(con, snapshot_id, plan)

        # Copy retained legacy raw records and map old raw IDs to new IDs.
        old_to_new: dict[int, int] = {}
        raw_rows = con.execute("""
            SELECT id, instrument_code, source_table, source_row_number,
                   source_id, source_timestamp, open_raw, high_raw,
                   low_raw, close_raw, volume_raw
            FROM raw_daily_records
            WHERE import_batch_id=?
              AND NOT (
                  instrument_code=?
                  AND date(source_timestamp) BETWEEN ? AND ?
              )
            ORDER BY source_table, source_row_number, id
        """, (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO)).fetchall()

        for row in raw_rows:
            cur = con.execute("""
                INSERT INTO raw_daily_records (
                    import_batch_id, instrument_code, source_table,
                    source_row_number, source_id, source_timestamp,
                    open_raw, high_raw, low_raw, close_raw, volume_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id,
                row["instrument_code"],
                row["source_table"],
                row["source_row_number"],
                row["source_id"],
                row["source_timestamp"],
                row["open_raw"],
                row["high_raw"],
                row["low_raw"],
                row["close_raw"],
                row["volume_raw"],
            ))
            old_to_new[int(row["id"])] = int(cur.lastrowid)

        # Copy the associated quality assessments for retained raw records.
        quality_rows = con.execute("""
            SELECT raw_record_id, instrument_code, source_table,
                   source_timestamp, record_status, close_eligible,
                   full_ohlc_eligible, volume_eligible, issue_codes,
                   assessed_at_utc
            FROM daily_quality_assessments
            WHERE import_batch_id=?
            ORDER BY raw_record_id
        """, (LEGACY_BATCH_ID,)).fetchall()

        copied_quality = 0
        for row in quality_rows:
            new_raw_id = old_to_new.get(int(row["raw_record_id"]))
            if new_raw_id is None:
                continue
            con.execute("""
                INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code,
                    source_table, source_timestamp, record_status,
                    close_eligible, full_ohlc_eligible, volume_eligible,
                    issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_raw_id,
                snapshot_id,
                row["instrument_code"],
                row["source_table"],
                row["source_timestamp"],
                row["record_status"],
                row["close_eligible"],
                row["full_ohlc_eligible"],
                row["volume_eligible"],
                row["issue_codes"],
                row["assessed_at_utc"],
            ))
            copied_quality += 1

        # Copy retained curated closes, remapping their raw-record FK.
        close_rows = con.execute("""
            SELECT instrument_code, candle_date, close, raw_record_id,
                   source_id, source_table, source_quality_status, issue_codes
            FROM daily_close_series
            WHERE import_batch_id=?
              AND NOT (
                  instrument_code=?
                  AND candle_date BETWEEN ? AND ?
              )
            ORDER BY instrument_code, candle_date
        """, (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO)).fetchall()

        for row in close_rows:
            new_raw_id = old_to_new.get(int(row["raw_record_id"]))
            if new_raw_id is None:
                raise RuntimeError(
                    f"Could not map legacy close raw_record_id {row['raw_record_id']}"
                )
            con.execute("""
                INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close,
                    raw_record_id, source_id, source_table,
                    source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, row["instrument_code"], row["candle_date"],
                row["close"], new_raw_id, row["source_id"], row["source_table"],
                row["source_quality_status"], row["issue_codes"],
            ))

        # Copy retained curated OHLC candles, remapping their raw-record FK.
        ohlc_rows = con.execute("""
            SELECT instrument_code, candle_date, open, high, low, close,
                   volume, volume_status, source_volume_raw, raw_record_id,
                   source_id, source_table, quality_status, issue_codes
            FROM daily_ohlcv_analytical
            WHERE import_batch_id=?
              AND NOT (
                  instrument_code=?
                  AND candle_date BETWEEN ? AND ?
              )
            ORDER BY instrument_code, candle_date
        """, (LEGACY_BATCH_ID, INSTRUMENT, REPLACE_FROM, REPLACE_TO)).fetchall()

        for row in ohlc_rows:
            new_raw_id = old_to_new.get(int(row["raw_record_id"]))
            if new_raw_id is None:
                raise RuntimeError(
                    f"Could not map legacy OHLC raw_record_id {row['raw_record_id']}"
                )
            con.execute("""
                INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date,
                    open, high, low, close, volume, volume_status,
                    source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, row["instrument_code"], row["candle_date"],
                row["open"], row["high"], row["low"], row["close"],
                row["volume"], row["volume_status"], row["source_volume_raw"],
                new_raw_id, row["source_id"], row["source_table"],
                row["quality_status"], row["issue_codes"],
            ))

        # Add the two validated NSE CSV batches as raw + quality + curated data.
        external_rows = con.execute("""
            SELECT r.id AS external_record_id, r.batch_id, b.calendar_year,
                   b.source_filename, r.source_row_number, r.instrument_code,
                   r.source_index_name, r.candle_date, r.open_raw, r.high_raw,
                   r.low_raw, r.close_raw, r.open, r.high, r.low, r.close
            FROM external_index_daily_records r
            JOIN external_index_source_batches b ON b.id=r.batch_id
            WHERE r.batch_id IN (?, ?)
            ORDER BY r.candle_date
        """, EXTERNAL_BATCH_IDS).fetchall()

        new_issue_codes = json.dumps(
            ["nse_indices_historical_source", "volume_unavailable"],
            separators=(",", ":"),
        )
        inserted_external = 0
        for row in external_rows:
            year = int(row["calendar_year"])
            source_table = f"{NEW_SOURCE_TABLE_PREFIX}_{year}"
            source_id = f"NSE_EXT:{row['external_record_id']}"
            source_timestamp = f"{row['candle_date']} 00:00:00"

            cur = con.execute("""
                INSERT INTO raw_daily_records (
                    import_batch_id, instrument_code, source_table,
                    source_row_number, source_id, source_timestamp,
                    open_raw, high_raw, low_raw, close_raw, volume_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id,
                INSTRUMENT,
                source_table,
                row["source_row_number"],
                source_id,
                source_timestamp,
                row["open_raw"],
                row["high_raw"],
                row["low_raw"],
                row["close_raw"],
                None,
            ))
            new_raw_id = int(cur.lastrowid)

            con.execute("""
                INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code,
                    source_table, source_timestamp, record_status,
                    close_eligible, full_ohlc_eligible, volume_eligible,
                    issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'accepted', 1, 1, 0, ?, ?)
            """, (
                new_raw_id, snapshot_id, INSTRUMENT, source_table,
                source_timestamp, new_issue_codes, utc_now(),
            ))

            con.execute("""
                INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close,
                    raw_record_id, source_id, source_table,
                    source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', ?)
            """, (
                snapshot_id, INSTRUMENT, row["candle_date"], row["close"],
                new_raw_id, source_id, source_table, new_issue_codes,
            ))

            con.execute("""
                INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date,
                    open, high, low, close, volume, volume_status,
                    source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'unavailable', NULL, ?, ?, ?, 'accepted', ?)
            """, (
                snapshot_id, INSTRUMENT, row["candle_date"],
                row["open"], row["high"], row["low"], row["close"],
                new_raw_id, source_id, source_table, new_issue_codes,
            ))
            inserted_external += 1

        # Verify copied raw/quality counts and all target table counts.
        actual_counts = {}
        for table in (
            "raw_daily_records",
            "daily_quality_assessments",
            "daily_close_series",
            "daily_ohlcv_analytical",
        ):
            actual_counts[table] = con.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE import_batch_id=?",
                (snapshot_id,),
            ).fetchone()["n"]

        if inserted_external != 495:
            raise RuntimeError(f"Inserted {inserted_external} NSE rows, expected 495.")
        for table, expected_count in plan["expected"].items():
            if actual_counts[table] != expected_count:
                raise RuntimeError(
                    f"{table} count mismatch: {actual_counts[table]} != {expected_count}"
                )

        # Verify BANKNIFTY year coverage and complete OHLC after replacement.
        bank_counts = con.execute("""
            SELECT
                (SELECT COUNT(*) FROM daily_close_series
                 WHERE import_batch_id=? AND instrument_code='BANKNIFTY'
                   AND candle_date BETWEEN '2015-01-01' AND '2015-12-31') AS close_2015,
                (SELECT COUNT(*) FROM daily_close_series
                 WHERE import_batch_id=? AND instrument_code='BANKNIFTY'
                   AND candle_date BETWEEN '2016-01-01' AND '2016-12-31') AS close_2016,
                (SELECT COUNT(*) FROM daily_ohlcv_analytical
                 WHERE import_batch_id=? AND instrument_code='BANKNIFTY'
                   AND candle_date BETWEEN '2015-01-01' AND '2015-12-31') AS ohlc_2015,
                (SELECT COUNT(*) FROM daily_ohlcv_analytical
                 WHERE import_batch_id=? AND instrument_code='BANKNIFTY'
                   AND candle_date BETWEEN '2016-01-01' AND '2016-12-31') AS ohlc_2016
        """, (snapshot_id, snapshot_id, snapshot_id, snapshot_id)).fetchone()
        if tuple(bank_counts) != (248, 247, 248, 247):
            raise RuntimeError(
                "BANKNIFTY 2015-2016 counts do not match NSE source: "
                f"{tuple(bank_counts)}"
            )

        # Confirm raw-to-quality relationship and database constraints.
        missing_quality = con.execute("""
            SELECT COUNT(*) AS n
            FROM raw_daily_records r
            LEFT JOIN daily_quality_assessments q ON q.raw_record_id=r.id
            WHERE r.import_batch_id=? AND q.raw_record_id IS NULL
        """, (snapshot_id,)).fetchone()["n"]
        if missing_quality:
            raise RuntimeError(f"New snapshot has {missing_quality} raw rows without quality records.")

        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"Foreign-key check found {len(fk_errors)} errors.")

        # Only now make the new snapshot eligible for the existing aggregation builder.
        con.execute("""
            UPDATE import_batches
            SET status='completed', imported_rows=?, imported_at_utc=?
            WHERE id=?
        """, (actual_counts["raw_daily_records"], utc_now(), snapshot_id))

        con.commit()
        print("\nPROMOTION COMMITTED")
        print("New snapshot import_batch_id:", snapshot_id)
        print("Verified backup:", backup_path)
        print("New batch raw rows:", actual_counts["raw_daily_records"])
        print("New batch quality rows:", actual_counts["daily_quality_assessments"])
        print("New batch daily close rows:", actual_counts["daily_close_series"])
        print("New batch daily OHLC rows:", actual_counts["daily_ohlcv_analytical"])
        print("BANKNIFTY 2015 close/OHLC:", bank_counts[0], bank_counts[2])
        print("BANKNIFTY 2016 close/OHLC:", bank_counts[1], bank_counts[3])
        print("Legacy batch 1: preserved unchanged")
        print("Aggregates: not yet rebuilt")
        print("Next: run scripts\\build_multi_timeframe_history.py")
        return snapshot_id

    except Exception:
        con.rollback()
        print("\nPROMOTION FAILED — transaction rolled back.", file=sys.stderr)
        print("Verified pre-promotion backup retained:", backup_path, file=sys.stderr)
        raise
    finally:
        con.close()


APPLY_MODE = False


def main() -> None:
    global APPLY_MODE
    parser = argparse.ArgumentParser(
        description="Build a new versioned historical snapshot using NSE BANKNIFTY 2015-2016 data."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a verified backup and promote the new composite snapshot. Default is read-only dry run.",
    )
    args = parser.parse_args()
    APPLY_MODE = args.apply

    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    con = connect_readonly(DATABASE)
    try:
        plan = get_preflight(con)
    finally:
        con.close()

    print_plan(plan)

    # Confirm this composite fingerprint has not already been imported.
    check = connect_readonly(DATABASE)
    try:
        already = check.execute(
            "SELECT id, status FROM import_batches WHERE source_sha256=?",
            (plan["source_sha256"],),
        ).fetchone()
    finally:
        check.close()
    if already:
        raise RuntimeError(
            f"This exact composite snapshot already exists as batch {already['id']} "
            f"with status {already['status']}. Refusing duplicate promotion."
        )

    if not args.apply:
        print("\nDRY RUN ONLY — no database changes and no backup created.")
        print("After reviewing the plan, apply with:")
        print("python scripts\\promote_banknifty_nse_snapshot.py --apply")
        return

    apply_promotion(plan)


if __name__ == "__main__":
    main()
