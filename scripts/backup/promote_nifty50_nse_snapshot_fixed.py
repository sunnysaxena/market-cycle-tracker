#!/usr/bin/env python3
"""Promote staged NSE NIFTY 50 history into a new composite snapshot.

Default mode is a read-only dry run. Use --apply only after reviewing the plan.
The script backs up the SQLite database, revalidates inside a write transaction,
creates a new snapshot, and leaves all previous snapshots and aggregates intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"

PARENT_BATCH_ID = 3
EXTERNAL_BATCH_IDS = (5, 6)
INSTRUMENT = "NIFTY50"
INDEX_NAME = "NIFTY 50"
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
MAPPING_CODE = "NSE:NIFTY50:nse_indices_historical_2025_to_2026:1D"
MAPPING_SOURCE_TABLE = "nse_indices_historical_2025_to_2026"
SOURCE_TABLE_PREFIX = "nse_indices_historical"
START_DATE = "2025-01-01"
END_DATE = "2026-10-30"
TOLERANCE = 0.02
EXPECTED_ROWS = 454
EXPECTED_OVERLAPS = 44
EXPECTED_NEW_DATES = 410
EXPECTED_PARENT = {"raw": 20559, "quality": 20559, "close": 20505, "ohlc": 20385}
EXPECTED_PARENT_NIFTY = {"raw": 3728, "close": 3728, "ohlc": 3728}
EXPECTED_NEW = {"raw": 20969, "quality": 20969, "close": 20915, "ohlc": 20795}
EXPECTED_NEW_NIFTY = {"raw": 4138, "close": 4138, "ohlc": 4138}
COMPOSITE_PATH = (
    "composite_snapshot://batch_3+NSE_NIFTY50_external_batches_5_6"
    "?policy=replace_NIFTY50_2025_01_01_to_2026_10_30"
)
EXPECTED_FILES = {
    2025: {
        "batch_id": 5,
        "filename": "nifty50_nse_2025.csv",
        "sha256": "ce1faf932060e5edde6615044e18c4754e8de73285e2ca412f2b22c9415f65d1",
        "rows": 249,
        "overlaps": 44,
        "start": "2025-01-01",
        "end": "2025-12-31",
    },
    2026: {
        "batch_id": 6,
        "filename": "nifty50_nse_2026.csv",
        "sha256": "b2a6d13df4c5168aa110fef27dde05b184692e2a8137a4da20075aad36fcea90",
        "rows": 205,
        "overlaps": 0,
        "start": "2026-01-01",
        "end": "2026-10-30",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_count(con: sqlite3.Connection, table: str, batch_id: int) -> int:
    return int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=?", (batch_id,)
    ).fetchone()[0])


def instrument_count(con: sqlite3.Connection, table: str, batch_id: int) -> int:
    return int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=? AND instrument_code=?",
        (batch_id, INSTRUMENT),
    ).fetchone()[0])


def collect_plan(con: sqlite3.Connection) -> dict[str, Any]:
    required_tables = (
        "import_batches", "raw_daily_records", "daily_quality_assessments",
        "daily_close_series", "daily_ohlcv_analytical", "aggregated_ohlcv",
        "aggregated_close_series", "historical_data_sources",
        "historical_instrument_source_mappings", "historical_source_batch_links",
        "external_index_source_batches", "external_index_daily_records",
        "exchange_calendar_events",
    )
    missing = [t for t in required_tables if not table_exists(con, t)]
    require(not missing, f"Required tables are missing: {missing}.")

    parent = con.execute(
        "SELECT * FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)
    ).fetchone()
    require(parent is not None and parent["status"] == "completed",
            "Parent snapshot batch 3 is missing or not completed.")
    completed = [int(r[0]) for r in con.execute(
        "SELECT id FROM import_batches WHERE status='completed' ORDER BY id"
    ).fetchall()]
    require(completed == [1, 2, 3],
            f"Completed snapshot batches changed; expected [1, 2, 3], found {completed}.")

    parent_counts = {
        "raw": table_count(con, "raw_daily_records", PARENT_BATCH_ID),
        "quality": table_count(con, "daily_quality_assessments", PARENT_BATCH_ID),
        "close": table_count(con, "daily_close_series", PARENT_BATCH_ID),
        "ohlc": table_count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID),
    }
    require(parent_counts == EXPECTED_PARENT,
            f"Parent batch 3 counts differ from baseline: {parent_counts}.")

    mapping = con.execute(
        "SELECT * FROM historical_instrument_source_mappings WHERE mapping_code=?",
        (MAPPING_CODE,),
    ).fetchone()
    require(mapping is not None, "NIFTY50 NSE source mapping is missing.")
    require(mapping["source_code"] == SOURCE_CODE and mapping["instrument_code"] == INSTRUMENT,
            "NIFTY50 mapping source/instrument identity is unexpected.")
    require(mapping["source_table"] == MAPPING_SOURCE_TABLE and mapping["timeframe"] == "1D",
            "NIFTY50 mapping table/timeframe is unexpected.")
    require(mapping["mapping_status"] == "pending_review" and mapping["mapping_role"] == "pending_review",
            "NIFTY50 mapping is not pending_review; stop and inspect current state.")
    mapping_meta = json.loads(mapping["metadata_json"] or "{}")
    mapped_ids = sorted(int(x) for x in mapping_meta.get("external_source_batch_ids", []))
    require(mapped_ids == [5, 6], f"NIFTY50 mapping metadata has unexpected external batch IDs: {mapped_ids}.")

    source = con.execute(
        "SELECT * FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()
    require(source is not None and source["source_type"] == "official_exchange_portal",
            "NSE official source registry row is missing or has unexpected type.")

    # Validate all contributing registries and all six staged/external source references.
    for source_code in ("LEGACY_MYSQL_DUMP_20260308", "BSE_INDICES_HISTORICAL_DATA", SOURCE_CODE):
        require(con.execute(
            "SELECT COUNT(*) FROM historical_data_sources WHERE source_code=?", (source_code,)
        ).fetchone()[0] == 1, f"Contributing source registry row is missing: {source_code}.")
    external_registry = con.execute(
        "SELECT id, instrument_code, calendar_year, source_filename, source_sha256, source_row_count, unique_date_count, import_status, expected_session_count, source_provider, source_size_bytes"
        " FROM external_index_source_batches WHERE id IN (1,2,3,4,5,6) ORDER BY id"
    ).fetchall()
    require([int(r["id"]) for r in external_registry] == [1, 2, 3, 4, 5, 6],
            "Expected existing external source batches 1 through 6 for composite provenance.")

    staged: list[sqlite3.Row] = []
    year_counts: dict[int, int] = {}
    for year, exp in EXPECTED_FILES.items():
        batch = con.execute(
            "SELECT * FROM external_index_source_batches WHERE id=?",
            (exp["batch_id"],),
        ).fetchone()
        require(batch is not None, f"NSE external source batch {exp['batch_id']} is missing.")
        require(batch["instrument_code"] == INSTRUMENT and int(batch["calendar_year"]) == year,
                f"External batch {exp['batch_id']} instrument/year mismatch.")
        require(batch["source_filename"] == exp["filename"] and batch["source_sha256"] == exp["sha256"],
                f"External batch {exp['batch_id']} file identity/hash mismatch.")
        require(int(batch["source_row_count"]) == exp["rows"] and int(batch["unique_date_count"]) == exp["rows"],
                f"External batch {exp['batch_id']} row/unique-date counts mismatch.")
        require(batch["import_status"] == "staged_validated_calendar_incomplete" and int(batch["expected_session_count"]) == 0,
                f"External batch {exp['batch_id']} status/calendar assertion is unexpected.")
        require(batch["source_provider"] == "NSE Indices historical-data report",
                f"External batch {exp['batch_id']} provider is unexpected.")

        rows = con.execute(
            "SELECT * FROM external_index_daily_records WHERE batch_id=? ORDER BY candle_date",
            (exp["batch_id"],),
        ).fetchall()
        require(len(rows) == exp["rows"],
                f"External batch {exp['batch_id']} staged {len(rows)} rows; expected {exp['rows']}.")
        dates = [r["candle_date"] for r in rows]
        require(len(set(dates)) == len(dates), f"Duplicate NIFTY50 dates found in year {year}.")
        require(min(dates) == exp["start"] and max(dates) == exp["end"],
                f"Unexpected NIFTY50 {year} date range.")
        overlap_n = 0
        for r in rows:
            require(r["instrument_code"] == INSTRUMENT and r["source_index_name"] == INDEX_NAME,
                    f"Instrument/index identity mismatch on {r['candle_date']}.")
            vals = [float(r[k]) for k in ("open", "high", "low", "close")]
            o, h, l, c = vals
            require(all(v > 0 for v in vals) and h >= max(o, l, c) and l <= min(o, h, c),
                    f"Invalid OHLC geometry on {r['candle_date']}.")
            require(r["quality_status"] == "valid_ohlc" and not json.loads(r["issue_codes"] or "[]"),
                    f"Staged quality issue on {r['candle_date']}.")
            status = r["overlap_status"]
            if status != "no_legacy_daily_record":
                overlap_n += 1
                require(status == "ohlc_match_within_0_02",
                        f"Unexpected overlap status on {r['candle_date']}: {status}.")
                for fld in ("open", "high", "low", "close"):
                    require(r[f"legacy_{fld}"] is not None and
                            abs(float(r[fld]) - float(r[f"legacy_{fld}"])) <= TOLERANCE,
                            f"Staged-vs-legacy {fld} mismatch on {r['candle_date']}.")
            else:
                require(all(r[f"legacy_{fld}"] is None for fld in ("open", "high", "low", "close")),
                        f"Unexpected legacy values on new date {r['candle_date']}.")
            staged.append(r)
        require(overlap_n == exp["overlaps"],
                f"Year {year} overlap count {overlap_n}; expected {exp['overlaps']}.")
        link_n = con.execute(
            "SELECT COUNT(*) FROM historical_source_batch_links WHERE source_code=? AND external_source_batch_id=? AND link_role='staged_external_file'",
            (SOURCE_CODE, exp["batch_id"]),
        ).fetchone()[0]
        require(link_n == 1, f"Expected one staged source link for external batch {exp['batch_id']}.")
        year_counts[year] = len(rows)

    dates = [r["candle_date"] for r in staged]
    require(len(staged) == EXPECTED_ROWS and len(set(dates)) == EXPECTED_ROWS,
            f"Combined staged rows/dates mismatch: {len(staged)} rows, {len(set(dates))} unique dates.")
    require(min(dates) == START_DATE and max(dates) == END_DATE,
            "Combined staged NIFTY50 replacement window is unexpected.")
    overlap_rows = [r for r in staged if r["overlap_status"] != "no_legacy_daily_record"]
    new_rows = [r for r in staged if r["overlap_status"] == "no_legacy_daily_record"]
    require(len(overlap_rows) == EXPECTED_OVERLAPS and len(new_rows) == EXPECTED_NEW_DATES,
            f"Combined overlap/new counts mismatch: {len(overlap_rows)}/{len(new_rows)}.")

    overlap_dates = sorted(r["candle_date"] for r in overlap_rows)
    for d in overlap_dates:
        raw = con.execute(
            "SELECT id FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=? AND date(source_timestamp)=?",
            (PARENT_BATCH_ID, INSTRUMENT, d),
        ).fetchall()
        close = con.execute(
            "SELECT close FROM daily_close_series WHERE import_batch_id=? AND instrument_code=? AND candle_date=?",
            (PARENT_BATCH_ID, INSTRUMENT, d),
        ).fetchall()
        ohlc = con.execute(
            "SELECT open,high,low,close FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=? AND candle_date=?",
            (PARENT_BATCH_ID, INSTRUMENT, d),
        ).fetchall()
        require(len(raw) == len(close) == len(ohlc) == 1,
                f"Expected exactly one parent raw/close/OHLC row on overlap {d}.")
        staged_row = next(r for r in overlap_rows if r["candle_date"] == d)
        for i, fld in enumerate(("open", "high", "low", "close")):
            require(abs(float(staged_row[fld]) - float(ohlc[0][i])) <= TOLERANCE,
                    f"Direct parent OHLC mismatch on {d} ({fld}).")
        require(abs(float(staged_row["close"]) - float(close[0][0])) <= TOLERANCE,
                f"Direct parent close mismatch on {d}.")

    parent_nifty = {
        "raw": int(con.execute(
            "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=?",
            (PARENT_BATCH_ID, INSTRUMENT),
        ).fetchone()[0]),
        "close": instrument_count(con, "daily_close_series", PARENT_BATCH_ID),
        "ohlc": instrument_count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID),
    }
    require(parent_nifty == EXPECTED_PARENT_NIFTY,
            f"Parent NIFTY50 counts differ from baseline: {parent_nifty}.")

    weekend_dates = sorted({d for d in dates if date.fromisoformat(d).weekday() >= 5})
    for d in weekend_dates:
        event_n = con.execute(
            "SELECT COUNT(*) FROM exchange_calendar_events WHERE exchange='NSE' AND market_segment='EQUITY' AND session_date=? AND event_type='special_session_open'",
            (d,),
        ).fetchone()[0]
        require(event_n == 1, f"NSE weekend session {d} is not registered exactly once.")
    holiday_dates = con.execute(
        "SELECT session_date FROM exchange_calendar_events WHERE exchange='NSE' AND market_segment='EQUITY' AND event_type='holiday_closed' AND session_date BETWEEN ? AND ?",
        (START_DATE, END_DATE),
    ).fetchall()
    holiday_set = {r[0] for r in holiday_dates}
    require(not (set(dates) & holiday_set),
            f"Staged NIFTY50 records fall on registered NSE holidays: {sorted(set(dates) & holiday_set)}.")

    existing = con.execute(
        "SELECT id FROM import_batches WHERE source_path=?", (COMPOSITE_PATH,)
    ).fetchone()
    if existing is not None:
        raise RuntimeError(
            f"NIFTY50 composite snapshot already exists as batch {existing['id']}."
        )
    next_batch_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM import_batches"
    ).fetchone()[0])
    require(next_batch_id == 4,
            f"Expected new snapshot batch ID 4; next ID is {next_batch_id}.")

    contribution_codes = [
        "LEGACY:IMPORT:4:CONTRIBUTION",
        "NSE:SNAPSHOT:4:EXTERNAL:1", "NSE:SNAPSHOT:4:EXTERNAL:2",
        "BSE:SNAPSHOT:4:EXTERNAL:3", "BSE:SNAPSHOT:4:EXTERNAL:4",
        "NSE:SNAPSHOT:4:EXTERNAL:5", "NSE:SNAPSHOT:4:EXTERNAL:6",
    ]
    marks = ",".join("?" for _ in contribution_codes)
    collisions = con.execute(
        f"SELECT link_code FROM historical_source_batch_links WHERE link_code IN ({marks})",
        tuple(contribution_codes),
    ).fetchall()
    require(not collisions, f"Snapshot contribution link-code collisions: {[r[0] for r in collisions]}.")

    expected = {
        "raw": parent_counts["raw"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
        "quality": parent_counts["quality"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
        "close": parent_counts["close"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
        "ohlc": parent_counts["ohlc"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
    }
    require(expected == EXPECTED_NEW, f"Calculated composite counts are unexpected: {expected}.")
    expected_nifty = {
        "raw": parent_nifty["raw"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
        "close": parent_nifty["close"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
        "ohlc": parent_nifty["ohlc"] - EXPECTED_OVERLAPS + EXPECTED_ROWS,
    }
    require(expected_nifty == EXPECTED_NEW_NIFTY,
            f"Calculated NIFTY50 counts are unexpected: {expected_nifty}.")

    # Record prior snapshots' table counts and parent's aggregate counts for post-apply invariance checks.
    prior_counts: dict[int, dict[str, int]] = {}
    for batch_id in (1, 2, 3):
        prior_counts[batch_id] = {
            t: table_count(con, t, batch_id)
            for t in ("raw_daily_records", "daily_quality_assessments", "daily_close_series", "daily_ohlcv_analytical")
        }
    parent_aggregates = {
        "ohlcv": table_count(con, "aggregated_ohlcv", PARENT_BATCH_ID),
        "close": table_count(con, "aggregated_close_series", PARENT_BATCH_ID),
    }

    return {
        "parent": parent,
        "source": source,
        "mapping": mapping,
        "external_batches": external_registry,
        "staged": staged,
        "dates": dates,
        "overlap_dates": overlap_dates,
        "overlap_count": len(overlap_rows),
        "new_count": len(new_rows),
        "weekend_dates": weekend_dates,
        "parent_counts": parent_counts,
        "parent_nifty": parent_nifty,
        "expected": expected,
        "expected_nifty": expected_nifty,
        "next_batch_id": next_batch_id,
        "year_counts": year_counts,
        "prior_counts": prior_counts,
        "parent_aggregates": parent_aggregates,
        "contribution_codes": contribution_codes,
    }


def print_plan(plan: dict[str, Any], mode: str) -> None:
    print("NIFTY 50 NSE COMPOSITE SNAPSHOT PROMOTION")
    print("=" * 94)
    print(f"Database: {DATABASE}")
    print(f"Parent snapshot: batch {PARENT_BATCH_ID} (completed; preserved unchanged)")
    print(f"External source batches: {EXTERNAL_BATCH_IDS}")
    print(f"Mode: {mode}")
    print("OHLC source only; no volume is imported.")
    print("\nSOURCE RECONCILIATION")
    print("-" * 94)
    for year, batch_id in ((2025, 5), (2026, 6)):
        rows = plan["year_counts"][year]
        exp = EXPECTED_FILES[year]
        print(f"{year} | external batch={batch_id} | rows={rows} | overlaps={exp['overlaps']} | new={rows-exp['overlaps']}")
    print(f"Combined staged NIFTY50 rows : {len(plan['staged'])}")
    print(f"Canonical matching overlaps  : {plan['overlap_count']}")
    print(f"New dates beyond parent       : {plan['new_count']}")
    print(f"Registered weekend sessions  : {plan['weekend_dates']}")
    print("Overlap mismatch records     : 0")

    print("\nPROPOSED COMPOSITE SNAPSHOT")
    print("-" * 94)
    print(f"New import batch ID                 : {plan['next_batch_id']}")
    print(f"Parent batch preserved              : {PARENT_BATCH_ID}")
    print(f"NIFTY50 replacement window          : {START_DATE} to {END_DATE}")
    print(f"NSE NIFTY50 rows to add              : {EXPECTED_ROWS}")
    print(f"Legacy NIFTY50 rows omitted          : {EXPECTED_OVERLAPS}")
    print(f"New dates beyond parent              : {EXPECTED_NEW_DATES}")
    print(f"Expected raw rows                    : {plan['expected']['raw']}")
    print(f"Expected quality assessments         : {plan['expected']['quality']}")
    print(f"Expected daily close rows             : {plan['expected']['close']}")
    print(f"Expected full-OHLC rows               : {plan['expected']['ohlc']}")
    print(f"Expected NIFTY50 raw/close/OHLC       : {plan['expected_nifty']['raw']} / {plan['expected_nifty']['close']} / {plan['expected_nifty']['ohlc']}")
    print("NSE NIFTY50 mapping after promotion : preferred_for_period / active")
    print(f"NSE preferred period                 : {START_DATE} to {END_DATE}")
    print("BANKNIFTY and SENSEX mappings         : unchanged")
    print("Other instrument records             : copied from parent batch 3 unchanged")
    print("Aggregates                           : not copied/rebuilt by this step")
    print(f"Parent batch {PARENT_BATCH_ID} aggregates               : preserved unchanged")
    print("Volume                               : unavailable; no index-volume field in source")
    print("Source-row provenance                : year-specific NSE table names")
    print("\nSOURCE CONTRIBUTION PLAN")
    print("-" * 94)
    print("Legacy batch 3 retained records")
    print("NSE external batches 1 and 2 (BANKNIFTY)")
    print("BSE external batches 3 and 4 (SENSEX)")
    print("NSE external batches 5 and 6 (NIFTY50)")
    print("\nParent batches 1, 2 and 3 remain untouched.")


def make_backup() -> tuple[Path, str]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"historical_staging_before_nifty50_promotion_{stamp}.db"
    src = sqlite3.connect(DATABASE, timeout=60)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    require(integrity == "ok", f"Backup integrity failed: {integrity}.")
    require(not fk_errors, f"Backup has {len(fk_errors)} foreign-key errors.")
    return backup, hashlib.sha256(backup.read_bytes()).hexdigest()


def apply_promotion() -> None:
    backup, backup_sha = make_backup()
    print(f"\nVerified database backup: {backup}")
    print(f"Backup SHA-256: {backup_sha}")

    con = sqlite3.connect(DATABASE, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 120000")
    try:
        con.execute("BEGIN IMMEDIATE")
        # Re-run every preflight assertion while holding the write transaction.
        plan = collect_plan(con)
        require(plan["next_batch_id"] == 4, "New batch ID changed before apply.")
        print_plan(plan, "APPLY (transactional)")

        parent = plan["parent"]
        external_batches = [r for r in plan["external_batches"] if int(r["id"]) in EXTERNAL_BATCH_IDS]
        batch_hash_inputs = {
            "parent_batch_id": PARENT_BATCH_ID,
            "parent_sha256": parent["source_sha256"],
            "external_batches": [
                {"id": int(r["id"]), "sha256": r["source_sha256"], "calendar_year": int(r["calendar_year"])}
                for r in external_batches
            ],
            "policy": "replace_NIFTY50_2025-01-01_to_2026-10-30_with_NSE_source",
        }
        composite_hash = hashlib.sha256(
            json.dumps(batch_hash_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source_size = int(parent["source_size_bytes"]) + sum(int(r["source_size_bytes"]) for r in external_batches)
        created_at = utc_now()

        cur = con.execute(
            """INSERT INTO import_batches (
                source_path, source_sha256, source_size_bytes,
                status, imported_rows, imported_at_utc
            ) VALUES (?, ?, ?, 'completed', ?, ?)""",
            (COMPOSITE_PATH, composite_hash, source_size, plan["expected"]["raw"], created_at),
        )
        new_batch_id = int(cur.lastrowid)
        require(new_batch_id == 4, f"Inserted batch ID {new_batch_id}, expected 4.")

        staged_dates = set(plan["dates"])
        parent_raw_rows = con.execute(
            "SELECT * FROM raw_daily_records WHERE import_batch_id=? ORDER BY id",
            (PARENT_BATCH_ID,),
        ).fetchall()
        replaced_old_ids: set[int] = set()
        copied_raw_map: dict[int, int] = {}
        raw_insert_sql = """INSERT INTO raw_daily_records (
            import_batch_id, instrument_code, source_table, source_row_number,
            source_id, source_timestamp, open_raw, high_raw, low_raw, close_raw, volume_raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        for r in parent_raw_rows:
            d = (r["source_timestamp"] or "")[:10]
            if r["instrument_code"] == INSTRUMENT and d in staged_dates:
                replaced_old_ids.add(int(r["id"]))
                continue
            ins = con.execute(raw_insert_sql, (
                new_batch_id, r["instrument_code"], r["source_table"], r["source_row_number"],
                r["source_id"], r["source_timestamp"], r["open_raw"], r["high_raw"],
                r["low_raw"], r["close_raw"], r["volume_raw"],
            ))
            copied_raw_map[int(r["id"])] = int(ins.lastrowid)
        require(len(replaced_old_ids) == EXPECTED_OVERLAPS,
                f"Expected to replace 44 old NIFTY50 raw records; found {len(replaced_old_ids)}.")

        quality_rows = con.execute(
            "SELECT * FROM daily_quality_assessments WHERE import_batch_id=? ORDER BY raw_record_id",
            (PARENT_BATCH_ID,),
        ).fetchall()
        copied_quality = 0
        for q in quality_rows:
            old_id = int(q["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = copied_raw_map.get(old_id)
            require(new_raw_id is not None, f"No copied raw record for quality row {old_id}.")
            con.execute(
                """INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code, source_table,
                    source_timestamp, record_status, close_eligible, full_ohlc_eligible,
                    volume_eligible, issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_raw_id, new_batch_id, q["instrument_code"], q["source_table"], q["source_timestamp"],
                 q["record_status"], q["close_eligible"], q["full_ohlc_eligible"],
                 q["volume_eligible"], q["issue_codes"], q["assessed_at_utc"]),
            )
            copied_quality += 1

        close_rows = con.execute(
            "SELECT * FROM daily_close_series WHERE import_batch_id=? ORDER BY instrument_code,candle_date",
            (PARENT_BATCH_ID,),
        ).fetchall()
        copied_close = 0
        for r in close_rows:
            old_id = int(r["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = copied_raw_map.get(old_id)
            require(new_raw_id is not None, f"No copied raw record for close row {old_id}.")
            con.execute(
                """INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close, raw_record_id,
                    source_id, source_table, source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, r["instrument_code"], r["candle_date"], r["close"], new_raw_id,
                 r["source_id"], r["source_table"], r["source_quality_status"], r["issue_codes"]),
            )
            copied_close += 1

        ohlc_rows = con.execute(
            "SELECT * FROM daily_ohlcv_analytical WHERE import_batch_id=? ORDER BY instrument_code,candle_date",
            (PARENT_BATCH_ID,),
        ).fetchall()
        copied_ohlc = 0
        for r in ohlc_rows:
            old_id = int(r["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = copied_raw_map.get(old_id)
            require(new_raw_id is not None, f"No copied raw record for OHLC row {old_id}.")
            con.execute(
                """INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date, open, high, low, close,
                    volume, volume_status, source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, r["instrument_code"], r["candle_date"], r["open"], r["high"],
                 r["low"], r["close"], r["volume"], r["volume_status"], r["source_volume_raw"],
                 new_raw_id, r["source_id"], r["source_table"], r["quality_status"], r["issue_codes"]),
            )
            copied_ohlc += 1

        # Add all 454 NSE records. Year-specific source_table labels retain unique
        # source-row provenance because each CSV restarts its row numbering.
        external_rows = con.execute(
            """SELECT r.id AS external_record_id, r.batch_id, b.calendar_year,
                      r.source_row_number, r.candle_date, r.open_raw, r.high_raw,
                      r.low_raw, r.close_raw, r.open, r.high, r.low, r.close
               FROM external_index_daily_records r
               JOIN external_index_source_batches b ON b.id=r.batch_id
               WHERE r.batch_id IN (?, ?)
               ORDER BY r.candle_date""",
            EXTERNAL_BATCH_IDS,
        ).fetchall()
        require(len(external_rows) == EXPECTED_ROWS,
                f"Expected 454 NSE external records at apply; found {len(external_rows)}.")
        issue_codes = json.dumps(["nse_indices_historical_source", "volume_unavailable"], separators=(",", ":"))
        inserted_external = 0
        for r in external_rows:
            year = int(r["calendar_year"])
            source_table = f"{SOURCE_TABLE_PREFIX}_{year}"
            source_id = f"NSE_EXT:{r['external_record_id']}"
            d = r["candle_date"]
            source_timestamp = f"{d} 00:00:00"
            ins = con.execute(raw_insert_sql, (
                new_batch_id, INSTRUMENT, source_table, r["source_row_number"], source_id,
                source_timestamp, r["open_raw"], r["high_raw"], r["low_raw"], r["close_raw"], None,
            ))
            new_raw_id = int(ins.lastrowid)
            con.execute(
                """INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code, source_table,
                    source_timestamp, record_status, close_eligible, full_ohlc_eligible,
                    volume_eligible, issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'accepted', 1, 1, 0, ?, ?)""",
                (new_raw_id, new_batch_id, INSTRUMENT, source_table, source_timestamp, issue_codes, created_at),
            )
            con.execute(
                """INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close, raw_record_id,
                    source_id, source_table, source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', ?)""",
                (new_batch_id, INSTRUMENT, d, float(r["close"]), new_raw_id, source_id, source_table, issue_codes),
            )
            con.execute(
                """INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date, open, high, low, close,
                    volume, volume_status, source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'unavailable', NULL, ?, ?, ?, 'accepted', ?)""",
                (new_batch_id, INSTRUMENT, d, float(r["open"]), float(r["high"]), float(r["low"]),
                 float(r["close"]), new_raw_id, source_id, source_table, issue_codes),
            )
            inserted_external += 1

        actual = {
            "raw": table_count(con, "raw_daily_records", new_batch_id),
            "quality": table_count(con, "daily_quality_assessments", new_batch_id),
            "close": table_count(con, "daily_close_series", new_batch_id),
            "ohlc": table_count(con, "daily_ohlcv_analytical", new_batch_id),
        }
        require(actual == plan["expected"], f"Composite counts mismatch: {actual}; expected {plan['expected']}.")
        new_nifty = {
            "raw": int(con.execute(
                "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=?",
                (new_batch_id, INSTRUMENT),
            ).fetchone()[0]),
            "close": instrument_count(con, "daily_close_series", new_batch_id),
            "ohlc": instrument_count(con, "daily_ohlcv_analytical", new_batch_id),
        }
        require(new_nifty == plan["expected_nifty"],
                f"New NIFTY50 counts mismatch: {new_nifty}; expected {plan['expected_nifty']}.")
        require(inserted_external == EXPECTED_ROWS, f"Inserted {inserted_external} external rows, expected 454.")
        for year, expected_rows in ((2025, 249), (2026, 205)):
            suffix = f"{SOURCE_TABLE_PREFIX}_{year}"
            n = con.execute(
                "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=? AND source_table=?",
                (new_batch_id, INSTRUMENT, suffix),
            ).fetchone()[0]
            require(n == expected_rows, f"Promoted {year} NIFTY50 OHLC rows={n}; expected {expected_rows}.")
        latest = con.execute(
            "SELECT MAX(candle_date) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=?",
            (new_batch_id, INSTRUMENT),
        ).fetchone()[0]
        require(latest == END_DATE, f"Unexpected latest NIFTY50 date after promotion: {latest}.")

        missing_quality = con.execute(
            """SELECT COUNT(*) FROM raw_daily_records r
               LEFT JOIN daily_quality_assessments q ON q.raw_record_id=r.id
               WHERE r.import_batch_id=? AND q.raw_record_id IS NULL""",
            (new_batch_id,),
        ).fetchone()[0]
        require(missing_quality == 0, f"New snapshot has {missing_quality} raw rows without quality assessments.")

        # Activate the NSE NIFTY50 mapping only after all row-level checks pass.
        mapping_note = (
            "NSE Indices NIFTY 50 daily OHLC source reconciled against 44 matching legacy overlaps; "
            "454 validated daily rows promoted into composite snapshot batch 4. Preferred for "
            "2025-01-01 through 2026-10-30. No volume field was supplied by the source. "
            "Annual calendar coverage is incomplete; expected session totals are not asserted."
        )
        con.execute(
            """UPDATE historical_instrument_source_mappings
               SET mapping_role='preferred_for_period', mapping_status='active',
                   valid_from=?, valid_to=?, priority=10, notes=?, updated_at_utc=?
               WHERE mapping_code=?""",
            (START_DATE, END_DATE, mapping_note, created_at, MAPPING_CODE),
        )
        require(con.execute("SELECT changes()").fetchone()[0] == 1,
                "NIFTY50 source mapping was not activated exactly once.")

        # Preserve NSE source metadata and append this composite's provenance.
        source_row = con.execute(
            "SELECT metadata_json FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)
        ).fetchone()
        source_meta = json.loads(source_row["metadata_json"] or "{}")
        previous_ids = source_meta.get("external_source_batch_ids", [])
        if not isinstance(previous_ids, list):
            previous_ids = []
        source_meta["external_source_batch_ids"] = sorted({int(x) for x in previous_ids} | set(EXTERNAL_BATCH_IDS))
        snapshot_ids = source_meta.get("composite_snapshot_batch_ids", [])
        if not isinstance(snapshot_ids, list):
            snapshot_ids = []
        # Preserve any older singular snapshot reference before advancing the latest pointer.
        previous_snapshot_id = source_meta.get("composite_snapshot_batch_id")
        prior_snapshot_ids = {int(x) for x in snapshot_ids}
        if previous_snapshot_id is not None:
            prior_snapshot_ids.add(int(previous_snapshot_id))
        source_meta["composite_snapshot_batch_ids"] = sorted(prior_snapshot_ids | {new_batch_id})
        source_meta["composite_snapshot_batch_id"] = new_batch_id
        con.execute(
            "UPDATE historical_data_sources SET metadata_json=?, updated_at_utc=? WHERE source_code=?",
            (json.dumps(source_meta, sort_keys=True), created_at, SOURCE_CODE),
        )

        # Link every contributing source file to the new composite snapshot.
        contribution_links = [
            ("LEGACY:IMPORT:4:CONTRIBUTION", "LEGACY_MYSQL_DUMP_20260308", None,
             "Legacy-source records outside the NIFTY50 replacement period contribute to composite snapshot 4."),
            ("NSE:SNAPSHOT:4:EXTERNAL:1", SOURCE_CODE, 1,
             "NSE BANKNIFTY 2015 external source batch 1 retained in composite snapshot 4."),
            ("NSE:SNAPSHOT:4:EXTERNAL:2", SOURCE_CODE, 2,
             "NSE BANKNIFTY 2016 external source batch 2 retained in composite snapshot 4."),
            ("BSE:SNAPSHOT:4:EXTERNAL:3", "BSE_INDICES_HISTORICAL_DATA", 3,
             "BSE SENSEX 2025 external source batch 3 retained in composite snapshot 4."),
            ("BSE:SNAPSHOT:4:EXTERNAL:4", "BSE_INDICES_HISTORICAL_DATA", 4,
             "BSE SENSEX 2026 external source batch 4 retained in composite snapshot 4."),
            ("NSE:SNAPSHOT:4:EXTERNAL:5", SOURCE_CODE, 5,
             "NSE NIFTY50 2025 external source batch 5 promoted into composite snapshot 4."),
            ("NSE:SNAPSHOT:4:EXTERNAL:6", SOURCE_CODE, 6,
             "NSE NIFTY50 2026 external source batch 6 promoted into composite snapshot 4."),
        ]
        for link_code, src_code, external_id, notes in contribution_links:
            con.execute(
                """INSERT INTO historical_source_batch_links (
                    link_code, source_code, import_batch_id, external_source_batch_id,
                    link_role, notes, created_at_utc
                ) VALUES (?, ?, ?, ?, 'contributed_to_snapshot', ?, ?)""",
                (link_code, src_code, new_batch_id, external_id, notes, created_at),
            )

        # Confirm all previous snapshot rows and the parent's prebuilt aggregates remain unchanged.
        for batch_id, counts in plan["prior_counts"].items():
            actual_prior = {
                t: table_count(con, t, batch_id)
                for t in ("raw_daily_records", "daily_quality_assessments", "daily_close_series", "daily_ohlcv_analytical")
            }
            require(actual_prior == counts,
                    f"Existing snapshot batch {batch_id} changed: {actual_prior} vs {counts}.")
        parent_aggregates_now = {
            "ohlcv": table_count(con, "aggregated_ohlcv", PARENT_BATCH_ID),
            "close": table_count(con, "aggregated_close_series", PARENT_BATCH_ID),
        }
        require(parent_aggregates_now == plan["parent_aggregates"],
                "Parent batch 3 aggregate counts changed unexpectedly.")
        require(table_count(con, "aggregated_ohlcv", new_batch_id) == 0 and
                table_count(con, "aggregated_close_series", new_batch_id) == 0,
                "New snapshot unexpectedly contains aggregates before the rebuild step.")

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        require(integrity == "ok", f"SQLite integrity check failed: {integrity}.")
        require(not fk_errors, f"Foreign-key check found {len(fk_errors)} errors.")
        con.commit()

        print("\nNIFTY 50 NSE PROMOTION COMMITTED")
        print("=" * 94)
        print(f"New composite import_batch_id : {new_batch_id}")
        print(f"New raw rows                  : {actual['raw']}")
        print(f"New quality assessments       : {actual['quality']}")
        print(f"New daily close rows          : {actual['close']}")
        print(f"New full-OHLC rows             : {actual['ohlc']}")
        print(f"NIFTY50 daily raw/close/OHLC   : {new_nifty['raw']} / {new_nifty['close']} / {new_nifty['ohlc']}")
        print(f"NSE NIFTY50 rows promoted      : {inserted_external}")
        print("NIFTY50 mapping                : preferred_for_period / active")
        print("Parent batches 1, 2 and 3      : preserved unchanged")
        print("Parent batch 3 aggregates      : preserved unchanged")
        print("New batch aggregates           : not built; run aggregation builder next")
        print(f"SQLite integrity               : {integrity}")
        print(f"Foreign-key errors             : {len(fk_errors)}")
        print(f"Verified backup                : {backup}")
    except Exception:
        con.rollback()
        print("\nPROMOTION FAILED — transaction rolled back.", file=sys.stderr)
        print(f"Verified backup remains at: {backup}", file=sys.stderr)
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply promotion; default is a read-only dry run.")
    args = parser.parse_args()
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    if not args.apply:
        con = connect_readonly(DATABASE)
        try:
            plan = collect_plan(con)
            print_plan(plan, "DRY RUN (read-only)")
        finally:
            con.close()
        print("\nDry run completed. No database changes or backup were made.")
        print("Review the proposed counts, then rerun with --apply to promote NIFTY50.")
        return 0

    # A read-only preflight first protects against creating a backup for a plan
    # that is already invalid. apply_promotion revalidates again under lock.
    con = connect_readonly(DATABASE)
    try:
        plan = collect_plan(con)
        print_plan(plan, "APPLY (preflight passed; write transaction follows)")
    finally:
        con.close()
    apply_promotion()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
