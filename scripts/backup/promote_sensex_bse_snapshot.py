#!/usr/bin/env python3
"""Promote staged BSE SENSEX history into a new composite snapshot.

Default mode is read-only dry-run. Use --apply to create a verified backup and
promote all staged BSE SENSEX records into a new composite import batch.

The prior completed snapshot is never modified. The 44 legacy SENSEX rows
covered by the BSE source are replaced only in the new snapshot; all 454 BSE
rows are retained there with raw provenance. Aggregate tables are not rebuilt
by this script.
"""

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

PARENT_BATCH_ID = 2
BSE_SOURCE_CODE = "BSE_INDICES_HISTORICAL_DATA"
BSE_MAPPING_CODE = "BSE:SENSEX:bse_indices_historical_2025_to_latest:1D"
BSE_EXTERNAL_BATCH_IDS = (3, 4)
BSE_SOURCE_TABLE = "bse_indices_historical_2025_to_latest"
START_DATE = "2025-01-01"
END_DATE = "2026-10-30"
EXPECTED_BSE_ROWS = 454
EXPECTED_OVERLAPS = 44
EXPECTED_NEW_DATES = 410
EXPECTED_PARENT_RAW = 20149
EXPECTED_PARENT_CLOSE = 20095
EXPECTED_PARENT_OHLC = 19975


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def table_count(con: sqlite3.Connection, table: str, batch_id: int) -> int:
    return int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id = ?",
        (batch_id,),
    ).fetchone()[0])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def collect_plan(con: sqlite3.Connection) -> dict[str, Any]:
    # Confirm source snapshot.
    parent = con.execute(
        "SELECT * FROM import_batches WHERE id = ?",
        (PARENT_BATCH_ID,),
    ).fetchone()
    require(parent is not None, f"Parent import batch {PARENT_BATCH_ID} not found.")
    require(parent["status"] == "completed", "Parent snapshot is not completed.")

    parent_raw = table_count(con, "raw_daily_records", PARENT_BATCH_ID)
    parent_quality = table_count(con, "daily_quality_assessments", PARENT_BATCH_ID)
    parent_close = table_count(con, "daily_close_series", PARENT_BATCH_ID)
    parent_ohlc = table_count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID)
    require(parent_raw == EXPECTED_PARENT_RAW, f"Unexpected parent raw count: {parent_raw}.")
    require(parent_quality == EXPECTED_PARENT_RAW, f"Unexpected parent quality count: {parent_quality}.")
    require(parent_close == EXPECTED_PARENT_CLOSE, f"Unexpected parent close count: {parent_close}.")
    require(parent_ohlc == EXPECTED_PARENT_OHLC, f"Unexpected parent OHLC count: {parent_ohlc}.")

    # Prevent a second promotion over the same source period.
    existing_path = (
        "composite_snapshot://batch_2+BSE_external_batches_3_4"
        "?policy=replace_SENSEX_2025_01_01_to_2026_10_30"
    )
    already = con.execute(
        "SELECT id FROM import_batches WHERE source_path = ?",
        (existing_path,),
    ).fetchone()
    if already is not None:
        raise RuntimeError(
            f"This SENSEX composite snapshot was already created (batch {already['id']})."
        )

    # BSE provider and pending mapping must exist.
    source = con.execute(
        "SELECT * FROM historical_data_sources WHERE source_code = ?",
        (BSE_SOURCE_CODE,),
    ).fetchone()
    require(source is not None, "BSE historical source is not registered.")
    require(source["source_type"] == "official_exchange_portal", "Unexpected BSE source type.")

    mapping = con.execute(
        "SELECT * FROM historical_instrument_source_mappings WHERE mapping_code = ?",
        (BSE_MAPPING_CODE,),
    ).fetchone()
    require(mapping is not None, "BSE SENSEX source mapping is not registered.")
    require(mapping["instrument_code"] == "SENSEX", "BSE mapping instrument is not SENSEX.")
    require(mapping["mapping_status"] == "pending_review", "BSE mapping is not pending_review; inspect before promotion.")

    placeholders = ",".join("?" for _ in BSE_EXTERNAL_BATCH_IDS)
    external_batches = con.execute(
        f"SELECT * FROM external_index_source_batches WHERE id IN ({placeholders}) ORDER BY calendar_year",
        BSE_EXTERNAL_BATCH_IDS,
    ).fetchall()
    require(len(external_batches) == 2, "Expected BSE external source batches 3 and 4.")
    by_year = {int(r["calendar_year"]): r for r in external_batches}
    require(set(by_year) == {2025, 2026}, "BSE source batches do not cover 2025 and 2026.")
    require(all(r["instrument_code"] == "SENSEX" for r in external_batches), "An external batch is not SENSEX.")
    require(all(str(r["import_status"]).startswith("staged_validated") for r in external_batches), "A BSE batch is not staged/validated.")

    staged = con.execute(
        f"""
        SELECT * FROM external_index_daily_records
        WHERE instrument_code = 'SENSEX'
          AND batch_id IN ({placeholders})
        ORDER BY candle_date
        """,
        BSE_EXTERNAL_BATCH_IDS,
    ).fetchall()
    require(len(staged) == EXPECTED_BSE_ROWS, f"Expected 454 staged BSE rows, found {len(staged)}.")
    dates = [r["candle_date"] for r in staged]
    require(len(set(dates)) == len(dates), "Duplicate SENSEX dates found across staged BSE batches.")
    require(min(dates) == START_DATE and max(dates) == END_DATE, "Unexpected BSE date range.")
    require(all(START_DATE <= d <= END_DATE for d in dates), "BSE source contains an out-of-range date.")
    require(all(r["quality_status"] == "valid_ohlc" for r in staged), "BSE source contains a non-valid OHLC row.")

    # Validate OHLC mathematically and compare all overlap fields precisely.
    for r in staged:
        o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        require(all(v > 0 for v in (o, h, l, c)), f"Non-positive OHLC value on {r['candle_date']}.")
        require(h >= max(o, l, c), f"Invalid High on {r['candle_date']}.")
        require(l <= min(o, h, c), f"Invalid Low on {r['candle_date']}.")

    overlap_rows = [r for r in staged if r["legacy_close"] is not None]
    new_rows = [r for r in staged if r["legacy_close"] is None]
    require(len(overlap_rows) == EXPECTED_OVERLAPS, f"Expected 44 legacy overlaps, found {len(overlap_rows)}.")
    require(len(new_rows) == EXPECTED_NEW_DATES, f"Expected 410 new dates, found {len(new_rows)}.")
    for r in overlap_rows:
        for fld in ("open", "high", "low", "close"):
            legacy_value = r[f"legacy_{fld}"]
            require(legacy_value is not None, f"Missing legacy {fld} on overlap {r['candle_date']}.")
            require(abs(float(r[fld]) - float(legacy_value)) < 1e-9,
                    f"BSE/legacy {fld} mismatch on {r['candle_date']}.")

    # Ensure the overlap in the parent snapshot is exactly the 44 staged dates.
    staged_dates = set(dates)
    parent_sensex_raw = con.execute(
        """
        SELECT id, source_timestamp
        FROM raw_daily_records
        WHERE import_batch_id = ? AND instrument_code = 'SENSEX'
        """,
        (PARENT_BATCH_ID,),
    ).fetchall()
    parent_overlap = [r for r in parent_sensex_raw if (r["source_timestamp"] or "")[:10] in staged_dates]
    require(len(parent_overlap) == EXPECTED_OVERLAPS, f"Expected 44 SENSEX raw rows to replace, found {len(parent_overlap)}.")

    # Verify that each replaced legacy date has curated close and full OHLC.
    overlap_dates = sorted(r["candle_date"] for r in overlap_rows)
    for d in overlap_dates:
        close_n = con.execute(
            "SELECT COUNT(*) FROM daily_close_series WHERE import_batch_id=? AND instrument_code='SENSEX' AND candle_date=?",
            (PARENT_BATCH_ID, d),
        ).fetchone()[0]
        ohlc_n = con.execute(
            "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code='SENSEX' AND candle_date=?",
            (PARENT_BATCH_ID, d),
        ).fetchone()[0]
        require(close_n == 1 and ohlc_n == 1, f"Expected one daily close and OHLC row for overlap {d}.")

    # BSE weekend rows must be registered as BSE special sessions.
    weekend_dates = []
    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        if dt.weekday() >= 5:
            weekend_dates.append(d)
            event = con.execute(
                """
                SELECT COUNT(*) FROM exchange_calendar_events
                WHERE exchange='BSE' AND market_segment='EQUITY'
                  AND session_date=? AND event_type='special_session_open'
                """,
                (d,),
            ).fetchone()[0]
            require(event == 1, f"BSE weekend date {d} has no registered special-session event.")

    # The common source row number must be unique for the common source table.
    source_row_numbers = [r["source_row_number"] for r in staged]
    require(all(v is not None for v in source_row_numbers), "BSE source row number is missing.")
    require(len(set(source_row_numbers)) == len(source_row_numbers),
            "BSE source row numbers are not unique across the two year slices.")

    # Check no conflicting rows already occupy the anticipated next batch ID.
    next_batch_id = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM import_batches").fetchone()[0])
    require(con.execute("SELECT COUNT(*) FROM import_batches WHERE id=?", (next_batch_id,)).fetchone()[0] == 0,
            "Next import batch ID is already occupied.")

    # Expected counts: remove 44 old SENSEX rows, add all 454 BSE rows.
    expected = {
        "raw": parent_raw - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
        "quality": parent_quality - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
        "close": parent_close - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
        "ohlc": parent_ohlc - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
    }
    expected_sensex = {
        "close": int(con.execute(
            "SELECT COUNT(*) FROM daily_close_series WHERE import_batch_id=? AND instrument_code='SENSEX'",
            (PARENT_BATCH_ID,),
        ).fetchone()[0]) - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
        "ohlc": int(con.execute(
            "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code='SENSEX'",
            (PARENT_BATCH_ID,),
        ).fetchone()[0]) - EXPECTED_OVERLAPS + EXPECTED_BSE_ROWS,
    }
    require(expected["raw"] == 20559 and expected["quality"] == 20559,
            f"Unexpected expected raw/quality counts: {expected}.")
    require(expected["close"] == 20505 and expected["ohlc"] == 20385,
            f"Unexpected expected curated counts: {expected}.")
    require(expected_sensex == {"close": 5314, "ohlc": 5314},
            f"Unexpected expected SENSEX counts: {expected_sensex}.")

    return {
        "parent": parent,
        "parent_counts": {
            "raw": parent_raw,
            "quality": parent_quality,
            "close": parent_close,
            "ohlc": parent_ohlc,
        },
        "external_batches": external_batches,
        "staged": staged,
        "dates": dates,
        "overlap_dates": overlap_dates,
        "overlap_count": len(overlap_rows),
        "new_count": len(new_rows),
        "weekend_dates": weekend_dates,
        "expected": expected,
        "expected_sensex": expected_sensex,
        "new_batch_id": next_batch_id,
        "source": source,
        "mapping": mapping,
    }


def print_plan(plan: dict[str, Any], mode: str) -> None:
    print("\nSENSEX BSE HISTORICAL SNAPSHOT PROMOTION")
    print("=" * 92)
    print(f"Database             : {DATABASE}")
    print(f"Mode                 : {mode}")
    print(f"Parent snapshot      : batch {PARENT_BATCH_ID} (completed; preserved unchanged)")
    print(f"BSE external batches : {', '.join(str(x) for x in BSE_EXTERNAL_BATCH_IDS)}")
    print(f"Replacement window   : {START_DATE} to {END_DATE}")

    print("\nSOURCE RECONCILIATION")
    print("-" * 92)
    print(f"BSE SENSEX records                     : {len(plan['staged'])}")
    print(f"Exact OHLC overlap records              : {plan['overlap_count']}")
    print(f"New dates beyond legacy snapshot        : {plan['new_count']}")
    print(f"OHLC mismatch records                   : 0")
    print(f"Weekend dates verified in BSE calendar  : {len(plan['weekend_dates'])}")
    for batch in plan["external_batches"]:
        print(f"  {batch['calendar_year']}: batch {batch['id']} | rows={batch['source_row_count']} | {batch['import_status']}")

    print("\nCOMPOSITE SNAPSHOT PLAN")
    print("-" * 92)
    print(f"New import batch ID                    : {plan['new_batch_id']}")
    print(f"Legacy rows copied (excluding 44 SENSEX overlaps): {plan['parent_counts']['raw'] - EXPECTED_OVERLAPS}")
    print(f"BSE SENSEX rows added                   : {EXPECTED_BSE_ROWS}")
    print(f"Expected raw rows                       : {plan['expected']['raw']}")
    print(f"Expected quality assessments            : {plan['expected']['quality']}")
    print(f"Expected daily close rows               : {plan['expected']['close']}")
    print(f"Expected full-OHLC rows                 : {plan['expected']['ohlc']}")
    print(f"Expected SENSEX close/OHLC rows         : {plan['expected_sensex']['close']} / {plan['expected_sensex']['ohlc']}")
    print("BSE SENSEX mapping after promotion      : preferred_for_period / active")
    print("BSE preferred source period             : 2025-01-01 to 2026-10-30")
    print("Source mappings for other instruments  : unchanged")
    print("Aggregates                             : not rebuilt by this script")
    print("Parent batch 2                         : unchanged")
    print("Prior aggregates                       : unchanged")

    print("\nDATA POLICY")
    print("-" * 92)
    print("All 454 BSE records are included in the new snapshot, including 44 exact overlap rows.")
    print("The 44 corresponding legacy SENSEX rows are omitted only from the new snapshot.")
    print("Legacy batch 1 and composite batch 2 remain untouched.")
    print("BSE Volume(Cr.) is not written as index traded volume; analytical volume remains unavailable.")
    print("BSE annual calendars remain incomplete; no expected session total is asserted.")
    print("No price scaling or adjustment is applied.")


def make_backup() -> tuple[Path, str]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"historical_staging_before_sensex_promotion_{stamp}.db"
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
        fk = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    require(integrity == "ok", f"Backup integrity failed: {integrity}")
    require(len(fk) == 0, f"Backup has {len(fk)} foreign-key errors.")

    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    return backup, digest


def apply_promotion(plan: dict[str, Any]) -> None:
    backup, backup_sha = make_backup()
    print(f"\nVerified database backup: {backup}")
    print(f"Backup SHA-256: {backup_sha}")

    con = sqlite3.connect(DATABASE, timeout=120)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")

        # Re-check parent and source state inside the write transaction.
        parent_status = con.execute(
            "SELECT status FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)
        ).fetchone()
        require(parent_status and parent_status["status"] == "completed", "Parent snapshot changed before apply.")
        require(con.execute(
            "SELECT COUNT(*) FROM import_batches WHERE source_path LIKE 'composite_snapshot://batch_2+BSE_external_batches_3_4%'"
        ).fetchone()[0] == 0, "SENSEX promotion appears to have already been applied.")

        parent = con.execute("SELECT * FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)).fetchone()
        batch_hash_inputs = {
            "parent_batch_id": PARENT_BATCH_ID,
            "parent_sha256": parent["source_sha256"],
            "external_batches": [
                {
                    "id": int(r["id"]),
                    "sha256": r["source_sha256"],
                    "calendar_year": int(r["calendar_year"]),
                }
                for r in plan["external_batches"]
            ],
            "policy": "replace_SENSEX_2025-01-01_to_2026-10-30_with_BSE_source",
        }
        composite_hash = hashlib.sha256(
            json.dumps(batch_hash_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source_size = int(parent["source_size_bytes"]) + sum(
            int(r["source_size_bytes"]) for r in plan["external_batches"]
        )
        source_path = (
            "composite_snapshot://batch_2+BSE_external_batches_3_4"
            "?policy=replace_SENSEX_2025_01_01_to_2026_10_30"
        )
        created_at = utc_now()
        cur = con.execute(
            """
            INSERT INTO import_batches (
                source_path, source_sha256, source_size_bytes,
                status, imported_rows, imported_at_utc
            ) VALUES (?, ?, ?, 'completed', ?, ?)
            """,
            (source_path, composite_hash, source_size, plan["expected"]["raw"], created_at),
        )
        new_batch_id = int(cur.lastrowid)
        require(new_batch_id == plan["new_batch_id"], "New batch ID differs from dry-run plan.")

        # Identify all SENSEX raw IDs in the parent snapshot for the BSE source dates.
        staged_dates = set(plan["dates"])
        parent_raw_rows = con.execute(
            "SELECT * FROM raw_daily_records WHERE import_batch_id=? ORDER BY id",
            (PARENT_BATCH_ID,),
        ).fetchall()
        replaced_old_ids: set[int] = set()
        copied_raw_map: dict[int, int] = {}
        raw_insert = """
            INSERT INTO raw_daily_records (
                import_batch_id, instrument_code, source_table,
                source_row_number, source_id, source_timestamp,
                open_raw, high_raw, low_raw, close_raw, volume_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        copied_raw = 0
        for r in parent_raw_rows:
            record_date = (r["source_timestamp"] or "")[:10]
            if r["instrument_code"] == "SENSEX" and record_date in staged_dates:
                replaced_old_ids.add(int(r["id"]))
                continue
            ins = con.execute(raw_insert, (
                new_batch_id, r["instrument_code"], r["source_table"],
                r["source_row_number"], r["source_id"], r["source_timestamp"],
                r["open_raw"], r["high_raw"], r["low_raw"], r["close_raw"], r["volume_raw"],
            ))
            copied_raw_map[int(r["id"])] = int(ins.lastrowid)
            copied_raw += 1

        require(len(replaced_old_ids) == EXPECTED_OVERLAPS,
                f"Unexpected number of replaced legacy SENSEX raw rows: {len(replaced_old_ids)}.")

        # Copy quality assessments, preserving all legacy quality decisions.
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
                """
                INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code,
                    source_table, source_timestamp, record_status,
                    close_eligible, full_ohlc_eligible, volume_eligible,
                    issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_raw_id, new_batch_id, q["instrument_code"], q["source_table"],
                 q["source_timestamp"], q["record_status"], q["close_eligible"],
                 q["full_ohlc_eligible"], q["volume_eligible"], q["issue_codes"],
                 q["assessed_at_utc"]),
            )
            copied_quality += 1

        # Copy curated close records.
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
                """
                INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close,
                    raw_record_id, source_id, source_table,
                    source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_batch_id, r["instrument_code"], r["candle_date"], r["close"],
                 new_raw_id, r["source_id"], r["source_table"],
                 r["source_quality_status"], r["issue_codes"]),
            )
            copied_close += 1

        # Copy curated full OHLC records.
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
                """
                INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date,
                    open, high, low, close, volume, volume_status,
                    source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_batch_id, r["instrument_code"], r["candle_date"],
                 r["open"], r["high"], r["low"], r["close"], r["volume"],
                 r["volume_status"], r["source_volume_raw"], new_raw_id,
                 r["source_id"], r["source_table"], r["quality_status"], r["issue_codes"]),
            )
            copied_ohlc += 1

        # Add all 454 BSE source rows and their assessments/curated rows.
        bse_raw_ids: dict[str, int] = {}
        for r in plan["staged"]:
            d = r["candle_date"]
            raw_timestamp = f"{d} 00:00:00"
            ins = con.execute(raw_insert, (
                new_batch_id, "SENSEX", BSE_SOURCE_TABLE,
                r["source_row_number"], None, raw_timestamp,
                r["open_raw"], r["high_raw"], r["low_raw"], r["close_raw"],
                None,  # BSE Volume(Cr.) is not index traded volume.
            ))
            new_raw_id = int(ins.lastrowid)
            bse_raw_ids[d] = new_raw_id

            con.execute(
                """
                INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code,
                    source_table, source_timestamp, record_status,
                    close_eligible, full_ohlc_eligible, volume_eligible,
                    issue_codes, assessed_at_utc
                ) VALUES (?, ?, 'SENSEX', ?, ?, 'accepted', 1, 1, 0, '[]', ?)
                """,
                (new_raw_id, new_batch_id, BSE_SOURCE_TABLE, raw_timestamp, created_at),
            )
            con.execute(
                """
                INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close,
                    raw_record_id, source_id, source_table,
                    source_quality_status, issue_codes
                ) VALUES (?, 'SENSEX', ?, ?, ?, NULL, ?, 'accepted', '[]')
                """,
                (new_batch_id, d, float(r["close"]), new_raw_id, BSE_SOURCE_TABLE),
            )
            con.execute(
                """
                INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date,
                    open, high, low, close, volume, volume_status,
                    source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, 'SENSEX', ?, ?, ?, ?, ?, NULL, 'unavailable', NULL,
                          ?, NULL, ?, 'accepted', '[]')
                """,
                (new_batch_id, d, float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]), new_raw_id, BSE_SOURCE_TABLE),
            )

        # Verify row counts in the new composite snapshot.
        actual = {
            "raw": table_count(con, "raw_daily_records", new_batch_id),
            "quality": table_count(con, "daily_quality_assessments", new_batch_id),
            "close": table_count(con, "daily_close_series", new_batch_id),
            "ohlc": table_count(con, "daily_ohlcv_analytical", new_batch_id),
        }
        require(actual == plan["expected"], f"New snapshot counts do not match: {actual} vs {plan['expected']}.")

        sensex_actual = {
            "close": int(con.execute(
                "SELECT COUNT(*) FROM daily_close_series WHERE import_batch_id=? AND instrument_code='SENSEX'",
                (new_batch_id,),
            ).fetchone()[0]),
            "ohlc": int(con.execute(
                "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code='SENSEX'",
                (new_batch_id,),
            ).fetchone()[0]),
        }
        require(sensex_actual == plan["expected_sensex"],
                f"SENSEX row counts do not match: {sensex_actual} vs {plan['expected_sensex']}.")

        # Verify BSE daily coverage and raw provenance.
        bse_count = con.execute(
            "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code='SENSEX' AND source_table=? AND candle_date BETWEEN ? AND ?",
            (new_batch_id, BSE_SOURCE_TABLE, START_DATE, END_DATE),
        ).fetchone()[0]
        require(bse_count == EXPECTED_BSE_ROWS, f"Expected 454 promoted BSE OHLC rows, found {bse_count}.")
        latest = con.execute(
            "SELECT MAX(candle_date) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code='SENSEX'",
            (new_batch_id,),
        ).fetchone()[0]
        require(latest == END_DATE, f"Unexpected latest SENSEX date after promotion: {latest}.")

        # Promote the BSE mapping only after records have been written and verified.
        note = (
            "BSE historical SENSEX CSV reconciled against 44 exact legacy OHLC overlaps; "
            "454 valid daily OHLC rows promoted into composite snapshot batch "
            f"{new_batch_id}. Preferred for 2025-01-01 through 2026-10-30. "
            "BSE Volume(Cr.) remains source metadata and is not index traded volume. "
            "Annual calendar coverage remains incomplete; session counts are not asserted."
        )
        con.execute(
            """
            UPDATE historical_instrument_source_mappings
            SET mapping_role='preferred_for_period',
                mapping_status='active',
                valid_from=?, valid_to=?, priority=10,
                notes=?, updated_at_utc=?
            WHERE mapping_code=?
            """,
            (START_DATE, END_DATE, note, created_at, BSE_MAPPING_CODE),
        )
        require(con.execute("SELECT changes()").fetchone()[0] == 1, "BSE source mapping was not updated.")

        # Update BSE source metadata without discarding existing provenance.
        meta = json.loads(plan["source"]["metadata_json"] or "{}")
        meta["composite_snapshot_batch_id"] = new_batch_id
        meta["external_source_batch_ids"] = list(BSE_EXTERNAL_BATCH_IDS)
        con.execute(
            "UPDATE historical_data_sources SET metadata_json=?, updated_at_utc=? WHERE source_code=?",
            (json.dumps(meta, sort_keys=True), created_at, BSE_SOURCE_CODE),
        )

        # Link all contributing sources to the new snapshot.
        links = [
            (
                f"LEGACY:IMPORT:{new_batch_id}:CONTRIBUTION",
                "LEGACY_MYSQL_DUMP_20260308", new_batch_id, None,
                "contributed_to_snapshot",
                "Legacy-source records outside the BSE SENSEX replacement window contribute to this composite snapshot.",
            ),
            (
                f"NSE:SNAPSHOT:{new_batch_id}:EXTERNAL:1",
                "NSE_INDICES_HISTORICAL_DATA", new_batch_id, 1,
                "contributed_to_snapshot",
                f"NSE BANKNIFTY 2015 external source batch 1 retained in composite snapshot {new_batch_id}.",
            ),
            (
                f"NSE:SNAPSHOT:{new_batch_id}:EXTERNAL:2",
                "NSE_INDICES_HISTORICAL_DATA", new_batch_id, 2,
                "contributed_to_snapshot",
                f"NSE BANKNIFTY 2016 external source batch 2 retained in composite snapshot {new_batch_id}.",
            ),
            (
                f"BSE:SNAPSHOT:{new_batch_id}:EXTERNAL:3",
                BSE_SOURCE_CODE, new_batch_id, 3,
                "contributed_to_snapshot",
                f"BSE SENSEX 2025 external source batch 3 contributed 249 rows to composite snapshot {new_batch_id}.",
            ),
            (
                f"BSE:SNAPSHOT:{new_batch_id}:EXTERNAL:4",
                BSE_SOURCE_CODE, new_batch_id, 4,
                "contributed_to_snapshot",
                f"BSE SENSEX 2026 external source batch 4 contributed 205 rows to composite snapshot {new_batch_id}.",
            ),
        ]
        for link in links:
            con.execute(
                """
                INSERT INTO historical_source_batch_links (
                    link_code, source_code, import_batch_id,
                    external_source_batch_id, link_role, notes, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (*link, created_at),
            )

        # Verify old snapshots and aggregates were not altered.
        require(table_count(con, "raw_daily_records", PARENT_BATCH_ID) == EXPECTED_PARENT_RAW,
                "Parent raw rows changed unexpectedly.")
        require(table_count(con, "daily_close_series", PARENT_BATCH_ID) == EXPECTED_PARENT_CLOSE,
                "Parent close rows changed unexpectedly.")
        require(table_count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID) == EXPECTED_PARENT_OHLC,
                "Parent OHLC rows changed unexpectedly.")
        aggregate_count = con.execute(
            "SELECT COUNT(*) FROM aggregated_ohlcv WHERE import_batch_id=?",
            (new_batch_id,),
        ).fetchone()[0]
        aggregate_close_count = con.execute(
            "SELECT COUNT(*) FROM aggregated_close_series WHERE import_batch_id=?",
            (new_batch_id,),
        ).fetchone()[0]
        require(aggregate_count == 0 and aggregate_close_count == 0,
                "New snapshot unexpectedly has aggregate rows before rebuild.")

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        require(integrity == "ok", f"SQLite integrity check failed: {integrity}")
        require(len(fk_errors) == 0, f"Foreign-key errors found: {len(fk_errors)}")

        con.commit()

        print("\nSENSEX BSE PROMOTION COMMITTED")
        print("=" * 92)
        print(f"New composite import_batch_id : {new_batch_id}")
        print(f"New raw rows                  : {actual['raw']}")
        print(f"New quality assessments       : {actual['quality']}")
        print(f"New daily close rows          : {actual['close']}")
        print(f"New full-OHLC rows            : {actual['ohlc']}")
        print(f"SENSEX daily close/OHLC       : {sensex_actual['close']} / {sensex_actual['ohlc']}")
        print(f"BSE SENSEX rows promoted      : {bse_count}")
        print("BSE mapping                  : preferred_for_period / active")
        print("Parent batch 2                : preserved unchanged")
        print("Aggregates                    : not rebuilt; run aggregation builder next")
        print(f"SQLite integrity              : {integrity}")
        print(f"Foreign-key errors            : {len(fk_errors)}")
        print(f"Verified backup               : {backup}")

    except Exception:
        con.rollback()
        print("\nPROMOTION FAILED — transaction rolled back.", file=sys.stderr)
        print(f"Verified backup remains at: {backup}", file=sys.stderr)
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply promotion; default is read-only dry run.")
    args = parser.parse_args()

    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    con = connect_readonly(DATABASE)
    try:
        plan = collect_plan(con)
        print_plan(plan, "APPLY" if args.apply else "DRY RUN (read-only)")
    finally:
        con.close()

    if not args.apply:
        print("\nDry run completed. No database changes were made.")
        print("Review the plan, then rerun with --apply to promote SENSEX.")
        return 0

    apply_promotion(plan)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
