from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"

EXCHANGE = "BSE"
MARKET_SEGMENT = "EQUITY"
SESSION_DATE = "2026-02-01"
CALENDAR_YEAR = 2026

SOURCE_TITLE = "BSE Indices Notice — Special Trading Session for BSE Indices"
SOURCE_REFERENCE = "BSE Indices Notice 20260116-38 dated 16-Jan-2026"
SOURCE_URL = (
    "https://bseindices.com/AsiaIndexAPI/api/NoticesAsiaDownload/w?"
    "NoticeId=20260116-38"
)
VERIFICATION_LEVEL = "official_primary"
COVERAGE_STATUS = "event_exceptions_only"
EVENT_TYPE = "special_session_open"
EVENT_NAME = "Union Budget 2026 special trading session"
EVENT_NOTES = (
    "BSE Indices Notice 20260116-38 confirms that BSE indices would be "
    "calculated on Sunday 01-Feb-2026, declared a special trading day for "
    "Union Budget 2026, with markets open for regular trading hours. "
    "This is an event-level calendar exception only; it does not establish "
    "complete BSE holiday-calendar coverage for 2026. The corresponding "
    "SENSEX OHLC row was found in the locally validated BSE CSV; that CSV "
    "has not yet been staged or promoted."
)
YEAR_NOTES = (
    "Selected BSE equity special-session exception for 2026 only. "
    "This row does not represent a complete annual holiday or trading-session calendar."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_existing_state(connection: sqlite3.Connection) -> tuple[tuple | None, tuple | None]:
    year_row = connection.execute(
        """
        SELECT exchange, market_segment, calendar_year, source_title,
               source_reference, source_url, verification_level,
               coverage_status, notes
        FROM exchange_calendar_years
        WHERE exchange = ? AND market_segment = ? AND calendar_year = ?
        """,
        (EXCHANGE, MARKET_SEGMENT, CALENDAR_YEAR),
    ).fetchone()

    event_row = connection.execute(
        """
        SELECT exchange, market_segment, session_date, calendar_year,
               event_type, event_name, market_open_time, market_close_time,
               source_title, source_reference, source_url,
               verification_level, notes
        FROM exchange_calendar_events
        WHERE exchange = ? AND market_segment = ? AND session_date = ?
        """,
        (EXCHANGE, MARKET_SEGMENT, SESSION_DATE),
    ).fetchone()
    return year_row, event_row


def validate_existing_rows(year_row: tuple | None, event_row: tuple | None) -> None:
    if year_row is not None:
        # Do not silently downgrade or overwrite a more complete calendar record.
        current_status = year_row[7]
        current_level = year_row[6]
        if current_status not in (COVERAGE_STATUS, "annual_list_loaded", "official_full_calendar"):
            raise RuntimeError(
                "A BSE 2026 calendar-year row already exists with an unexpected "
                f"coverage_status={current_status!r}. Review it manually."
            )
        if current_level not in (VERIFICATION_LEVEL, "official_primary_copy"):
            raise RuntimeError(
                "A BSE 2026 calendar-year row already exists with an unexpected "
                f"verification_level={current_level!r}. Review it manually."
            )

    if event_row is not None:
        if event_row[4] != EVENT_TYPE or event_row[5] != EVENT_NAME:
            raise RuntimeError(
                "A different BSE event is already registered on 2026-02-01. "
                "The script will not overwrite it. Review the existing event manually."
            )


def print_plan(year_row: tuple | None, event_row: tuple | None, apply: bool) -> None:
    print("\nBSE 2026 UNION BUDGET SPECIAL SESSION REGISTRATION")
    print("=" * 82)
    print(f"Database: {DATABASE}")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (read-only)'}")
    print(f"Exchange / segment: {EXCHANGE} / {MARKET_SEGMENT}")
    print(f"Session date: {SESSION_DATE} (Sunday)")
    print(f"Source: {SOURCE_TITLE}")
    print(f"Reference: {SOURCE_REFERENCE}")
    print(f"Source URL: {SOURCE_URL}")
    print(f"Verification: {VERIFICATION_LEVEL}")
    print(f"Calendar-year coverage: {COVERAGE_STATUS}")
    print("\nPROPOSED CHANGES")
    print("-" * 82)
    print(f"BSE 2026 parent row: {'already exists' if year_row else '1 row to insert'}")
    print(f"BSE 2026-02-01 event: {'already exists' if event_row else '1 event to insert'}")
    print("Event type: special_session_open")
    print("Market hours: not populated (notice confirms regular hours, not exact times)")
    print("Annual-calendar claim: none; coverage remains event_exceptions_only")
    print("Historical price/quality/aggregate tables: unchanged")
    print("\nNOTES")
    print("- BSE Indices Notice 20260116-38 confirms BSE indices were to be calculated")
    print("  on 01-Feb-2026 and that the exchange declared it a special trading day.")
    print("- The local SENSEX CSV validation found an OHLC row for this date.")
    print("- The SENSEX CSV has not yet been staged or promoted.")
    print("- Existing unrelated calendar rows will not be modified.")


def _schema_signature(connection: sqlite3.Connection) -> tuple:
    return tuple(connection.execute("""
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
    """).fetchall())


def _table_row_counts(connection: sqlite3.Connection) -> tuple:
    table_names = [
        row[0] for row in connection.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
    ]
    counts = []
    for table_name in table_names:
        quoted_name = table_name.replace('"', '""')
        count = connection.execute(
            f'SELECT COUNT(*) FROM "{quoted_name}"'
        ).fetchone()[0]
        counts.append((table_name, count))
    return tuple(counts)


def create_verified_backup(connection: sqlite3.Connection) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"historical_staging_before_bse_2026_budget_session_{timestamp}.db"

    source_schema = _schema_signature(connection)
    source_counts = _table_row_counts(connection)

    destination = sqlite3.connect(backup_path)
    try:
        connection.backup(destination)
        destination.commit()
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = destination.execute("PRAGMA foreign_key_check").fetchall()
        backup_schema = _schema_signature(destination)
        backup_counts = _table_row_counts(destination)
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"Backup verification failed: integrity={integrity}, fk_errors={len(fk_errors)}"
            )
        if source_schema != backup_schema:
            raise RuntimeError("Backup schema does not match the source database.")
        if source_counts != backup_counts:
            raise RuntimeError("Backup table row counts do not match the source database.")
    finally:
        destination.close()

    return backup_path


def apply_registration(connection: sqlite3.Connection) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    year_row, event_row = get_existing_state(connection)
    validate_existing_rows(year_row, event_row)

    year_inserted = 0
    event_inserted = 0

    if year_row is None:
        connection.execute(
            """
            INSERT INTO exchange_calendar_years (
                exchange, market_segment, calendar_year,
                source_title, source_reference, source_url,
                verification_level, coverage_status, notes, loaded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                EXCHANGE, MARKET_SEGMENT, CALENDAR_YEAR,
                SOURCE_TITLE, SOURCE_REFERENCE, SOURCE_URL,
                VERIFICATION_LEVEL, COVERAGE_STATUS, YEAR_NOTES, now,
            ),
        )
        year_inserted = 1

    if event_row is None:
        connection.execute(
            """
            INSERT INTO exchange_calendar_events (
                exchange, market_segment, session_date, calendar_year,
                event_type, event_name, market_open_time, market_close_time,
                source_title, source_reference, source_url,
                verification_level, notes, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                EXCHANGE, MARKET_SEGMENT, SESSION_DATE, CALENDAR_YEAR,
                EVENT_TYPE, EVENT_NAME, None, None,
                SOURCE_TITLE, SOURCE_REFERENCE, SOURCE_URL,
                VERIFICATION_LEVEL, EVENT_NOTES, now,
            ),
        )
        event_inserted = 1

    return year_inserted, event_inserted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register the BSE 2026-02-01 Union Budget special trading session."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a verified backup and commit the calendar exception.",
    )
    args = parser.parse_args()

    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    connection_uri = f"file:{DATABASE.as_posix()}?mode={'rw' if args.apply else 'ro'}"
    connection = sqlite3.connect(connection_uri, uri=True, timeout=60)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        year_row, event_row = get_existing_state(connection)
        validate_existing_rows(year_row, event_row)
        print_plan(year_row, event_row, args.apply)

        if not args.apply:
            print("\nDry run completed. No database changes were made.")
            print("Review the plan, then rerun with --apply to register the event.")
            return 0

        backup_path = create_verified_backup(connection)
        print(f"\nVerified database backup: {backup_path}")
        print(f"Backup SHA-256: {sha256_file(backup_path)}")

        try:
            connection.execute("BEGIN IMMEDIATE")
            year_inserted, event_inserted = apply_registration(connection)

            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or fk_errors:
                raise RuntimeError(
                    f"Post-update verification failed: integrity={integrity}, "
                    f"foreign_key_errors={len(fk_errors)}"
                )

            # Verify exact inserted/retained rows before commit.
            verified_year, verified_event = get_existing_state(connection)
            if verified_year is None or verified_event is None:
                raise RuntimeError("Calendar row verification failed before commit.")
            validate_existing_rows(verified_year, verified_event)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        print("\nBSE CALENDAR REGISTRATION COMMITTED")
        print("=" * 82)
        print(f"Exchange-year rows inserted: {year_inserted}")
        print(f"Weekend event rows inserted: {event_inserted}")
        print(f"BSE 2026-02-01 event: {EVENT_NAME}")
        print("Coverage status: event_exceptions_only")
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print(f"Verified backup: {backup_path}")
        print("Historical price/quality/aggregate tables: not modified")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
