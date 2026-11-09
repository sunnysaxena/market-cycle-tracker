from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path(r"E:\market-cycle-tracker")
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"

EXCHANGE = "NSE"
SEGMENT = "EQUITY"
SESSION_DATE = "2026-02-01"
YEAR = 2026
SOURCE_TITLE = "NSE Live Trading Session on 01-Feb-2026 - Union Budget"
SOURCE_REFERENCE = "NSE/CMTR/72349; Circular Ref. 11/2026; dated 16-Jan-2026"
SOURCE_URL = "https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf"
VERIFICATION = "official_primary"
EVENT_NAME = "Union Budget 2026 special trading session"
OPEN_TIME = "09:15"
CLOSE_TIME = "15:30"
YEAR_NOTES = (
    "Selected special-session exception only. This row does not assert that the "
    "complete NSE 2026 annual holiday/session calendar has been loaded."
)
EVENT_NOTES = (
    "NSE Capital Market circular confirms live trading on Sunday 01-Feb-2026 "
    "for the Union Budget, with normal market 09:15-15:30 IST. Pre-open was "
    "09:00-09:08 IST. The CSV validation identified a NIFTY 50 OHLC row on "
    "this date; source data remains separately staged/pending promotion."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def inspect_plan(connection: sqlite3.Connection) -> tuple[bool, bool]:
    year_exists = connection.execute(
        """SELECT 1 FROM exchange_calendar_years
           WHERE exchange=? AND market_segment=? AND calendar_year=?""",
        (EXCHANGE, SEGMENT, YEAR),
    ).fetchone() is not None
    event_exists = connection.execute(
        """SELECT 1 FROM exchange_calendar_events
           WHERE exchange=? AND market_segment=? AND session_date=?""",
        (EXCHANGE, SEGMENT, SESSION_DATE),
    ).fetchone() is not None
    return year_exists, event_exists


def create_verified_backup(database: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"historical_staging_before_nse_2026_budget_session_{stamp}.db"

    # SQLite's backup API gives a transactionally consistent copy, even if a WAL exists.
    source = sqlite3.connect(database)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    check = sqlite3.connect(backup)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()

    if integrity != "ok" or fk_errors:
        backup.unlink(missing_ok=True)
        raise RuntimeError(
            f"Backup verification failed: integrity={integrity}, foreign_keys={len(fk_errors)}"
        )
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the official NSE 2026 Union Budget special session."
    )
    parser.add_argument("--apply", action="store_true", help="Commit the calendar event; default is dry-run.")
    args = parser.parse_args()

    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    mode = "APPLY" if args.apply else "DRY RUN (read-only)"
    with connect_readonly(DATABASE) as connection:
        year_exists, event_exists = inspect_plan(connection)

    print("\nNSE 2026 UNION BUDGET SPECIAL SESSION REGISTRATION")
    print("=" * 86)
    print(f"Database: {DATABASE}")
    print(f"Mode: {mode}")
    print(f"Exchange / segment: {EXCHANGE} / {SEGMENT}")
    print(f"Session date: {SESSION_DATE} (Sunday)")
    print(f"Source: {SOURCE_TITLE}")
    print(f"Reference: {SOURCE_REFERENCE}")
    print(f"Source URL: {SOURCE_URL}")
    print(f"Verification: {VERIFICATION}")
    print("Annual calendar coverage: event_exceptions_only (not a complete annual calendar)")
    print("\nPROPOSED CHANGES")
    print("-" * 86)
    print(f"NSE 2026 parent row: {'already exists; preserve' if year_exists else '1 row to insert'}")
    print(f"NSE 2026-02-01 event: {'already exists; update source metadata if needed' if event_exists else '1 event to insert'}")
    print(f"Event type: special_session_open")
    print(f"Normal market hours: {OPEN_TIME}-{CLOSE_TIME} IST")
    print("Pre-open: 09:00-09:08 IST")
    print("Historical price/quality/aggregate tables: unchanged")

    if not args.apply:
        print("\nDry run completed. No database changes were made.")
        print("Review the plan, then rerun with --apply to register the event.")
        return

    backup = create_verified_backup(DATABASE)
    print(f"\nVerified database backup: {backup}")
    print(f"Backup SHA-256: {sha256_file(backup)}")

    connection = sqlite3.connect(DATABASE, timeout=60)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc).isoformat()

        # Insert an exceptions-only parent row if missing; never downgrade an existing annual calendar.
        connection.execute(
            """INSERT OR IGNORE INTO exchange_calendar_years (
                   exchange, market_segment, calendar_year, source_title,
                   source_reference, source_url, verification_level,
                   coverage_status, notes, loaded_at_utc
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                EXCHANGE, SEGMENT, YEAR, SOURCE_TITLE, SOURCE_REFERENCE,
                SOURCE_URL, VERIFICATION, "event_exceptions_only", YEAR_NOTES, now,
            ),
        )

        connection.execute(
            """INSERT INTO exchange_calendar_events (
                   exchange, market_segment, session_date, calendar_year,
                   event_type, event_name, market_open_time, market_close_time,
                   source_title, source_reference, source_url,
                   verification_level, notes, created_at_utc
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(exchange, market_segment, session_date)
               DO UPDATE SET
                   event_type=excluded.event_type,
                   event_name=excluded.event_name,
                   market_open_time=excluded.market_open_time,
                   market_close_time=excluded.market_close_time,
                   source_title=excluded.source_title,
                   source_reference=excluded.source_reference,
                   source_url=excluded.source_url,
                   verification_level=excluded.verification_level,
                   notes=excluded.notes""",
            (
                EXCHANGE, SEGMENT, SESSION_DATE, YEAR,
                "special_session_open", EVENT_NAME, OPEN_TIME, CLOSE_TIME,
                SOURCE_TITLE, SOURCE_REFERENCE, SOURCE_URL,
                VERIFICATION, EVENT_NOTES, now,
            ),
        )

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"Pre-commit database checks failed: integrity={integrity}, foreign_keys={len(fk_errors)}"
            )

        connection.commit()

        result = connection.execute(
            """SELECT session_date, event_type, event_name, market_open_time,
                      market_close_time, verification_level, source_reference
               FROM exchange_calendar_events
               WHERE exchange=? AND market_segment=? AND session_date=?""",
            (EXCHANGE, SEGMENT, SESSION_DATE),
        ).fetchone()
        final_integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        final_fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

        print("\nNSE CALENDAR REGISTRATION COMMITTED")
        print("=" * 86)
        print("Event:", tuple(result) if result else "NOT FOUND")
        print("Annual calendar coverage:", connection.execute(
            """SELECT coverage_status FROM exchange_calendar_years
               WHERE exchange=? AND market_segment=? AND calendar_year=?""",
            (EXCHANGE, SEGMENT, YEAR),
        ).fetchone()[0])
        print("SQLite integrity:", final_integrity)
        print("Foreign-key errors:", len(final_fk_errors))
        print("Historical price/quality/aggregate tables: not modified")
        print("Verified backup:", backup)

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
