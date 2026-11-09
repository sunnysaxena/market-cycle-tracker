#!/usr/bin/env python3
"""Stage 2025/2026 NSE daily OHLC CSVs for BANKNIFTY, FINNIFTY, MIDCPNIFTY and INDIA_VIX.

Default mode is read-only dry run. --apply creates a verified SQLite backup and
stages source batches transactionally. Canonical daily data and aggregates are
never modified by this script.

The 3 equity index CSVs use the Nifty Indices report format. INDIA_VIX uses the
separate NSE India VIX CSV format. Table-level source mappings are created
per instrument and year so source provenance can be matched exactly later.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "historical_staging.db"
DEFAULT_INPUT = ROOT / "backend" / "data" / "incoming"
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
EQUITY_SOURCE_PROVIDER = "NSE Indices historical-data report"
EQUITY_SOURCE_URL = "https://www.niftyindices.com/reports/historical-data"
VIX_SOURCE_PROVIDER = "NSE India VIX historical data"
VIX_SOURCE_URL = "https://www.nseindia.com/reports-indices-historical-vix"
TIME_WINDOWS = {
    2025: (date(2025, 1, 1), date(2025, 12, 31), 249),
    2026: (date(2026, 1, 1), date(2026, 10, 30), 205),
}
TOLERANCE = 0.02

# instrument: (source CSV index name, filename stem, source table prefix, parser kind)
INSTRUMENTS = {
    "BANKNIFTY": ("NIFTY BANK", "banknifty", "nse_indices_historical", "equity"),
    "FINNIFTY": ("NIFTY FINANCIAL SERVICES", "finnifty", "nse_indices_historical", "equity"),
    "MIDCPNIFTY": ("NIFTY MIDCAP SELECT", "midcpnifty", "nse_indices_historical", "equity"),
    "INDIA_VIX": ("INDIA VIX", "indiavix", "nse_india_vix_historical", "vix"),
}


@dataclass
class ParsedRow:
    row_number: int
    source_index_name: str
    raw_date: str
    candle_date: str
    raw: dict[str, str]
    values: dict[str, float]


@dataclass
class SourceFile:
    instrument: str
    year: int
    filename: str
    path: Path
    index_name: str
    source_table: str
    source_provider: str
    source_url: str
    parser_kind: str
    sha256: str
    size_bytes: int
    rows: list[ParsedRow]
    weekend_dates: list[str]
    overlap_count: int = 0
    overlap_mismatches: int = 0
    registered_weekend_dates: list[str] = field(default_factory=list)
    external_batch_id: Optional[int] = None
    already_staged: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_date(raw: str, parser_kind: str) -> date:
    value = (raw or "").strip()
    formats = ("%d-%b-%Y", "%d-%B-%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d") if parser_kind == "vix" else (
        "%d-%B-%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format {raw!r} for parser={parser_kind}")


def parse_number(raw: str, field_name: str, filename: str, row_number: int) -> float:
    try:
        value = float((raw or "").replace(",", "").strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{filename}:{row_number}: invalid {field_name} value {raw!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{filename}:{row_number}: {field_name} must be finite and positive")
    return value


def parse_source_file(instrument: str, year: int, input_dir: Path) -> SourceFile:
    if instrument not in INSTRUMENTS:
        raise ValueError(f"Unsupported instrument: {instrument}")
    index_name, stem, table_prefix, parser_kind = INSTRUMENTS[instrument]
    start, end, expected_count = TIME_WINDOWS[year]
    filename = f"{stem}_nse_{year}.csv"
    path = input_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required CSV not found: {path}")

    rows: list[ParsedRow] = []
    seen_dates: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        original_headers = reader.fieldnames or []
        normalized_headers = [str(header or "").strip() for header in original_headers]
        required = ["Date", "Open", "High", "Low", "Close"]
        if parser_kind == "equity":
            required = ["Index Name", *required]
        missing = [name for name in required if name not in normalized_headers]
        if missing:
            raise ValueError(f"{filename}: missing required CSV columns {missing}; headers={original_headers!r}")

        for row_number, source_record in enumerate(reader, start=2):
            if not source_record or not any(str(value or "").strip() for value in source_record.values()):
                continue
            record = {
                str(key or "").strip(): (value or "").strip()
                for key, value in source_record.items()
                if key is not None
            }
            actual_index_name = index_name if parser_kind == "vix" else record.get("Index Name", "")
            if actual_index_name != index_name:
                raise ValueError(
                    f"{filename}:{row_number}: expected index {index_name!r}, found {actual_index_name!r}"
                )
            raw_date = record.get("Date", "")
            parsed = parse_date(raw_date, parser_kind)
            if parsed.year != year or not (start <= parsed <= end):
                raise ValueError(
                    f"{filename}:{row_number}: date {parsed} outside configured window {start}..{end}"
                )
            iso_date = parsed.isoformat()
            if iso_date in seen_dates:
                raise ValueError(f"{filename}: duplicate date {iso_date}")
            seen_dates.add(iso_date)
            raw_ohlc = {name: record.get(name, "") for name in ("Open", "High", "Low", "Close")}
            values = {
                key.lower(): parse_number(value, key, filename, row_number)
                for key, value in raw_ohlc.items()
            }
            o, h, l, c = values["open"], values["high"], values["low"], values["close"]
            if h < max(o, l, c) or l > min(o, h, c):
                raise ValueError(f"{filename}:{row_number}: invalid OHLC relationship")
            rows.append(ParsedRow(
                row_number=row_number,
                source_index_name=index_name,
                raw_date=raw_date,
                candle_date=iso_date,
                raw=raw_ohlc,
                values=values,
            ))

    if len(rows) != expected_count:
        raise ValueError(
            f"{filename}: expected {expected_count} validated rows from the prior validation run; found {len(rows)}. "
            "Revalidate the CSV before staging."
        )
    source_table = f"{table_prefix}_{year}"
    provider = VIX_SOURCE_PROVIDER if parser_kind == "vix" else EQUITY_SOURCE_PROVIDER
    source_url = VIX_SOURCE_URL if parser_kind == "vix" else EQUITY_SOURCE_URL
    return SourceFile(
        instrument=instrument,
        year=year,
        filename=filename,
        path=path,
        index_name=index_name,
        source_table=source_table,
        source_provider=provider,
        source_url=source_url,
        parser_kind=parser_kind,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        rows=rows,
        weekend_dates=sorted(
            row.candle_date for row in rows if date.fromisoformat(row.candle_date).weekday() >= 5
        ),
    )


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def mapping_code(item: SourceFile) -> str:
    return f"NSE:{item.instrument}:{item.source_table}:1D"


def inspect_and_reconcile(con: sqlite3.Connection, files: list[SourceFile], snapshot_batch: int) -> None:
    required_tables = (
        "external_index_source_batches", "external_index_daily_records",
        "daily_ohlcv_analytical", "daily_close_series", "exchange_calendar_events",
        "historical_data_sources", "historical_instrument_source_mappings",
        "historical_source_batch_links",
    )
    missing_tables = [name for name in required_tables if not table_exists(con, name)]
    if missing_tables:
        raise RuntimeError(f"Required staging tables are missing: {missing_tables}")
    source = con.execute(
        "SELECT source_code FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()
    if source is None:
        raise RuntimeError(f"Historical source registry row {SOURCE_CODE} is missing")

    for item in files:
        existing_batches = con.execute("""
            SELECT id, source_sha256, source_row_count, import_status
            FROM external_index_source_batches
            WHERE instrument_code=? AND calendar_year=? AND source_filename=?
            ORDER BY id
        """, (item.instrument, item.year, item.filename)).fetchall()
        if existing_batches:
            exact = [row for row in existing_batches if row[1] == item.sha256]
            if len(existing_batches) == 1 and len(exact) == 1:
                item.already_staged = True
                item.external_batch_id = int(existing_batches[0][0])
            else:
                raise RuntimeError(
                    f"Conflicting or ambiguous staged batch for {item.filename}; do not overwrite existing source batch"
                )

        dates = [row.candle_date for row in item.rows]
        marks = ",".join("?" for _ in dates)
        existing_ohlc = {
            row[0]: row[1:5]
            for row in con.execute(f"""
                SELECT candle_date, open, high, low, close
                FROM daily_ohlcv_analytical
                WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
            """, (snapshot_batch, item.instrument, *dates)).fetchall()
        }
        existing_close = {
            row[0]: row[1]
            for row in con.execute(f"""
                SELECT candle_date, close
                FROM daily_close_series
                WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
            """, (snapshot_batch, item.instrument, *dates)).fetchall()
        }
        item.overlap_count = len(existing_ohlc) + len(set(existing_close) - set(existing_ohlc))
        for row in item.rows:
            legacy_ohlc = existing_ohlc.get(row.candle_date)
            if legacy_ohlc is not None:
                deltas = [row.values[key] - float(value) for key, value in zip(("open", "high", "low", "close"), legacy_ohlc)]
                if any(abs(delta) > TOLERANCE for delta in deltas):
                    item.overlap_mismatches += 1
            elif row.candle_date in existing_close:
                if abs(row.values["close"] - float(existing_close[row.candle_date])) > TOLERANCE:
                    item.overlap_mismatches += 1

        registered = set()
        if item.weekend_dates:
            weekend_marks = ",".join("?" for _ in item.weekend_dates)
            registered = {
                row[0] for row in con.execute(f"""
                    SELECT session_date FROM exchange_calendar_events
                    WHERE exchange='NSE' AND market_segment='EQUITY'
                      AND event_type='special_session_open'
                      AND session_date IN ({weekend_marks})
                """, tuple(item.weekend_dates)).fetchall()
            }
        item.registered_weekend_dates = sorted(registered)
        missing_weekend = sorted(set(item.weekend_dates) - registered)
        if missing_weekend:
            raise RuntimeError(
                f"{item.filename}: weekend records lack registered NSE special-session events: {missing_weekend}"
            )

        holiday_marks = ",".join("?" for _ in dates)
        holiday_dates = {
            row[0] for row in con.execute(f"""
                SELECT session_date FROM exchange_calendar_events
                WHERE exchange='NSE' AND market_segment='EQUITY'
                  AND event_type='holiday_closed'
                  AND session_date IN ({holiday_marks})
            """, tuple(dates)).fetchall()
        }
        if holiday_dates:
            raise RuntimeError(f"{item.filename}: source rows occur on registered NSE holidays: {sorted(holiday_dates)}")

        code = mapping_code(item)
        existing_mapping = con.execute("""
            SELECT source_code, instrument_code, source_table, timeframe, mapping_role,
                   valid_from, valid_to, mapping_status
            FROM historical_instrument_source_mappings
            WHERE mapping_code=?
        """, (code,)).fetchone()
        expected_start, expected_end, _ = TIME_WINDOWS[item.year]
        if existing_mapping:
            expected = (
                SOURCE_CODE, item.instrument, item.source_table, "1D", "preferred_for_period",
                expected_start.isoformat(), expected_end.isoformat(), "active"
            )
            actual = tuple(existing_mapping)
            pending_expected = (
                SOURCE_CODE, item.instrument, item.source_table, "1D", "pending_review",
                expected_start.isoformat(), expected_end.isoformat(), "pending_review"
            )
            if actual not in (expected, pending_expected):
                raise RuntimeError(f"Existing mapping {code} conflicts with expected year-specific mapping: {actual}")


def stable_slice_hash(item: SourceFile) -> tuple[str, int]:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Instrument", "Index Name", "Date", "Open", "High", "Low", "Close"])
    for row in sorted(item.rows, key=lambda value: value.candle_date):
        writer.writerow([
            item.instrument, row.source_index_name, row.raw_date,
            row.raw["Open"], row.raw["High"], row.raw["Low"], row.raw["Close"],
        ])
    payload = buffer.getvalue().encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(payload)


def print_plan(con: sqlite3.Connection, files: list[SourceFile], snapshot_batch: int, apply_mode: bool) -> None:
    next_id = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM external_index_source_batches").fetchone()[0])
    print("NSE HISTORICAL CSV SOURCE STAGING — FOUR INSTRUMENTS")
    print("=" * 112)
    print(f"Database: {DEFAULT_DB}")
    print(f"Snapshot used for overlap comparison: batch {snapshot_batch}")
    print("Mode: APPLY" if apply_mode else "Mode: DRY RUN (read-only)")
    print("OHLC source only; no index volume is imported.")
    print("Annual exchange-session completeness is not asserted.")
    print("\nYEAR-SLICE STAGING PLAN")
    print("-" * 112)
    total_rows = total_overlaps = total_new = total_mismatches = total_weekend = 0
    for item in files:
        if item.external_batch_id is None:
            item.external_batch_id = next_id
            next_id += 1
        slice_hash, payload_size = stable_slice_hash(item)
        new_dates = len(item.rows) - item.overlap_count
        total_rows += len(item.rows)
        total_overlaps += item.overlap_count
        total_new += new_dates
        total_mismatches += item.overlap_mismatches
        total_weekend += len(item.weekend_dates)
        state = "already_staged_identical" if item.already_staged else "staged_validated_calendar_incomplete"
        print(
            f"{item.instrument:10} {item.year} | external_batch_id={item.external_batch_id} "
            f"| rows={len(item.rows)} | overlap={item.overlap_count} | new_dates={new_dates} "
            f"| weekend_rows={len(item.weekend_dates)}"
        )
        print(f"  File: {item.filename} | bytes={item.size_bytes} | SHA-256={item.sha256}")
        print(f"  Year-slice SHA-256: {slice_hash} | payload bytes={payload_size}")
        print(f"  Source table provenance: {item.source_table}")
        print(f"  Registered weekend dates: {item.registered_weekend_dates}")
        print(f"  Overlap mismatches > {TOLERANCE:.2f}: {item.overlap_mismatches}")
        print(f"  Status: {state}")
    print("\nCOMBINED SUMMARY")
    print("-" * 112)
    print(f"Files: {len(files)}")
    print(f"Source rows: {total_rows}")
    print(f"Existing snapshot overlaps: {total_overlaps}")
    print(f"New dates beyond snapshot: {total_new}")
    print(f"Weekend source rows: {total_weekend}")
    print(f"Overlap mismatch groups: {total_mismatches}")
    print(f"Expected mapping rows (per instrument/year): {len(files)}; all pending_review until promotion")
    print("Source registry: NSE_INDICES_HISTORICAL_DATA (existing)")
    print("Canonical daily/quality/aggregate tables: unchanged")


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"historical_staging_before_remaining_indices_staging_{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    if integrity != "ok" or fk_errors:
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup verification failed: integrity={integrity}, foreign-key errors={len(fk_errors)}")
    digest = sha256_file(backup_path)
    print(f"\nVerified database backup: {backup_path}")
    print(f"Backup SHA-256: {digest}")
    return backup_path


def apply_staging(db_path: Path, files: list[SourceFile], snapshot_batch: int) -> None:
    backup_database(db_path)
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE")
        # Re-run all DB-side reconciliation within the write transaction.
        inspect_and_reconcile(con, files, snapshot_batch)
        mismatches = sum(item.overlap_mismatches for item in files)
        if mismatches:
            raise RuntimeError(f"{mismatches} overlap mismatch groups found; staging is blocked")

        now = datetime.now(timezone.utc).isoformat()
        staged: list[tuple[SourceFile, int, str, int]] = []
        for item in files:
            existing = con.execute("""
                SELECT id, source_sha256 FROM external_index_source_batches
                WHERE instrument_code=? AND calendar_year=? AND source_filename=?
                ORDER BY id
            """, (item.instrument, item.year, item.filename)).fetchall()
            if existing:
                if len(existing) != 1 or existing[0]["source_sha256"] != item.sha256:
                    raise RuntimeError(f"Conflicting external staging batch for {item.filename}")
                external_id = int(existing[0]["id"])
                slice_hash, slice_size = stable_slice_hash(item)
                staged.append((item, external_id, slice_hash, slice_size))
                continue

            slice_hash, slice_size = stable_slice_hash(item)
            expected_start, expected_end, _ = TIME_WINDOWS[item.year]
            notes = (
                f"Official NSE daily OHLC CSV source for {item.index_name}. Original file SHA-256={item.sha256}; "
                f"file size={item.size_bytes}; year-slice SHA-256={slice_hash}. "
                "expected_session_count=0: complete annual exchange calendar coverage is not asserted. "
                f"Provenance table key for promoted raw rows: {item.source_table}. "
                "No index traded-volume field is present in the source."
            )
            cursor = con.execute("""
                INSERT INTO external_index_source_batches (
                    source_provider, source_url, instrument_code, source_index_name,
                    source_filename, source_sha256, source_size_bytes, calendar_year,
                    expected_session_count, source_row_count, unique_date_count,
                    calendar_missing_dates_json, calendar_unexpected_dates_json,
                    import_status, notes, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'null', 'null', ?, ?, ?)
            """, (
                item.source_provider, item.source_url, item.instrument, item.index_name,
                item.filename, item.sha256, item.size_bytes, item.year,
                len(item.rows), len(item.rows), "staged_validated_calendar_incomplete", notes, now,
            ))
            external_id = int(cursor.lastrowid)

            date_values = [row.candle_date for row in item.rows]
            marks = ",".join("?" for _ in date_values)
            old_ohlc = {
                row[0]: row[1:5]
                for row in con.execute(f"""
                    SELECT candle_date, open, high, low, close
                    FROM daily_ohlcv_analytical
                    WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
                """, (snapshot_batch, item.instrument, *date_values)).fetchall()
            }
            old_close = {
                row[0]: row[1]
                for row in con.execute(f"""
                    SELECT candle_date, close
                    FROM daily_close_series
                    WHERE import_batch_id=? AND instrument_code=? AND candle_date IN ({marks})
                """, (snapshot_batch, item.instrument, *date_values)).fetchall()
            }
            records = []
            for row in item.rows:
                prior = old_ohlc.get(row.candle_date)
                prior_close = old_close.get(row.candle_date)
                if prior is not None:
                    diffs = [row.values[key] - float(value) for key, value in zip(("open", "high", "low", "close"), prior)]
                    overlap_status = "ohlc_match_within_0_02" if all(abs(value) <= TOLERANCE for value in diffs) else "ohlc_mismatch_review"
                    legacy_vals = tuple(prior)
                    diff_vals = tuple(diffs)
                elif prior_close is not None:
                    close_diff = row.values["close"] - float(prior_close)
                    overlap_status = "close_match_within_0_02" if abs(close_diff) <= TOLERANCE else "close_mismatch_review"
                    legacy_vals = (None, None, None, float(prior_close))
                    diff_vals = (None, None, None, close_diff)
                else:
                    overlap_status = "no_legacy_daily_record"
                    legacy_vals = (None, None, None, None)
                    diff_vals = (None, None, None, None)
                issue_codes = [] if "mismatch_review" not in overlap_status else ["legacy_overlap_price_mismatch"]
                records.append((
                    external_id, row.row_number, item.instrument, item.index_name,
                    row.candle_date, row.raw_date,
                    row.raw["Open"], row.raw["High"], row.raw["Low"], row.raw["Close"],
                    row.values["open"], row.values["high"], row.values["low"], row.values["close"],
                    *legacy_vals, *diff_vals, overlap_status, "valid_ohlc", json.dumps(issue_codes),
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
                f"Staged official NSE source file {item.filename} for {item.instrument}.", now,
            ))
            staged.append((item, external_id, slice_hash, slice_size))

        # Create exact table/year mappings while still pending review.
        for item, external_id, slice_hash, _ in staged:
            code = mapping_code(item)
            start, end, _ = TIME_WINDOWS[item.year]
            metadata = json.dumps({
                "external_source_batch_ids": [external_id],
                "source_filenames": [item.filename],
                "date_ranges": {str(item.year): [start.isoformat(), end.isoformat()]},
                "source_sha256": item.sha256,
                "source_table_provenance": item.source_table,
            }, sort_keys=True)
            notes = (
                f"NSE source staged for {item.instrument}, {item.year}; "
                f"{len(item.rows)} validated OHLC rows. Mapping matches source_table={item.source_table}. "
                "Pending controlled promotion; annual calendar coverage is incomplete."
            )
            existing_mapping = con.execute(
                "SELECT mapping_id, mapping_status, mapping_role, source_table FROM historical_instrument_source_mappings WHERE mapping_code=?",
                (code,),
            ).fetchone()
            if existing_mapping is None:
                con.execute("""
                    INSERT INTO historical_instrument_source_mappings (
                        mapping_code, source_code, instrument_code, source_symbol,
                        source_table, timeframe, mapping_role, valid_from, valid_to,
                        priority, mapping_status, notes, metadata_json,
                        created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, '1D', 'pending_review', ?, ?, 10,
                              'pending_review', ?, ?, ?, ?)
                """, (
                    code, SOURCE_CODE, item.instrument, item.index_name, item.source_table,
                    start.isoformat(), end.isoformat(), notes, metadata, now, now,
                ))
            else:
                # A correctly configured active mapping must not be downgraded on a re-run.
                if existing_mapping[1] == "pending_review" and existing_mapping[2] == "pending_review":
                    con.execute("""
                        UPDATE historical_instrument_source_mappings
                        SET notes=?, metadata_json=?, updated_at_utc=? WHERE mapping_code=?
                    """, (notes, metadata, now, code))

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Pre-commit database checks failed: integrity={integrity}; FK errors={len(fk_errors)}")
        con.commit()

        print("\nFOUR-INSTRUMENT NSE SOURCE STAGING COMMITTED")
        print("=" * 112)
        total_staged = 0
        for item, external_id, slice_hash, _ in staged:
            row_count = con.execute(
                "SELECT COUNT(*) FROM external_index_daily_records WHERE batch_id=?", (external_id,)
            ).fetchone()[0]
            total_staged += int(row_count)
            print(
                f"{item.instrument:10} {item.year} | external_batch_id={external_id} "
                f"| staged_rows={row_count} | source_table={item.source_table}"
            )
        print(f"Total staged records across all files: {total_staged}")
        print(f"Year-specific source mappings: {len(staged)} (pending_review unless already active)")
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print("Canonical daily/quality/aggregate tables: unchanged")
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
    parser.add_argument("--snapshot-batch", type=int, default=4)
    args = parser.parse_args()
    if not args.database.is_file():
        raise FileNotFoundError(args.database)
    if not args.input_dir.is_dir():
        raise FileNotFoundError(args.input_dir)

    files = [
        parse_source_file(instrument, year, args.input_dir)
        for instrument in INSTRUMENTS
        for year in (2025, 2026)
    ]
    # All CSV parsing occurs before opening the DB; open SQLite read-only for preflight.
    con = sqlite3.connect(f"file:{args.database.as_posix()}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        inspect_and_reconcile(con, files, args.snapshot_batch)
        print_plan(con, files, args.snapshot_batch, apply_mode=args.apply)
    finally:
        con.close()

    total_mismatches = sum(item.overlap_mismatches for item in files)
    if total_mismatches:
        raise RuntimeError(
            f"Found {total_mismatches} canonical overlap mismatch groups > {TOLERANCE:.2f}; staging apply is blocked"
        )
    if not args.apply:
        print("\nDry run completed. No database or source files were modified.")
        print("Review the plan, then rerun with --apply to stage the four instruments.")
        return 0

    apply_staging(args.database, files, args.snapshot_batch)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
