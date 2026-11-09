from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
INCOMING = ROOT / "backend" / "data" / "incoming"
SOURCE_PAGE = "https://www.niftyindices.com/reports/historical-data"
SOURCE_PROVIDER = "NSE Indices historical-data report"
INSTRUMENT_CODE = "BANKNIFTY"
SOURCE_INDEX_NAME = "NIFTY BANK"
EXPECTED_FILES = {
    2015: INCOMING / "banknifty_nse_2015.csv",
    2016: INCOMING / "banknifty_nse_2016.csv",
}
PRICE_FIELDS = ("Open", "High", "Low", "Close")


@dataclass(frozen=True)
class SourceRow:
    year: int
    row_number: int
    index_name: str
    raw_date: str
    candle_date: str
    open_raw: str
    high_raw: str
    low_raw: str
    close_raw: str
    open: float
    high: float
    low: float
    close: float


class ValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_price(value: str, field: str, row_number: int) -> float:
    try:
        result = float(value.replace(",", "").strip())
    except (AttributeError, ValueError) as exc:
        raise ValidationError(
            f"Row {row_number}: invalid {field} value {value!r}"
        ) from exc
    if not math.isfinite(result) or result <= 0:
        raise ValidationError(
            f"Row {row_number}: {field} must be a finite positive number"
        )
    return result


def read_year_file(year: int, path: Path) -> tuple[list[SourceRow], str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input file not found: {path}")

    rows: list[SourceRow] = []
    seen_dates: set[str] = set()
    file_hash = sha256_file(path)
    file_size = path.stat().st_size

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_headers = ["Index Name", "Date", "Open", "High", "Low", "Close"]
        if reader.fieldnames != expected_headers:
            raise ValidationError(
                f"{path.name}: unexpected header {reader.fieldnames!r}; "
                f"expected {expected_headers!r}"
            )

        for row_number, record in enumerate(reader, start=2):
            index_name = (record.get("Index Name") or "").strip()
            if index_name != SOURCE_INDEX_NAME:
                raise ValidationError(
                    f"{path.name}, row {row_number}: expected index "
                    f"{SOURCE_INDEX_NAME!r}, found {index_name!r}"
                )

            raw_date = (record.get("Date") or "").strip()
            try:
                parsed_date = datetime.strptime(raw_date, "%d %b %Y").date()
            except ValueError as exc:
                raise ValidationError(
                    f"{path.name}, row {row_number}: unsupported date {raw_date!r}"
                ) from exc

            if parsed_date.year != year:
                raise ValidationError(
                    f"{path.name}, row {row_number}: date {parsed_date} "
                    f"is outside expected year {year}"
                )

            candle_date = parsed_date.isoformat()
            if candle_date in seen_dates:
                raise ValidationError(
                    f"{path.name}: duplicate date {candle_date}"
                )
            seen_dates.add(candle_date)

            values = {
                field: parse_price(record.get(field, ""), field, row_number)
                for field in PRICE_FIELDS
            }
            if values["High"] < max(values["Open"], values["Close"], values["Low"]):
                raise ValidationError(
                    f"{path.name}, {candle_date}: High is below another OHLC value"
                )
            if values["Low"] > min(values["Open"], values["Close"], values["High"]):
                raise ValidationError(
                    f"{path.name}, {candle_date}: Low is above another OHLC value"
                )

            rows.append(SourceRow(
                year=year,
                row_number=row_number,
                index_name=index_name,
                raw_date=raw_date,
                candle_date=candle_date,
                open_raw=(record.get("Open") or "").strip(),
                high_raw=(record.get("High") or "").strip(),
                low_raw=(record.get("Low") or "").strip(),
                close_raw=(record.get("Close") or "").strip(),
                open=values["Open"],
                high=values["High"],
                low=values["Low"],
                close=values["Close"],
            ))

    if not rows:
        raise ValidationError(f"{path.name}: no data rows found")

    return rows, file_hash, file_size


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS external_index_source_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            instrument_code TEXT NOT NULL,
            source_index_name TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL UNIQUE,
            source_size_bytes INTEGER NOT NULL,
            calendar_year INTEGER NOT NULL,
            expected_session_count INTEGER NOT NULL,
            source_row_count INTEGER NOT NULL,
            unique_date_count INTEGER NOT NULL,
            calendar_missing_dates_json TEXT NOT NULL,
            calendar_unexpected_dates_json TEXT NOT NULL,
            import_status TEXT NOT NULL,
            notes TEXT,
            imported_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS external_index_daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            source_row_number INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            source_index_name TEXT NOT NULL,
            candle_date TEXT NOT NULL,
            raw_date TEXT NOT NULL,
            open_raw TEXT NOT NULL,
            high_raw TEXT NOT NULL,
            low_raw TEXT NOT NULL,
            close_raw TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            legacy_open REAL,
            legacy_high REAL,
            legacy_low REAL,
            legacy_close REAL,
            open_difference REAL,
            high_difference REAL,
            low_difference REAL,
            close_difference REAL,
            overlap_status TEXT NOT NULL,
            quality_status TEXT NOT NULL,
            issue_codes TEXT NOT NULL,
            UNIQUE (batch_id, candle_date),
            FOREIGN KEY (batch_id)
                REFERENCES external_index_source_batches(id)
        );

        CREATE INDEX IF NOT EXISTS ix_external_index_daily_instrument_date
            ON external_index_daily_records (instrument_code, candle_date);
    """)


def load_calendar(connection: sqlite3.Connection, year: int) -> tuple[set[str], set[str]]:
    year_row = connection.execute("""
        SELECT verification_level, coverage_status
        FROM exchange_calendar_years
        WHERE exchange = 'NSE'
          AND market_segment = 'EQUITY'
          AND calendar_year = ?
    """, (year,)).fetchone()
    if not year_row:
        raise ValidationError(f"NSE equity calendar metadata missing for {year}")

    holidays = {
        row[0] for row in connection.execute("""
            SELECT session_date
            FROM exchange_calendar_events
            WHERE exchange = 'NSE'
              AND market_segment = 'EQUITY'
              AND calendar_year = ?
              AND event_type = 'holiday_closed'
        """, (year,))
    }
    special_open = {
        row[0] for row in connection.execute("""
            SELECT session_date
            FROM exchange_calendar_events
            WHERE exchange = 'NSE'
              AND market_segment = 'EQUITY'
              AND calendar_year = ?
              AND event_type = 'special_session_open'
        """, (year,))
    }
    if not holidays:
        raise ValidationError(f"No NSE regular holiday events found for {year}")
    return holidays, special_open


def expected_sessions(year: int, holidays: set[str], special_open: set[str]) -> set[str]:
    result: set[str] = set()
    current = date(year, 1, 1)
    end = date(year, 12, 31)
    while current <= end:
        iso = current.isoformat()
        if current.weekday() < 5 and iso not in holidays:
            result.add(iso)
        current = date.fromordinal(current.toordinal() + 1)
    result.update(special_open)
    return result


def legacy_rows(connection: sqlite3.Connection, dates: list[str]) -> dict[str, dict[str, Any]]:
    if not dates:
        return {}
    result: dict[str, dict[str, Any]] = {}
    # The import period is small, but keep query batches below SQLite parameter limits.
    for start in range(0, len(dates), 400):
        subset = dates[start:start + 400]
        placeholders = ",".join("?" for _ in subset)
        query = f"""
            SELECT
                c.candle_date,
                o.open, o.high, o.low, o.close,
                c.close
            FROM daily_close_series AS c
            LEFT JOIN daily_ohlcv_analytical AS o
              ON o.instrument_code = c.instrument_code
             AND o.candle_date = c.candle_date
            WHERE c.instrument_code = 'BANKNIFTY'
              AND c.candle_date IN ({placeholders})
        """
        for row in connection.execute(query, subset):
            result[row[0]] = {
                "open": row[1], "high": row[2], "low": row[3],
                "ohlc_close": row[4], "close": row[5],
            }
    return result


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    loaded: dict[int, tuple[list[SourceRow], str, int]] = {}
    for year, path in EXPECTED_FILES.items():
        loaded[year] = read_year_file(year, path)

    connection = sqlite3.connect(DATABASE)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        create_schema(connection)
        connection.execute("BEGIN IMMEDIATE")

        print("\nBANKNIFTY NSE CSV SOURCE STAGING")
        print("=" * 76)
        print("Source: NSE Indices historical-data report")
        print("Purpose: separate, versioned source staging; no canonical data replacement")

        for year in (2015, 2016):
            rows, file_hash, file_size = loaded[year]
            holidays, special_open = load_calendar(connection, year)
            expected = expected_sessions(year, holidays, special_open)
            actual = {row.candle_date for row in rows}
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)

            if len(actual) != len(rows):
                raise ValidationError(f"{year}: source dates are not unique")

            if missing or unexpected:
                status = "calendar_review_required"
            else:
                status = "staged_validated"

            existing_batch = connection.execute("""
                SELECT id, source_row_count
                FROM external_index_source_batches
                WHERE source_sha256 = ?
            """, (file_hash,)).fetchone()

            if existing_batch:
                batch_id, stored_count = existing_batch
                current_count = connection.execute("""
                    SELECT COUNT(*) FROM external_index_daily_records
                    WHERE batch_id = ?
                """, (batch_id,)).fetchone()[0]
                if stored_count != len(rows) or current_count != len(rows):
                    raise ValidationError(
                        f"{year}: existing SHA-256 batch has an unexpected record count"
                    )
                print(f"\n{year}: already staged; no duplicate insert (batch_id={batch_id})")
                print(f"  SHA-256: {file_hash}")
                continue

            legacy = legacy_rows(connection, [row.candle_date for row in rows])
            timestamp = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute("""
                INSERT INTO external_index_source_batches (
                    source_provider, source_url, instrument_code,
                    source_index_name, source_filename, source_sha256,
                    source_size_bytes, calendar_year, expected_session_count,
                    source_row_count, unique_date_count,
                    calendar_missing_dates_json, calendar_unexpected_dates_json,
                    import_status, notes, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                SOURCE_PROVIDER, SOURCE_PAGE, INSTRUMENT_CODE,
                SOURCE_INDEX_NAME, EXPECTED_FILES[year].name, file_hash,
                file_size, year, len(expected), len(rows), len(actual),
                json.dumps(missing), json.dumps(unexpected), status,
                "CSV source staged separately. Existing raw and curated data were not overwritten. "
                "Overlap differences are retained for review, not auto-corrected.",
                timestamp,
            ))
            batch_id = cursor.lastrowid

            for row in rows:
                old = legacy.get(row.candle_date)
                issue_codes: list[str] = []
                if old is None:
                    overlap_status = "no_legacy_daily_record"
                else:
                    old_close = old["close"]
                    close_delta = row.close - old_close
                    if abs(close_delta) <= 0.02:
                        overlap_status = "close_match_within_0_02"
                    else:
                        overlap_status = "close_difference_detected"
                        issue_codes.append("legacy_source_close_difference_gt_0_02")
                    if old["open"] is None:
                        issue_codes.append("legacy_full_ohlc_unavailable")
                connection.execute("""
                    INSERT INTO external_index_daily_records (
                        batch_id, source_row_number, instrument_code,
                        source_index_name, candle_date, raw_date,
                        open_raw, high_raw, low_raw, close_raw,
                        open, high, low, close,
                        legacy_open, legacy_high, legacy_low, legacy_close,
                        open_difference, high_difference, low_difference,
                        close_difference, overlap_status, quality_status,
                        issue_codes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, row.row_number, INSTRUMENT_CODE,
                    row.index_name, row.candle_date, row.raw_date,
                    row.open_raw, row.high_raw, row.low_raw, row.close_raw,
                    row.open, row.high, row.low, row.close,
                    old["open"] if old else None,
                    old["high"] if old else None,
                    old["low"] if old else None,
                    old["close"] if old else None,
                    (row.open - old["open"]) if old and old["open"] is not None else None,
                    (row.high - old["high"]) if old and old["high"] is not None else None,
                    (row.low - old["low"]) if old and old["low"] is not None else None,
                    (row.close - old["close"]) if old else None,
                    overlap_status,
                    "valid_ohlc" if not issue_codes else "valid_ohlc_with_source_overlap_issue",
                    json.dumps(issue_codes),
                ))

            overlap_count = sum(1 for row in rows if row.candle_date in legacy)
            missing_legacy_count = len(rows) - overlap_count
            full_ohlc_overlap = sum(
                1 for row in rows
                if row.candle_date in legacy and legacy[row.candle_date]["open"] is not None
            )
            diff_count = sum(
                1 for row in rows
                if row.candle_date in legacy
                and abs(row.close - legacy[row.candle_date]["close"]) > 0.02
            )

            print(f"\n{year} | batch_id={batch_id}")
            print(f"  Source rows / unique dates: {len(rows)} / {len(actual)}")
            print(f"  Calendar expected sessions: {len(expected)}")
            print(f"  Calendar missing / unexpected: {len(missing)} / {len(unexpected)}")
            print(f"  Existing close overlap: {overlap_count}")
            print(f"  Existing full-OHLC overlap: {full_ohlc_overlap}")
            print(f"  Dates absent from legacy close series: {missing_legacy_count}")
            print(f"  Overlap closes differing by >0.02: {diff_count}")
            print(f"  Staging status: {status}")
            print(f"  SHA-256: {file_hash}")
            if missing:
                print("  Missing expected dates:", ", ".join(missing))
            if unexpected:
                print("  Unexpected source dates:", ", ".join(unexpected))

        connection.commit()

        print("\nSTAGING SUMMARY")
        print("=" * 76)
        for row in connection.execute("""
            SELECT
                b.calendar_year,
                b.source_filename,
                b.source_row_count,
                b.expected_session_count,
                b.import_status,
                COUNT(r.id)
            FROM external_index_source_batches b
            LEFT JOIN external_index_daily_records r ON r.batch_id = b.id
            WHERE b.instrument_code = 'BANKNIFTY'
              AND b.calendar_year IN (2015, 2016)
            GROUP BY b.id
            ORDER BY b.calendar_year
        """):
            print(
                f"{row[0]} | {row[1]} | rows={row[2]} | "
                f"expected={row[3]} | staged={row[5]} | status={row[4]}"
            )

        print("\nSQLite integrity:", connection.execute("PRAGMA integrity_check").fetchone()[0])
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        print("Foreign-key errors:", len(fk_errors))
        print("\nExisting raw_daily_records: unchanged")
        print("Existing daily_close_series: unchanged")
        print("Existing daily_ohlcv_analytical: unchanged")
        print("No historical candles were replaced or promoted to canonical data.")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
