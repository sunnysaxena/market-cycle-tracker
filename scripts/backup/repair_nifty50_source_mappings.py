#!/usr/bin/env python3
"""Repair year-specific NSE NIFTY50 source mappings in the local staging DB.

Default mode is read-only. Pass --apply to create a SQLite backup and perform
only the mapping-table correction. No price, quality, or aggregate rows change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
INSTRUMENT = "NIFTY50"
TIMEFRAME = "1D"
PARENT_MAPPING_CODE = "NSE:NIFTY50:nse_indices_historical_2025_to_2026:1D"
YEAR_MAPPINGS = (
    {
        "mapping_code": "NSE:NIFTY50:nse_indices_historical_2025:1D",
        "source_table": "nse_indices_historical_2025",
        "valid_from": "2025-01-01",
        "valid_to": "2025-12-31",
        "expected_rows": 249,
        "expected_min": "2025-01-01",
        "expected_max": "2025-12-31",
        "external_batch_id": 5,
        "filename": "nifty50_nse_2025.csv",
    },
    {
        "mapping_code": "NSE:NIFTY50:nse_indices_historical_2026:1D",
        "source_table": "nse_indices_historical_2026",
        "valid_from": "2026-01-01",
        "valid_to": "2026-10-30",
        "expected_rows": 205,
        "expected_min": "2026-01-01",
        "expected_max": "2026-10-30",
        "external_batch_id": 6,
        "filename": "nifty50_nse_2026.csv",
    },
)


def connect_readonly() -> sqlite3.Connection:
    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_plan(conn: sqlite3.Connection) -> tuple[sqlite3.Row, list[dict]]:
    required = {
        "raw_daily_records",
        "historical_data_sources",
        "historical_instrument_source_mappings",
    }
    present = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(f"Required tables missing: {missing}")

    source = conn.execute(
        "SELECT source_code FROM historical_data_sources WHERE source_code=?",
        (SOURCE_CODE,),
    ).fetchone()
    if not source:
        raise RuntimeError(f"Source registry row not found: {SOURCE_CODE}")

    parent_rows = conn.execute(
        """SELECT * FROM historical_instrument_source_mappings
           WHERE mapping_code=?""",
        (PARENT_MAPPING_CODE,),
    ).fetchall()
    if len(parent_rows) != 1:
        raise RuntimeError(
            f"Expected exactly one combined NSE mapping {PARENT_MAPPING_CODE}; "
            f"found {len(parent_rows)}"
        )
    parent = parent_rows[0]
    if (parent["source_code"] != SOURCE_CODE
            or parent["instrument_code"] != INSTRUMENT
            or parent["timeframe"] != TIMEFRAME
            or parent["mapping_role"] != "preferred_for_period"
            or parent["mapping_status"] != "active"
            or parent["valid_from"] != "2025-01-01"
            or parent["valid_to"] != "2026-10-30"):
        raise RuntimeError("Existing combined mapping does not match expected state; refusing to modify it")

    prepared = []
    for item in YEAR_MAPPINGS:
        stats = conn.execute(
            """SELECT COUNT(*) AS n,
                      COUNT(DISTINCT DATE(source_timestamp)) AS unique_dates,
                      MIN(DATE(source_timestamp)) AS first_date,
                      MAX(DATE(source_timestamp)) AS last_date
               FROM raw_daily_records
               WHERE import_batch_id=4 AND instrument_code=? AND source_table=?""",
            (INSTRUMENT, item["source_table"]),
        ).fetchone()
        if (stats["n"] != item["expected_rows"]
                or stats["unique_dates"] != item["expected_rows"]
                or stats["first_date"] != item["expected_min"]
                or stats["last_date"] != item["expected_max"]):
            raise RuntimeError(
                f"Raw provenance validation failed for {item['source_table']}: {dict(stats)}"
            )

        conflicts = conn.execute(
            """SELECT mapping_id, mapping_code, source_table, valid_from, valid_to
               FROM historical_instrument_source_mappings
               WHERE source_code=? AND instrument_code=? AND timeframe=?
                 AND source_table=? AND mapping_status='active'""",
            (SOURCE_CODE, INSTRUMENT, TIMEFRAME, item["source_table"]),
        ).fetchall()
        if conflicts:
            raise RuntimeError(
                f"An active mapping already exists for {item['source_table']}: "
                f"{[dict(x) for x in conflicts]}"
            )
        code_conflicts = conn.execute(
            "SELECT mapping_id FROM historical_instrument_source_mappings WHERE mapping_code=?",
            (item["mapping_code"],),
        ).fetchall()
        if code_conflicts:
            raise RuntimeError(f"Mapping code already exists: {item['mapping_code']}")
        prepared.append({**item, "stats": dict(stats)})

    return parent, prepared


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_database() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"historical_staging_before_nifty50_mapping_repair_{stamp}.db"
    source = sqlite3.connect(str(DB_PATH))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        destination.close()
        source.close()
    return target


def apply_changes(parent_id: int, prepared: list[dict]) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT * FROM historical_instrument_source_mappings WHERE mapping_id=?",
            (parent_id,),
        ).fetchone()
        if not current or current["mapping_code"] != PARENT_MAPPING_CODE:
            raise RuntimeError("Combined mapping changed after preflight; transaction aborted")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        first = prepared[0]
        first_metadata = {
            "composite_snapshot_batch_id": 4,
            "external_source_batch_ids": [first["external_batch_id"]],
            "source_filenames": [first["filename"]],
            "date_ranges": {"2025": [first["valid_from"], first["valid_to"]]},
        }
        conn.execute(
            """UPDATE historical_instrument_source_mappings
               SET mapping_code=?, source_table=?, valid_from=?, valid_to=?,
                   notes=?, metadata_json=?, updated_at_utc=?
               WHERE mapping_id=?""",
            (
                first["mapping_code"], first["source_table"],
                first["valid_from"], first["valid_to"],
                "NSE Indices NIFTY 50 daily OHLC source; 249 validated 2025 records "
                "promoted into composite snapshot batch 4. Preferred for 2025-01-01 "
                "through 2025-12-31. No volume field was supplied by the source.",
                json.dumps(first_metadata, sort_keys=True), now, parent_id,
            ),
        )

        second = prepared[1]
        second_metadata = {
            "composite_snapshot_batch_id": 4,
            "external_source_batch_ids": [second["external_batch_id"]],
            "source_filenames": [second["filename"]],
            "date_ranges": {"2026": [second["valid_from"], second["valid_to"]]},
        }
        conn.execute(
            """INSERT INTO historical_instrument_source_mappings (
                   mapping_code, source_code, instrument_code, source_symbol,
                   source_table, timeframe, mapping_role, valid_from, valid_to,
                   priority, mapping_status, notes, metadata_json,
                   created_at_utc, updated_at_utc
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                second["mapping_code"], SOURCE_CODE, INSTRUMENT, "NIFTY 50",
                second["source_table"], TIMEFRAME, "preferred_for_period",
                second["valid_from"], second["valid_to"], 10, "active",
                "NSE Indices NIFTY 50 daily OHLC source; 205 validated 2026 records "
                "promoted into composite snapshot batch 4. Preferred for 2026-01-01 "
                "through 2026-10-30. No volume field was supplied by the source.",
                json.dumps(second_metadata, sort_keys=True), now, now,
            ),
        )

        # Validate the two active mapping rows before commit.
        for item in prepared:
            row = conn.execute(
                """SELECT COUNT(*) FROM historical_instrument_source_mappings
                   WHERE source_code=? AND instrument_code=? AND timeframe=?
                     AND source_table=? AND valid_from=? AND valid_to=?
                     AND mapping_role='preferred_for_period' AND mapping_status='active'""",
                (SOURCE_CODE, INSTRUMENT, TIMEFRAME, item["source_table"],
                 item["valid_from"], item["valid_to"]),
            ).fetchone()[0]
            if row != 1:
                raise RuntimeError(f"Post-update mapping validation failed for {item['source_table']}")

        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Post-commit database check failed: integrity={integrity}, fk={len(fk_errors)}")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up DB and apply mapping-only correction")
    args = parser.parse_args()

    print("NIFTY50 YEAR-SPECIFIC SOURCE MAPPING REPAIR")
    print("=" * 86)
    print(f"Database: {DB_PATH}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN (read-only)'}")
    print("Scope: historical_instrument_source_mappings only")
    print("Daily prices, quality assessments, aggregates and source batches: unchanged")

    if not DB_PATH.exists():
        print(f"ERROR: database not found: {DB_PATH}", file=sys.stderr)
        return 2

    try:
        with connect_readonly() as conn:
            parent, prepared = get_plan(conn)
        print("\nCURRENT COMBINED MAPPING")
        print(f"mapping_id={parent['mapping_id']} | {parent['mapping_code']}")
        print(f"current source_table={parent['source_table']} | period={parent['valid_from']}..{parent['valid_to']}")
        print("\nPROPOSED YEAR-SPECIFIC MAPPINGS")
        for item in prepared:
            print(
                f"{item['valid_from']}..{item['valid_to']} | "
                f"{item['source_table']} | rows={item['stats']['n']} | "
                f"mapping_code={item['mapping_code']}"
            )
        print("\nValidation: both raw source tables, row counts, unique dates, date ranges, "
              "source registry and mapping-code uniqueness passed.")

        if not args.apply:
            print("\nDRY RUN PASSED — no database changes or backup were made.")
            print("Review the plan, then rerun with --apply to repair the mapping only.")
            return 0

        backup = backup_database()
        print(f"\nVerified database backup: {backup}")
        print(f"Backup SHA-256: {sha256(backup)}")
        apply_changes(parent["mapping_id"], prepared)
        print("\nNIFTY50 SOURCE MAPPING REPAIR COMMITTED")
        print("=" * 86)
        print("Updated combined mapping into the 2025 table-specific mapping.")
        print("Inserted the 2026 table-specific mapping.")
        print("Daily price / quality / aggregate / batch rows: unchanged")
        print("SQLite integrity: ok")
        print("Foreign-key errors: 0")
        print(f"Verified backup: {backup}")
        return 0
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
