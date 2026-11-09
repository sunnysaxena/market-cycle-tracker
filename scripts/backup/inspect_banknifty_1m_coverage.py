import csv
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# This script is saved in <project_root>/scripts when used by the user.
PROJECT_ROOT = Path(r"E:\market-cycle-tracker")
DUMP_PATH = Path(r"E:\databases\Database\mysql\Dump20260308.sql")
DATABASE_PATH = PROJECT_ROOT / "backend" / "data" / "historical_staging.db"
OUTPUT_CSV = PROJECT_ROOT / "backend" / "data" / "banknifty_1m_coverage_2015_2016.csv"

START_DATE = "2015-01-01"
END_DATE = "2016-12-31"
TARGET_TABLE = "niftybank_1m"

INSERT_START_RE = re.compile(
    rf"INSERT\s+INTO\s+`?{re.escape(TARGET_TABLE)}`?",
    re.IGNORECASE,
)
DATETIME_RE = re.compile(r"'(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})'")


def load_daily_dates(connection, instrument_code):
    rows = connection.execute(
        """
        SELECT candle_date
        FROM daily_close_series
        WHERE instrument_code = ?
          AND candle_date >= ?
          AND candle_date <= ?
        """,
        (instrument_code, START_DATE, END_DATE),
    ).fetchall()
    return {str(row[0])[:10] for row in rows}


def scan_mysql_dump():
    if not DUMP_PATH.is_file():
        raise FileNotFoundError(f"MySQL dump not found: {DUMP_PATH}")

    # Per trading date: count source minute rows and retain first/last timestamp.
    daily_stats = defaultdict(lambda: {"rows": 0, "first": None, "last": None})
    total_target_timestamps = 0
    target_insert_statements = 0
    in_target_statement = False

    with DUMP_PATH.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            remainder = line
            while remainder:
                if not in_target_statement:
                    marker = INSERT_START_RE.search(remainder)
                    if marker is None:
                        break
                    target_insert_statements += 1
                    in_target_statement = True
                    remainder = remainder[marker.end():]

                semicolon = remainder.find(";")
                if semicolon >= 0:
                    statement_part = remainder[:semicolon]
                    remainder = remainder[semicolon + 1:]
                    in_target_statement = False
                else:
                    statement_part = remainder
                    remainder = ""

                for match in DATETIME_RE.finditer(statement_part):
                    timestamp_text = match.group("timestamp")
                    date_text = timestamp_text[:10]
                    if START_DATE <= date_text <= END_DATE:
                        total_target_timestamps += 1
                        stats = daily_stats[date_text]
                        stats["rows"] += 1
                        if stats["first"] is None or timestamp_text < stats["first"]:
                            stats["first"] = timestamp_text
                        if stats["last"] is None or timestamp_text > stats["last"]:
                            stats["last"] = timestamp_text

    if target_insert_statements == 0:
        raise RuntimeError(
            f"No INSERT statement for `{TARGET_TABLE}` was found in {DUMP_PATH}. "
            "Check the table name and dump format before proceeding."
        )

    return daily_stats, total_target_timestamps, target_insert_statements


def main():
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE_PATH}")

    connection = sqlite3.connect(f"file:{DATABASE_PATH.as_posix()}?mode=ro", uri=True)
    try:
        banknifty_daily = load_daily_dates(connection, "BANKNIFTY")
        nifty_daily = load_daily_dates(connection, "NIFTY50")
        finnifty_daily = load_daily_dates(connection, "FINNIFTY")

        holidays = {
            str(row[0])[:10]
            for row in connection.execute(
                """
                SELECT session_date
                FROM exchange_calendar_events
                WHERE exchange = 'NSE'
                  AND market_segment = 'EQUITY'
                  AND event_type = 'holiday_closed'
                  AND session_date BETWEEN ? AND ?
                """,
                (START_DATE, END_DATE),
            ).fetchall()
        }
        special_sessions = {
            str(row[0])[:10]
            for row in connection.execute(
                """
                SELECT session_date
                FROM exchange_calendar_events
                WHERE exchange = 'NSE'
                  AND market_segment = 'EQUITY'
                  AND event_type = 'special_session_open'
                  AND session_date BETWEEN ? AND ?
                """,
                (START_DATE, END_DATE),
            ).fetchall()
        }
    finally:
        connection.close()

    print("\nBANKNIFTY 1-MINUTE SOURCE COVERAGE INSPECTION")
    print("=" * 78)
    print(f"Source dump: {DUMP_PATH}")
    print(f"Target table: {TARGET_TABLE}")
    print("Scanning source SQL only; no import or reconstruction will be performed.")

    minute_stats, timestamp_count, insert_count = scan_mysql_dump()
    minute_dates = set(minute_stats)
    intraday_only_dates = minute_dates - banknifty_daily

    # Candidate session dates supported by at least one of the two equity peers.
    peer_supported_candidates = set()
    for date_text in (nifty_daily | finnifty_daily):
        if date_text in banknifty_daily or date_text in holidays:
            continue
        weekday = datetime.strptime(date_text, "%Y-%m-%d").weekday() < 5
        if weekday or date_text in special_sessions:
            peer_supported_candidates.add(date_text)

    recoverable_candidate_dates = peer_supported_candidates & minute_dates

    print(f"\nTarget INSERT statements found: {insert_count:,}")
    print(f"Minute-row timestamps found in 2015–2016: {timestamp_count:,}")
    print(f"Unique dates with 1-minute records: {len(minute_dates):,}")
    print(f"Existing BANKNIFTY daily close dates: {len(banknifty_daily):,}")
    print(f"Dates with 1-minute data but no daily close: {len(intraday_only_dates):,}")
    print(
        "Peer-supported candidate dates also present in 1-minute data: "
        f"{len(recoverable_candidate_dates):,}"
    )

    print("\nMONTHLY COVERAGE")
    print("-" * 78)
    print(
        f"{'MONTH':<10}{'1M ROWS':>12}{'1M DAYS':>12}"
        f"{'DAILY CLOSES':>15}{'1M-ONLY DAYS':>15}"
    )

    for year in (2015, 2016):
        for month in range(1, 13):
            prefix = f"{year}-{month:02d}"
            month_dates = sorted(d for d in minute_dates if d.startswith(prefix))
            row_count = sum(minute_stats[d]["rows"] for d in month_dates)
            daily_count = sum(1 for d in banknifty_daily if d.startswith(prefix))
            only_count = sum(1 for d in intraday_only_dates if d.startswith(prefix))
            print(
                f"{prefix:<10}{row_count:>12,}{len(month_dates):>12,}"
                f"{daily_count:>15,}{only_count:>15,}"
            )

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.writer(target)
        writer.writerow([
            "candle_date",
            "minute_rows_in_source",
            "first_minute_timestamp",
            "last_minute_timestamp",
            "has_daily_close_record",
            "nifty50_daily_present",
            "finnifty_daily_present",
            "india_vix_not_checked_in_this_report",
            "regular_nse_holiday",
            "special_session",
            "peer_supported_candidate",
        ])
        for date_text in sorted(minute_dates):
            stats = minute_stats[date_text]
            writer.writerow([
                date_text,
                stats["rows"],
                stats["first"],
                stats["last"],
                date_text in banknifty_daily,
                date_text in nifty_daily,
                date_text in finnifty_daily,
                "not_checked",
                date_text in holidays,
                date_text in special_sessions,
                date_text in peer_supported_candidates,
            ])

    print(f"\nCSV report: {OUTPUT_CSV}")
    print("Database mode: read-only.")
    print("Source dump: read-only; no SQL statements are executed against MySQL.")
    print("Daily candles created or modified: 0")
    print(
        "Important: minute-row presence is only a reconstruction candidate. "
        "Session completeness and OHLC validity must be checked before any "
        "daily candle is accepted."
    )


if __name__ == "__main__":
    main()
