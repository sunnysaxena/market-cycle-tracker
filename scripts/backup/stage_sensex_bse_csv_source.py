from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
INPUT_FILE = ROOT / "backend" / "data" / "incoming" / "sensex_bse_2025_to_latest.csv"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"
SOURCE_PAGE = "https://www.bseindia.com/Indices/IndexArchiveData.html"
SOURCE_PROVIDER = "BSE historical index data report"
SOURCE_CODE = "BSE_INDICES_HISTORICAL_DATA"
INSTRUMENT = "SENSEX"
SOURCE_INDEX_NAME = "SENSEX"
SOURCE_TABLE = "bse_indices_historical_2025_to_latest"
MAPPING_CODE = "BSE:SENSEX:bse_indices_historical_2025_to_latest:1D"
PRICE_FIELDS = ("Open", "High", "Low", "Close")
OVERLAP_TOLERANCE = 0.02

EXPECTED_HEADERS = [
    "Date", "Open", "High", "Low", "Close", "Points Change",
    "Change(%)", "Volume(Cr.)", "Turnover (Rs.Cr.)", "P/E", "P/B",
    "Div Yield",
]


@dataclass(frozen=True)
class SourceRow:
    row_number: int
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
    year: int


class ValidationError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_price(value: str, field: str, row_number: int) -> float:
    try:
        result = float((value or "").replace(",", "").strip())
    except (AttributeError, ValueError) as exc:
        raise ValidationError(
            f"CSV row {row_number}: invalid {field} value {value!r}"
        ) from exc
    if not math.isfinite(result) or result <= 0:
        raise ValidationError(
            f"CSV row {row_number}: {field} must be finite and positive"
        )
    return result


def parse_source_file(path: Path) -> tuple[list[SourceRow], str, int, list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f"BSE SENSEX CSV not found: {path}")

    source_hash = sha256_file(path)
    source_size = path.stat().st_size
    parsed: list[SourceRow] = []
    seen_dates: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_HEADERS:
            raise ValidationError(
                f"Unexpected BSE CSV headers: {reader.fieldnames!r}; "
                f"expected {EXPECTED_HEADERS!r}"
            )
        for row_number, record in enumerate(reader, start=2):
            raw_date = (record.get("Date") or "").strip()
            try:
                parsed_date = datetime.strptime(raw_date, "%d-%B-%Y").date()
            except ValueError as exc:
                raise ValidationError(
                    f"CSV row {row_number}: unsupported date {raw_date!r}; "
                    "expected e.g. 1-January-2025"
                ) from exc

            if not (date(2025, 1, 1) <= parsed_date <= date(2026, 10, 30)):
                raise ValidationError(
                    f"CSV row {row_number}: date {parsed_date} outside expected "
                    "range 2025-01-01 through 2026-10-30"
                )

            candle_date = parsed_date.isoformat()
            if candle_date in seen_dates:
                raise ValidationError(f"Duplicate SENSEX date: {candle_date}")
            seen_dates.add(candle_date)

            values = {
                field: parse_price(record.get(field, ""), field, row_number)
                for field in PRICE_FIELDS
            }
            if values["High"] < max(values["Open"], values["Close"], values["Low"]):
                raise ValidationError(
                    f"{candle_date}: High is below another OHLC value"
                )
            if values["Low"] > min(values["Open"], values["Close"], values["High"]):
                raise ValidationError(
                    f"{candle_date}: Low is above another OHLC value"
                )

            parsed.append(SourceRow(
                row_number=row_number,
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
                year=parsed_date.year,
            ))

    if not parsed:
        raise ValidationError("BSE CSV contains no data rows")
    if min(r.candle_date for r in parsed) != "2025-01-01":
        raise ValidationError("Unexpected first SENSEX source date")
    if max(r.candle_date for r in parsed) != "2026-10-30":
        raise ValidationError("Unexpected last SENSEX source date")
    return parsed, source_hash, source_size, reader.fieldnames or []


def serialize_year_slice(year_rows: list[SourceRow]) -> bytes:
    """Create deterministic bytes for the per-year source slice hash."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Date", "Open", "High", "Low", "Close"])
    # Source BSE CSV has additional descriptive/valuation columns. They are
    # retained in the original downloaded file; this canonical slice hash
    # covers the exact raw OHLC/date payload stored in the staging table.
    for row in sorted(year_rows, key=lambda item: item.candle_date):
        writer.writerow([
            row.raw_date, row.open_raw, row.high_raw,
            row.low_raw, row.close_raw,
        ])
    return output.getvalue().encode("utf-8")


def ensure_schema(connection: sqlite3.Connection) -> None:
    required = {
        "external_index_source_batches",
        "external_index_daily_records",
        "historical_data_sources",
        "historical_instrument_source_mappings",
        "historical_source_batch_links",
        "exchange_calendar_events",
        "exchange_calendar_years",
        "daily_close_series",
        "daily_ohlcv_analytical",
    }
    present = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(required - present)
    if missing:
        raise ValidationError(
            "Required tables are missing; this script will not create or alter "
            f"the schema: {', '.join(missing)}"
        )

    batch_cols = {
        row[1]: row for row in connection.execute(
            'PRAGMA table_info("external_index_source_batches")'
        )
    }
    daily_cols = {
        row[1] for row in connection.execute(
            'PRAGMA table_info("external_index_daily_records")'
        )
    }
    required_batch_cols = {
        "source_provider", "source_url", "instrument_code", "source_index_name",
        "source_filename", "source_sha256", "source_size_bytes", "calendar_year",
        "expected_session_count", "source_row_count", "unique_date_count",
        "calendar_missing_dates_json", "calendar_unexpected_dates_json",
        "import_status", "notes", "imported_at_utc",
    }
    required_daily_cols = {
        "batch_id", "source_row_number", "instrument_code", "source_index_name",
        "candle_date", "raw_date", "open_raw", "high_raw", "low_raw", "close_raw",
        "open", "high", "low", "close", "legacy_open", "legacy_high", "legacy_low",
        "legacy_close", "open_difference", "high_difference", "low_difference",
        "close_difference", "overlap_status", "quality_status", "issue_codes",
    }
    if not required_batch_cols.issubset(batch_cols):
        raise ValidationError("External source batch schema differs from expected schema")
    if not required_daily_cols.issubset(daily_cols):
        raise ValidationError("External daily record schema differs from expected schema")
    if batch_cols["expected_session_count"][3] == 1:
        # The existing schema requires an integer. Use 0 as an explicit unknown
        # sentinel; notes make clear that no complete annual calendar is loaded.
        print("Calendar note: expected_session_count=0 will mean 'not asserted'.")


def check_calendar(connection: sqlite3.Connection, rows: list[SourceRow]) -> tuple[list[str], list[str]]:
    unknown_weekends: list[str] = []
    holiday_conflicts: list[str] = []
    date_years = sorted({r.year for r in rows})
    for year in date_years:
        year_row = connection.execute("""
            SELECT coverage_status
            FROM exchange_calendar_years
            WHERE exchange='BSE' AND market_segment='EQUITY' AND calendar_year=?
        """, (year,)).fetchone()
        if not year_row:
            raise ValidationError(
                f"BSE calendar parent row missing for {year}; register its "
                "event-exception coverage before staging"
            )

    for row in rows:
        parsed = date.fromisoformat(row.candle_date)
        event = connection.execute("""
            SELECT event_type, event_name
            FROM exchange_calendar_events
            WHERE exchange='BSE' AND market_segment='EQUITY' AND session_date=?
        """, (row.candle_date,)).fetchone()
        if event and event[0] == "holiday_closed":
            holiday_conflicts.append(row.candle_date)
        if parsed.weekday() >= 5 and not (event and event[0] == "special_session_open"):
            unknown_weekends.append(row.candle_date)

    if holiday_conflicts:
        raise ValidationError(
            "CSV contains dates registered as BSE holidays: " + ", ".join(holiday_conflicts)
        )
    if unknown_weekends:
        raise ValidationError(
            "CSV contains weekend rows without registered BSE special-session events: "
            + ", ".join(unknown_weekends)
        )
    return unknown_weekends, holiday_conflicts


def existing_rows(connection: sqlite3.Connection, dates: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for start in range(0, len(dates), 400):
        subset = dates[start:start + 400]
        placeholders = ",".join("?" for _ in subset)
        query = f"""
            SELECT c.candle_date, o.open, o.high, o.low, o.close, c.close
            FROM daily_close_series AS c
            LEFT JOIN daily_ohlcv_analytical AS o
              ON o.import_batch_id = c.import_batch_id
             AND o.instrument_code = c.instrument_code
             AND o.candle_date = c.candle_date
            WHERE c.import_batch_id = 2
              AND c.instrument_code = 'SENSEX'
              AND c.candle_date IN ({placeholders})
        """
        for row in connection.execute(query, subset):
            result[row[0]] = {
                "open": row[1], "high": row[2], "low": row[3],
                "ohlc_close": row[4], "close": row[5],
            }
    return result


def year_slice_hash(rows: list[SourceRow]) -> tuple[str, int]:
    payload = serialize_year_slice(rows)
    return sha256_bytes(payload), len(payload)


def validate_registry_source(connection: sqlite3.Connection, original_hash: str,
                             original_size: int, row_count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "original_filename": INPUT_FILE.name,
        "original_file_sha256": original_hash,
        "original_file_size_bytes": original_size,
        "original_row_count": row_count,
        "source_headers": EXPECTED_HEADERS,
        "date_range": {"from": "2025-01-01", "to": "2026-10-30"},
        "volume_note": (
            "Volume(Cr.) is a BSE-reported source metric; it is not treated as "
            "traded volume of the SENSEX index and is not copied into OHLCV volume."
        ),
        "year_slice_hash_policy": (
            "External batch source_sha256 is the deterministic SHA-256 of the "
            "canonical date/OHLC year slice. The complete downloaded CSV SHA-256 "
            "is recorded here."
        ),
    }
    source = connection.execute("""
        SELECT provider_name, source_type, authority_level, source_url, data_format
        FROM historical_data_sources WHERE source_code=?
    """, (SOURCE_CODE,)).fetchone()
    expected_source = (
        SOURCE_PROVIDER, "official_exchange_portal", "official_primary_source_download",
        SOURCE_PAGE, "CSV",
    )
    if source is None:
        connection.execute("""
            INSERT INTO historical_data_sources (
                source_code, provider_name, source_type, authority_level,
                source_url, data_format, timezone, description, metadata_json,
                is_active, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            SOURCE_CODE, SOURCE_PROVIDER, "official_exchange_portal",
            "official_primary_source_download", SOURCE_PAGE, "CSV", "Asia/Kolkata",
            "BSE historical SENSEX index OHLC CSV downloaded from the BSE Index Archive. "
            "The source CSV contains additional metrics; Volume(Cr.) is not treated as "
            "index traded volume.",
            json.dumps(metadata, sort_keys=True), now, now,
        ))
    else:
        if tuple(source) != expected_source:
            raise ValidationError(
                f"Existing source_code {SOURCE_CODE} has conflicting registry details"
            )
        connection.execute("""
            UPDATE historical_data_sources
            SET metadata_json=?, updated_at_utc=?
            WHERE source_code=?
        """, (json.dumps(metadata, sort_keys=True), now, SOURCE_CODE))

    mapping = connection.execute("""
        SELECT source_code, instrument_code, source_symbol, source_table,
               timeframe, mapping_role, valid_from, valid_to, mapping_status
        FROM historical_instrument_source_mappings
        WHERE mapping_code=?
    """, (MAPPING_CODE,)).fetchone()
    expected_mapping = (
        SOURCE_CODE, INSTRUMENT, "SENSEX", SOURCE_TABLE, "1D",
        "pending_review", "2025-01-01", "2026-10-30", "pending_review",
    )
    if mapping is None:
        connection.execute("""
            INSERT INTO historical_instrument_source_mappings (
                mapping_code, source_code, instrument_code, source_symbol,
                source_table, timeframe, mapping_role, valid_from, valid_to,
                priority, mapping_status, notes, metadata_json,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 10, 'pending_review', ?, ?, ?, ?)
        """, (
            MAPPING_CODE, SOURCE_CODE, INSTRUMENT, "SENSEX", SOURCE_TABLE, "1D",
            "pending_review", "2025-01-01", "2026-10-30",
            "BSE CSV passed structural and OHLC validation with 44 exact overlap matches. "
            "Staged only; promotion and preferred-source status remain pending.",
            json.dumps({"original_filename": INPUT_FILE.name,
                        "original_file_sha256": original_hash,
                        "staged_calendar_years": [2025, 2026]}, sort_keys=True),
            now, now,
        ))
    else:
        if tuple(mapping) != expected_mapping:
            raise ValidationError(
                f"Existing mapping_code {MAPPING_CODE} has conflicting registry details"
            )


def prepare_plan(connection: sqlite3.Connection, rows: list[SourceRow],
                 original_hash: str, original_size: int) -> list[dict[str, Any]]:
    check_calendar(connection, rows)
    old = existing_rows(connection, [r.candle_date for r in rows])
    overlap_diffs: list[float] = []
    overlap_dates: list[str] = []
    for row in rows:
        prev = old.get(row.candle_date)
        if prev:
            overlap_dates.append(row.candle_date)
            if prev["open"] is not None:
                diffs = [
                    row.open - prev["open"],
                    row.high - prev["high"],
                    row.low - prev["low"],
                    row.close - prev["ohlc_close"],
                ]
                if any(abs(value) > OVERLAP_TOLERANCE for value in diffs):
                    raise ValidationError(
                        f"Overlap mismatch on {row.candle_date}: OHLC delta={diffs}"
                    )
                overlap_diffs.extend(diffs)
            elif abs(row.close - prev["close"]) > OVERLAP_TOLERANCE:
                raise ValidationError(
                    f"Close-only overlap mismatch on {row.candle_date}: "
                    f"{row.close - prev['close']:+.4f}"
                )

    if len(overlap_dates) != 44:
        raise ValidationError(
            f"Expected 44 overlapping SENSEX dates based on prior validation; "
            f"found {len(overlap_dates)}"
        )
    missing_legacy = [r.candle_date for r in rows if r.candle_date not in old]
    if len(missing_legacy) != 410:
        raise ValidationError(
            f"Expected 410 new SENSEX dates based on prior validation; found {len(missing_legacy)}"
        )

    plan: list[dict[str, Any]] = []
    for year in sorted({r.year for r in rows}):
        year_rows = [r for r in rows if r.year == year]
        digest, serialized_size = year_slice_hash(year_rows)
        plan.append({
            "year": year,
            "rows": year_rows,
            "slice_hash": digest,
            "slice_size": serialized_size,
            "overlap_count": sum(1 for r in year_rows if r.candle_date in old),
            "new_count": sum(1 for r in year_rows if r.candle_date not in old),
            "weekend_count": sum(1 for r in year_rows if date.fromisoformat(r.candle_date).weekday() >= 5),
        })
    return plan


def backup_database(connection: sqlite3.Connection) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"historical_staging_before_sensex_bse_staging_{stamp}.db"
    backup = sqlite3.connect(backup_path)
    try:
        connection.backup(backup)
        backup.commit()
    finally:
        backup.close()

    check = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise ValidationError("Backup verification failed")
    finally:
        check.close()
    return backup_path


def apply_staging(connection: sqlite3.Connection, plan: list[dict[str, Any]],
                  original_hash: str, original_size: int, total_rows: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    validate_registry_source(connection, original_hash, original_size, total_rows)
    legacy = existing_rows(connection, [r.candle_date for p in plan for r in p["rows"]])

    batch_ids: list[int] = []
    for item in plan:
        year = item["year"]
        digest = item["slice_hash"]
        existing_batch = connection.execute("""
            SELECT id, source_row_count, instrument_code, calendar_year
            FROM external_index_source_batches
            WHERE source_sha256=?
        """, (digest,)).fetchone()
        if existing_batch:
            batch_id, count, instrument, stored_year = existing_batch
            stored_rows = connection.execute("""
                SELECT COUNT(*) FROM external_index_daily_records WHERE batch_id=?
            """, (batch_id,)).fetchone()[0]
            if (count, instrument, stored_year, stored_rows) != (
                len(item["rows"]), INSTRUMENT, year, len(item["rows"])
            ):
                raise ValidationError(
                    f"Existing BSE source slice hash for {year} has conflicting batch details"
                )
            batch_ids.append(batch_id)
            item["batch_id"] = batch_id
            item["already_staged"] = True
            continue

        # No complete BSE annual session calendar is registered for these years.
        # The legacy schema makes expected_session_count NOT NULL; 0 is the
        # documented 'not asserted' sentinel, never a claim of zero sessions.
        notes = (
            f"Derived calendar-year OHLC slice from original downloaded file "
            f"{INPUT_FILE.name}; original full-file SHA-256={original_hash}. "
            "expected_session_count=0 means no complete annual BSE calendar is "
            "loaded and no expected-session total is asserted. Weekend records "
            "were checked against registered BSE special-session events. "
            "Volume(Cr.) is not treated as index traded volume; original CSV is preserved."
        )
        cursor = connection.execute("""
            INSERT INTO external_index_source_batches (
                source_provider, source_url, instrument_code, source_index_name,
                source_filename, source_sha256, source_size_bytes, calendar_year,
                expected_session_count, source_row_count, unique_date_count,
                calendar_missing_dates_json, calendar_unexpected_dates_json,
                import_status, notes, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'null', 'null', ?, ?, ?)
        """, (
            SOURCE_PROVIDER, SOURCE_PAGE, INSTRUMENT, SOURCE_INDEX_NAME,
            f"{INPUT_FILE.name}#calendar_year={year}", digest, item["slice_size"],
            year, len(item["rows"]), len(item["rows"]),
            "staged_validated_calendar_incomplete", notes, now,
        ))
        batch_id = cursor.lastrowid
        item["batch_id"] = batch_id
        item["already_staged"] = False

        for row in item["rows"]:
            previous = legacy.get(row.candle_date)
            issue_codes: list[str] = []
            if previous is None:
                overlap_status = "no_legacy_daily_record"
            elif previous["open"] is None:
                overlap_status = "close_match_within_0_02"
                issue_codes.append("legacy_full_ohlc_unavailable")
            else:
                overlap_status = "close_match_within_0_02"
            connection.execute("""
                INSERT INTO external_index_daily_records (
                    batch_id, source_row_number, instrument_code, source_index_name,
                    candle_date, raw_date, open_raw, high_raw, low_raw, close_raw,
                    open, high, low, close, legacy_open, legacy_high, legacy_low,
                    legacy_close, open_difference, high_difference, low_difference,
                    close_difference, overlap_status, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch_id, row.row_number, INSTRUMENT, SOURCE_INDEX_NAME,
                row.candle_date, row.raw_date, row.open_raw, row.high_raw,
                row.low_raw, row.close_raw, row.open, row.high, row.low, row.close,
                previous["open"] if previous else None,
                previous["high"] if previous else None,
                previous["low"] if previous else None,
                previous["ohlc_close"] if previous and previous["ohlc_close"] is not None else (
                    previous["close"] if previous else None
                ),
                row.open - previous["open"] if previous and previous["open"] is not None else None,
                row.high - previous["high"] if previous and previous["high"] is not None else None,
                row.low - previous["low"] if previous and previous["low"] is not None else None,
                row.close - (previous["ohlc_close"] if previous["ohlc_close"] is not None else previous["close"]) if previous else None,
                overlap_status, "valid_ohlc" if not issue_codes else "valid_ohlc_with_source_note",
                json.dumps(issue_codes),
            ))

        link_code = f"BSE:EXTERNAL:{batch_id}:STAGED"
        existing_link = connection.execute("""
            SELECT source_code, external_source_batch_id, link_role
            FROM historical_source_batch_links WHERE link_code=?
        """, (link_code,)).fetchone()
        expected_link = (SOURCE_CODE, batch_id, "staged_external_file")
        if existing_link is None:
            connection.execute("""
                INSERT INTO historical_source_batch_links (
                    link_code, source_code, import_batch_id,
                    external_source_batch_id, link_role, notes, created_at_utc
                ) VALUES (?, ?, NULL, ?, 'staged_external_file', ?, ?)
            """, (
                link_code, SOURCE_CODE, batch_id,
                f"BSE SENSEX year-slice staged from {INPUT_FILE.name}; "
                f"original CSV SHA-256={original_hash}.", now,
            ))
        elif tuple(existing_link) != expected_link:
            raise ValidationError(f"Conflicting source batch link: {link_code}")
        batch_ids.append(batch_id)

    # Ensure links exist for previously staged, matching batches too.
    for item in plan:
        batch_id = item["batch_id"]
        link_code = f"BSE:EXTERNAL:{batch_id}:STAGED"
        link = connection.execute("""
            SELECT source_code, external_source_batch_id, link_role
            FROM historical_source_batch_links WHERE link_code=?
        """, (link_code,)).fetchone()
        if link is None:
            connection.execute("""
                INSERT INTO historical_source_batch_links (
                    link_code, source_code, import_batch_id,
                    external_source_batch_id, link_role, notes, created_at_utc
                ) VALUES (?, ?, NULL, ?, 'staged_external_file', ?, ?)
            """, (
                link_code, SOURCE_CODE, batch_id,
                f"BSE SENSEX year-slice staged from {INPUT_FILE.name}; original CSV SHA-256={original_hash}.",
                now,
            ))
        elif tuple(link) != (SOURCE_CODE, batch_id, "staged_external_file"):
            raise ValidationError(f"Conflicting source batch link: {link_code}")


def print_plan(rows: list[SourceRow], original_hash: str, original_size: int,
               plan: list[dict[str, Any]], apply: bool) -> None:
    print("\nSENSEX BSE HISTORICAL CSV SOURCE STAGING")
    print("=" * 84)
    print(f"Input: {INPUT_FILE}")
    print(f"Original file SHA-256: {original_hash}")
    print(f"Original file size: {original_size:,} bytes")
    print(f"Total source rows: {len(rows)}")
    print("Source format: BSE daily SENSEX OHLC CSV")
    print("Volume(Cr.): source metadata only; not mapped to index traded volume")
    print("Database mode:", "APPLY" if apply else "DRY RUN (read-only)")
    print("\nYEAR-SLICE STAGING PLAN")
    print("-" * 84)
    for item in plan:
        print(
            f"{item['year']} | rows={len(item['rows'])} | "
            f"overlap={item['overlap_count']} | new_dates={item['new_count']} | "
            f"weekend_rows={item['weekend_count']}"
        )
        print(f"  Slice SHA-256: {item['slice_hash']}")
        print(f"  Slice payload size: {item['slice_size']:,} bytes")
        print("  Expected session count: not asserted (BSE annual calendar incomplete)")
        if item.get("already_staged"):
            print(f"  Existing staged batch: {item.get('batch_id')}")
    print("\nSOURCE REGISTRY PLAN")
    print("-" * 84)
    print(f"Source code: {SOURCE_CODE}")
    print(f"Instrument mapping: {MAPPING_CODE}")
    print("Mapping role/status: pending_review / pending_review")
    print("External source batches: 2 (one per calendar year)")
    print("Canonical daily tables: unchanged")
    print("Composite import batches: unchanged")
    print("Weekly/monthly/yearly aggregates: unchanged")
    if not apply:
        print("\nDry run completed. No database or files were modified.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage BSE SENSEX daily OHLC CSV as a separate source version."
    )
    parser.add_argument("--apply", action="store_true", help="Commit staging after validation")
    args = parser.parse_args()

    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")
    rows, original_hash, original_size, _ = parse_source_file(INPUT_FILE)

    # Read-only preflight first: schema, calendar exceptions, overlaps, registry conflicts.
    ro = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    try:
        ensure_schema(ro)
        plan = prepare_plan(ro, rows, original_hash, original_size)
        # Check registry table compatibility without changing it.
        src = ro.execute("SELECT source_code FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)).fetchone()
        if src:
            validate_registry_source_preflight(ro, original_hash, original_size, len(rows))
        existing_mapping = ro.execute("""
            SELECT source_code, instrument_code, source_symbol, source_table,
                   timeframe, mapping_role, valid_from, valid_to, mapping_status
            FROM historical_instrument_source_mappings
            WHERE mapping_code=?
        """, (MAPPING_CODE,)).fetchone()
        expected_mapping = (
            SOURCE_CODE, INSTRUMENT, "SENSEX", SOURCE_TABLE, "1D",
            "pending_review", "2025-01-01", "2026-10-30", "pending_review"
        )
        if existing_mapping and tuple(existing_mapping) != expected_mapping:
            raise ValidationError("Existing BSE SENSEX source mapping conflicts with this staging plan")
        # Check for existing source-year slice hash conflicts before apply.
        for item in plan:
            existing = ro.execute("""
                SELECT id, source_row_count, instrument_code, calendar_year
                FROM external_index_source_batches WHERE source_sha256=?
            """, (item["slice_hash"],)).fetchone()
            if existing:
                cnt = ro.execute("SELECT COUNT(*) FROM external_index_daily_records WHERE batch_id=?", (existing[0],)).fetchone()[0]
                if tuple(existing[1:]) != (len(item["rows"]), INSTRUMENT, item["year"]) or cnt != len(item["rows"]):
                    raise ValidationError(f"Existing year-slice batch {item['year']} conflicts with current CSV")
                item["already_staged"] = True
                item["batch_id"] = existing[0]
    finally:
        ro.close()

    print_plan(rows, original_hash, original_size, plan, args.apply)
    if not args.apply:
        print("\nReview the plan, then rerun with --apply to stage the BSE SENSEX source.")
        return 0

    # Create a verified backup before any changes.
    backup_source = sqlite3.connect(DATABASE, timeout=60)
    try:
        backup_path = backup_database(backup_source)
    finally:
        backup_source.close()
    print(f"\nVerified database backup: {backup_path}")
    print(f"Backup SHA-256: {sha256_file(backup_path)}")

    connection = sqlite3.connect(DATABASE, timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        ensure_schema(connection)
        # Recompute against the transaction's database state.
        plan = prepare_plan(connection, rows, original_hash, original_size)
        apply_staging(connection, plan, original_hash, original_size, len(rows))

        # Verify exactly two source-year batches and all source records.
        staged = connection.execute("""
            SELECT b.id, b.calendar_year, b.source_row_count, b.unique_date_count,
                   b.expected_session_count, b.import_status, COUNT(r.id)
            FROM external_index_source_batches b
            LEFT JOIN external_index_daily_records r ON r.batch_id=b.id
            WHERE b.instrument_code='SENSEX'
              AND b.source_provider=?
              AND b.calendar_year IN (2025, 2026)
            GROUP BY b.id
            ORDER BY b.calendar_year
        """, (SOURCE_PROVIDER,)).fetchall()
        if len(staged) != 2:
            raise ValidationError(f"Expected 2 SENSEX year-slice batches, found {len(staged)}")
        for item in plan:
            match = [r for r in staged if r[1] == item["year"]]
            if len(match) != 1 or match[0][2] != len(item["rows"]) or match[0][3] != len(item["rows"]) or match[0][6] != len(item["rows"]):
                raise ValidationError(f"Staged SENSEX {item['year']} row counts failed verification")

        mapping = connection.execute("""
            SELECT mapping_role, mapping_status, valid_from, valid_to
            FROM historical_instrument_source_mappings
            WHERE mapping_code=?
        """, (MAPPING_CODE,)).fetchone()
        if not mapping or tuple(mapping) != ("pending_review", "pending_review", "2025-01-01", "2026-10-30"):
            raise ValidationError("BSE SENSEX mapping verification failed")

        # Ensure canonical data and existing import batches have not been altered.
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise ValidationError(f"Integrity verification failed: {integrity}; FK={len(fk_errors)}")
        connection.commit()

        print("\nBSE SENSEX SOURCE STAGING COMMITTED")
        print("=" * 84)
        for row in staged:
            print(
                f"{row[1]} | external_batch_id={row[0]} | source={row[2]} | "
                f"unique={row[3]} | staged={row[6]} | "
                f"expected_sessions={row[4]} (not asserted) | status={row[5]}"
            )
        print("Total staged rows:", sum(r[6] for r in staged))
        print("Source registry:", SOURCE_CODE)
        print("Mapping status: pending_review (not promoted)")
        print("SQLite integrity:", integrity)
        print("Foreign-key errors:", len(fk_errors))
        print("Canonical daily/aggregate tables: unchanged")
        print("New composite snapshot: not created")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return 0


def validate_registry_source_preflight(connection: sqlite3.Connection, original_hash: str,
                                       original_size: int, row_count: int) -> None:
    row = connection.execute("""
        SELECT provider_name, source_type, authority_level, source_url, data_format
        FROM historical_data_sources WHERE source_code=?
    """, (SOURCE_CODE,)).fetchone()
    expected = (SOURCE_PROVIDER, "official_exchange_portal", "official_primary_source_download", SOURCE_PAGE, "CSV")
    if tuple(row) != expected:
        raise ValidationError(f"Existing source_code {SOURCE_CODE} conflicts with BSE source")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, sqlite3.Error, OSError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
