#!/usr/bin/env python3
"""Stage NSE NIFTY 50 daily OHLC CSV files as separate external source batches.

Default mode is read-only dry run. --apply creates a verified SQLite backup and
stages the files transactionally. It never writes canonical daily candles or
aggregates.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "historical_staging.db"
DEFAULT_INPUT = ROOT / "backend" / "data" / "incoming"
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
SOURCE_PROVIDER = "NSE Indices historical-data report"
SOURCE_URL = "https://www.niftyindices.com/reports/historical-data"
INSTRUMENT = "NIFTY50"
INDEX_NAME = "NIFTY 50"
FILES = {
    2025: ("nifty50_nse_2025.csv", date(2025, 1, 1), date(2025, 12, 31)),
    2026: ("nifty50_nse_2026.csv", date(2026, 1, 1), date(2026, 10, 30)),
}
REQUIRED_COLUMNS = ("Index Name", "Date", "Open", "High", "Low", "Close")


@dataclass
class ParsedRow:
    source_row_number: int
    index_name: str
    raw_date: str
    candle_date: str
    raw: dict[str, str]
    values: dict[str, float]


@dataclass
class YearFile:
    year: int
    path: Path
    filename: str
    sha256: str
    size_bytes: int
    rows: list[ParsedRow]
    weekend_dates: list[str]
    overlap_count: int = 0
    overlap_mismatches: int = 0
    registered_weekend_dates: list[str] | None = None
    external_batch_id: int | None = None
    already_staged: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_date(raw: str) -> date:
    value = raw.strip()
    for fmt in ("%d-%B-%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date format: {raw!r}")


def parse_year_file(year: int, input_dir: Path) -> YearFile:
    filename, start, end = FILES[year]
    path = input_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required CSV not found: {path}")

    rows: list[ParsedRow] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise ValueError(f"{filename}: missing CSV columns: {missing}")
        for source_row_number, raw_row in enumerate(reader, start=2):
            if not raw_row or not any((v or "").strip() for v in raw_row.values()):
                continue
            index_name = (raw_row.get("Index Name") or "").strip()
            if index_name != INDEX_NAME:
                raise ValueError(
                    f"{filename}:{source_row_number}: expected {INDEX_NAME!r}, got {index_name!r}"
                )
            parsed_date = parse_date(raw_row.get("Date") or "")
            if parsed_date.year != year:
                raise ValueError(
                    f"{filename}:{source_row_number}: date {parsed_date} is outside {year}"
                )
            if not (start <= parsed_date <= end):
                raise ValueError(
                    f"{filename}:{source_row_number}: date {parsed_date} outside configured window {start}..{end}"
                )
            iso_date = parsed_date.isoformat()
            if iso_date in seen:
                raise ValueError(f"{filename}: duplicate date {iso_date}")
            seen.add(iso_date)
            raw_values = {key: (raw_row.get(key) or "").strip() for key in ("Open", "High", "Low", "Close")}
            try:
                values = {key.lower(): float(value.replace(",", "")) for key, value in raw_values.items()}
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{filename}:{source_row_number}: non-numeric OHLC value") from exc
            o, h, l, c = values["open"], values["high"], values["low"], values["close"]
            if any(v <= 0 for v in (o, h, l, c)):
                raise ValueError(f"{filename}:{source_row_number}: OHLC contains non-positive value")
            if h < max(o, l, c) or l > min(o, h, c):
                raise ValueError(f"{filename}:{source_row_number}: invalid OHLC relationship")
            rows.append(ParsedRow(
                source_row_number=source_row_number,
                index_name=index_name,
                raw_date=(raw_row.get("Date") or "").strip(),
                candle_date=iso_date,
                raw=raw_values,
                values=values,
            ))

    if not rows:
        raise ValueError(f"{filename}: no data rows found")
    return YearFile(
        year=year,
        path=path,
        filename=filename,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        rows=rows,
        weekend_dates=sorted(r.candle_date for r in rows if date.fromisoformat(r.candle_date).weekday() >= 5),
    )


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def inspect_and_reconcile(con: sqlite3.Connection, files: list[YearFile], snapshot_batch: int) -> None:
    if not table_exists(con, "external_index_source_batches") or not table_exists(con, "external_index_daily_records"):
        raise RuntimeError("External source staging tables are missing. Initialize external source staging first.")
    source = con.execute(
        "SELECT source_code, source_type FROM historical_data_sources WHERE source_code=?",
        (SOURCE_CODE,),
    ).fetchone()
    if source is None:
        raise RuntimeError(f"Historical source {SOURCE_CODE} is not registered.")
    for year_file in files:
        existing = con.execute("""
            SELECT id, source_sha256, source_row_count, import_status
            FROM external_index_source_batches
            WHERE instrument_code=? AND calendar_year=? AND source_filename=?
            ORDER BY id
        """, (INSTRUMENT, year_file.year, year_file.filename)).fetchall()
        if existing:
            exact = [r for r in existing if r[1] == year_file.sha256]
            if len(existing) == 1 and len(exact) == 1:
                year_file.already_staged = True
                year_file.external_batch_id = int(existing[0][0])
                continue
            raise RuntimeError(
                f"A source batch for {year_file.filename} already exists with a different or ambiguous hash. "
                "Do not overwrite it; use a new versioned filename or review the existing batch."
            )

        dates = [row.candle_date for row in year_file.rows]
        placeholders = ",".join("?" for _ in dates)
        existing_ohlc = {
            row[0]: row[1:5]
            for row in con.execute(f"""
                SELECT candle_date, open, high, low, close
                FROM daily_ohlcv_analytical
                WHERE import_batch_id=? AND instrument_code=?
                  AND candle_date IN ({placeholders})
            """, (snapshot_batch, INSTRUMENT, *dates)).fetchall()
        }
        existing_close = {
            row[0]: row[1]
            for row in con.execute(f"""
                SELECT candle_date, close
                FROM daily_close_series
                WHERE import_batch_id=? AND instrument_code=?
                  AND candle_date IN ({placeholders})
            """, (snapshot_batch, INSTRUMENT, *dates)).fetchall()
        }
        year_file.overlap_count = len(existing_ohlc) + len(set(existing_close) - set(existing_ohlc))
        for row in year_file.rows:
            legacy = existing_ohlc.get(row.candle_date)
            if legacy is not None:
                deltas = [row.values[k] - float(v) for k, v in zip(("open", "high", "low", "close"), legacy)]
                if any(abs(delta) > 0.02 for delta in deltas):
                    year_file.overlap_mismatches += 1
            elif row.candle_date in existing_close:
                if abs(row.values["close"] - float(existing_close[row.candle_date])) > 0.02:
                    year_file.overlap_mismatches += 1

        registered = set()
        if year_file.weekend_dates:
            marks = ",".join("?" for _ in year_file.weekend_dates)
            registered = {
                r[0] for r in con.execute(f"""
                    SELECT session_date
                    FROM exchange_calendar_events
                    WHERE exchange='NSE' AND market_segment='EQUITY'
                      AND event_type='special_session_open'
                      AND session_date IN ({marks})
                """, tuple(year_file.weekend_dates)).fetchall()
            }
        year_file.registered_weekend_dates = sorted(registered)
        missing_weekend = sorted(set(year_file.weekend_dates) - registered)
        if missing_weekend:
            raise RuntimeError(
                f"{year_file.filename}: weekend rows lack registered NSE special-session events: {missing_weekend}"
            )

        holiday_dates = set()
        if dates:
            marks = ",".join("?" for _ in dates)
            holiday_dates = {
                r[0] for r in con.execute(f"""
                    SELECT session_date
                    FROM exchange_calendar_events
                    WHERE exchange='NSE' AND market_segment='EQUITY'
                      AND event_type='holiday_closed'
                      AND session_date IN ({marks})
                """, tuple(dates)).fetchall()
            }
        if holiday_dates:
            raise RuntimeError(
                f"{year_file.filename}: source contains records on registered NSE holiday dates: {sorted(holiday_dates)}"
            )


def deterministic_slice_hash(year_file: YearFile) -> tuple[str, int]:
    # Stable UTF-8 CSV payload of the exact data rows, useful for audit identity.
    import io
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(REQUIRED_COLUMNS)
    for row in sorted(year_file.rows, key=lambda item: item.candle_date):
        writer.writerow([
            row.index_name,
            row.raw_date,
            row.raw["Open"], row.raw["High"], row.raw["Low"], row.raw["Close"],
        ])
    payload = buffer.getvalue().encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(payload)


def print_plan(con: sqlite3.Connection, files: list[YearFile], snapshot_batch: int, apply_mode: bool = False) -> None:
    max_id = con.execute("SELECT COALESCE(MAX(id),0) FROM external_index_source_batches").fetchone()[0]
    pending_id = int(max_id) + 1
    print("\nNIFTY 50 NSE HISTORICAL CSV SOURCE STAGING")
    print("=" * 90)
    print(f"Database: {DEFAULT_DB}")
    print(f"Snapshot used for overlap comparison: batch {snapshot_batch}")
    print("Source: NSE Indices historical-data report")
    print(f"Index: {INDEX_NAME} ({INSTRUMENT})")
    print("Mode: APPLY" if apply_mode else "Mode: DRY RUN (read-only)")
    print("OHLC source only; no index volume field is imported.")
    print("\nYEAR-SLICE STAGING PLAN")
    print("-" * 90)
    for item in files:
        slice_hash, slice_size = deterministic_slice_hash(item)
        status = "already_staged_identical" if item.already_staged else "staged_validated_calendar_incomplete"
        print(
            f"{item.year} | external_batch_id={item.external_batch_id or pending_id} "
            f"| rows={len(item.rows)} | overlap={item.overlap_count} "
            f"| new_dates={len(item.rows)-item.overlap_count} | weekend_rows={len(item.weekend_dates)}"
        )
        print(f"  File: {item.filename} | bytes={item.size_bytes} | SHA-256={item.sha256}")
        print(f"  Year-slice SHA-256: {slice_hash} | payload bytes={slice_size}")
        print(f"  Registered NSE weekend dates: {item.registered_weekend_dates or []}")
        print("  Expected session count: not asserted (annual calendar coverage incomplete)")
        print(f"  Overlap OHLC/close mismatches > 0.02: {item.overlap_mismatches}")
        print(f"  Status: {status}")
        if not item.already_staged:
            pending_id += 1
    total_rows = sum(len(f.rows) for f in files)
    total_overlap = sum(f.overlap_count for f in files)
    total_weekend = sum(len(f.weekend_dates) for f in files)
    total_mismatch = sum(f.overlap_mismatches for f in files)
    print("\nCOMBINED SUMMARY")
    print("-" * 90)
    print(f"Source rows: {total_rows}")
    print(f"Existing snapshot overlaps: {total_overlap}")
    print(f"New dates beyond snapshot: {total_rows-total_overlap}")
    print(f"Weekend source rows: {total_weekend}")
    print(f"Overlap mismatch groups: {total_mismatch}")
    print("Source registry: NSE_INDICES_HISTORICAL_DATA (existing)")
    print("Instrument mapping: pending_review / pending_review until promotion")
    print("Canonical daily tables and aggregates: unchanged")


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"historical_staging_before_nifty50_staging_{stamp}.db"
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    check = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    if integrity != "ok" or fk_errors:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup verification failed: integrity={integrity}, fk_errors={len(fk_errors)}")
    digest = sha256_file(backup_path)
    print(f"\nVerified database backup: {backup_path}")
    print(f"Backup SHA-256: {digest}")
    return backup_path


def apply_staging(db_path: Path, input_dir: Path, files: list[YearFile], snapshot_batch: int) -> None:
    backup_database(db_path, db_path.parent / "backups")
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")
        source = con.execute(
            "SELECT source_code FROM historical_data_sources WHERE source_code=?",
            (SOURCE_CODE,),
        ).fetchone()
        if source is None:
            raise RuntimeError(f"Source registry row {SOURCE_CODE} disappeared before apply")

        staged_ids: list[tuple[YearFile, int, str, int]] = []
        for item in files:
            existing = con.execute("""
                SELECT id, source_sha256 FROM external_index_source_batches
                WHERE instrument_code=? AND calendar_year=? AND source_filename=?
                ORDER BY id
            """, (INSTRUMENT, item.year, item.filename)).fetchall()
            if existing:
                if len(existing) != 1 or existing[0]["source_sha256"] != item.sha256:
                    raise RuntimeError(f"Conflicting existing external batch for {item.filename}")
                staged_ids.append((item, int(existing[0]["id"]), *deterministic_slice_hash(item)))
                continue

            slice_hash, slice_size = deterministic_slice_hash(item)
            now = datetime.now(timezone.utc).isoformat()
            notes = (
                f"NSE Indices NIFTY 50 daily OHLC CSV. Original file SHA-256={item.sha256}; "
                f"original file size={item.size_bytes}. Calendar-year slice SHA-256={slice_hash}. "
                "expected_session_count=0 means no complete annual NSE calendar is loaded and no expected-session total is asserted. "
                "All weekend source dates were checked against registered NSE special-session events."
            )
            cursor = con.execute("""
                INSERT INTO external_index_source_batches (
                    source_provider, source_url, instrument_code, source_index_name,
                    source_filename, source_sha256, source_size_bytes, calendar_year,
                    expected_session_count, source_row_count, unique_date_count,
                    calendar_missing_dates_json, calendar_unexpected_dates_json,
                    import_status, notes, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                SOURCE_PROVIDER, SOURCE_URL, INSTRUMENT, INDEX_NAME,
                item.filename, item.sha256, item.size_bytes, item.year,
                0, len(item.rows), len({r.candle_date for r in item.rows}),
                "null", "null", "staged_validated_calendar_incomplete", notes, now,
            ))
            external_id = int(cursor.lastrowid)

            date_list = [r.candle_date for r in item.rows]
            marks = ",".join("?" for _ in date_list)
            legacy_ohlc = {
                r[0]: r[1:5]
                for r in con.execute(f"""
                    SELECT candle_date, open, high, low, close
                    FROM daily_ohlcv_analytical
                    WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
                """, (snapshot_batch, INSTRUMENT, *date_list)).fetchall()
            }
            legacy_close = {
                r[0]: r[1]
                for r in con.execute(f"""
                    SELECT candle_date, close
                    FROM daily_close_series
                    WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
                """, (snapshot_batch, INSTRUMENT, *date_list)).fetchall()
            }
            records = []
            for row in item.rows:
                previous = legacy_ohlc.get(row.candle_date)
                previous_close = legacy_close.get(row.candle_date)
                if previous is not None:
                    diffs = [row.values[k] - float(v) for k, v in zip(("open", "high", "low", "close"), previous)]
                    overlap_status = "ohlc_match_within_0_02" if all(abs(x) <= 0.02 for x in diffs) else "ohlc_mismatch_review"
                    legacy_values = tuple(previous)
                    diff_values = tuple(diffs)
                elif previous_close is not None:
                    close_diff = row.values["close"] - float(previous_close)
                    overlap_status = "close_match_within_0_02" if abs(close_diff) <= 0.02 else "close_mismatch_review"
                    legacy_values = (None, None, None, float(previous_close))
                    diff_values = (None, None, None, close_diff)
                else:
                    overlap_status = "no_legacy_daily_record"
                    legacy_values = (None, None, None, None)
                    diff_values = (None, None, None, None)
                issues = []
                if overlap_status.endswith("mismatch_review") or overlap_status == "ohlc_mismatch_review":
                    issues.append("legacy_overlap_price_mismatch")
                records.append((
                    external_id, row.source_row_number, INSTRUMENT, INDEX_NAME,
                    row.candle_date, row.raw_date,
                    row.raw["Open"], row.raw["High"], row.raw["Low"], row.raw["Close"],
                    row.values["open"], row.values["high"], row.values["low"], row.values["close"],
                    *legacy_values, *diff_values, overlap_status, "valid_ohlc", json.dumps(issues),
                ))
            con.executemany("""
                INSERT INTO external_index_daily_records (
                    batch_id, source_row_number, instrument_code, source_index_name,
                    candle_date, raw_date, open_raw, high_raw, low_raw, close_raw,
                    open, high, low, close,
                    legacy_open, legacy_high, legacy_low, legacy_close,
                    open_difference, high_difference, low_difference, close_difference,
                    overlap_status, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)

            link_code = f"NSE:EXTERNAL:{external_id}:STAGED"
            con.execute("""
                INSERT INTO historical_source_batch_links (
                    link_code, source_code, import_batch_id,
                    external_source_batch_id, link_role, notes, created_at_utc
                ) VALUES (?, ?, NULL, ?, 'staged_external_file', ?, ?)
                ON CONFLICT(link_code) DO NOTHING
            """, (
                link_code, SOURCE_CODE, external_id,
                f"Staged NSE Indices NIFTY 50 CSV file: {item.filename}.", now,
            ))
            staged_ids.append((item, external_id, slice_hash, slice_size))

        mapping_code = "NSE:NIFTY50:nse_indices_historical_2025_to_2026:1D"
        mapping = con.execute(
            "SELECT mapping_id FROM historical_instrument_source_mappings WHERE mapping_code=?",
            (mapping_code,),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        mapping_notes = (
            "NSE Indices NIFTY 50 historical CSVs staged for 2025-01-01 through 2026-10-30. "
            "44 overlap candles match snapshot batch 3 exactly; source remains pending review until controlled promotion."
        )
        mapping_metadata = json.dumps({
            "external_source_batch_ids": [entry[1] for entry in staged_ids],
            "source_filenames": [entry[0].filename for entry in staged_ids],
            "date_ranges": {str(entry[0].year): [min(r.candle_date for r in entry[0].rows), max(r.candle_date for r in entry[0].rows)] for entry in staged_ids},
        }, sort_keys=True)
        if mapping is None:
            con.execute("""
                INSERT INTO historical_instrument_source_mappings (
                    mapping_code, source_code, instrument_code, source_symbol,
                    source_table, timeframe, mapping_role, valid_from, valid_to,
                    priority, mapping_status, notes, metadata_json,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, '1D', 'pending_review', ?, ?, 10,
                          'pending_review', ?, ?, ?, ?)
            """, (
                mapping_code, SOURCE_CODE, INSTRUMENT, INDEX_NAME,
                "nse_indices_historical_2025_to_2026", "2025-01-01", "2026-10-30",
                mapping_notes, mapping_metadata, now, now,
            ))
        else:
            con.execute("""
                UPDATE historical_instrument_source_mappings
                SET mapping_status='pending_review', mapping_role='pending_review',
                    notes=?, metadata_json=?, updated_at_utc=?
                WHERE mapping_code=?
            """, (mapping_notes, mapping_metadata, now, mapping_code))

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Pre-commit database checks failed: integrity={integrity}, fk_errors={len(fk_errors)}")
        con.commit()

        print("\nNIFTY 50 NSE SOURCE STAGING COMMITTED")
        print("=" * 90)
        for item, external_id, slice_hash, _ in staged_ids:
            count = con.execute(
                "SELECT COUNT(*) FROM external_index_daily_records WHERE batch_id=?",
                (external_id,),
            ).fetchone()[0]
            print(f"{item.year} | external_batch_id={external_id} | staged_rows={count} | slice_sha256={slice_hash}")
        total = con.execute("""
            SELECT COUNT(*) FROM external_index_daily_records
            WHERE batch_id IN (?, ?)
        """, tuple(entry[1] for entry in staged_ids)).fetchone()[0]
        print(f"Total rows staged for NIFTY50: {total}")
        print(f"Source mapping: {mapping_code} | pending_review / pending_review")
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print("Canonical daily tables and aggregates: unchanged")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit source staging after verified backup")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--snapshot-batch", type=int, default=3)
    args = parser.parse_args()

    if not args.database.is_file():
        raise FileNotFoundError(args.database)
    if not args.input_dir.is_dir():
        raise FileNotFoundError(args.input_dir)

    files = [parse_year_file(year, args.input_dir) for year in (2025, 2026)]
    con = sqlite3.connect(f"file:{args.database.as_posix()}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        inspect_and_reconcile(con, files, args.snapshot_batch)
        print_plan(con, files, args.snapshot_batch, apply_mode=args.apply)
    finally:
        con.close()

    if not args.apply:
        print("\nDry run completed. No database or source files were modified.")
        print("Review the plan, then rerun with --apply to stage the NIFTY 50 source.")
        return 0

    # Re-check source files and the overlap under the write transaction in apply_staging.
    # Refuse promotion to staging if any overlapping price differs materially.
    mismatches = sum(item.overlap_mismatches for item in files)
    if mismatches:
        raise RuntimeError(f"Found {mismatches} overlap mismatch groups; staging apply blocked for review.")
    apply_staging(args.database, args.input_dir, files, args.snapshot_batch)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
