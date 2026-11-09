#!/usr/bin/env python3
"""Read-only preflight for promoting staged NSE NIFTY 50 history.

Run from the project root:
    python scripts\\preview_promote_nifty50_nse_snapshot.py

This script ONLY inspects the database. It does not create a backup, update
source mappings, insert a new import batch, or modify historical/aggregate data.
Promotion will be implemented as a separate, reviewed step after this preflight.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
PARENT_BATCH_ID = 3
EXTERNAL_BATCH_IDS = (5, 6)
INSTRUMENT = "NIFTY50"
INDEX_NAME = "NIFTY 50"
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
MAPPING_CODE = "NSE:NIFTY50:nse_indices_historical_2025_to_2026:1D"
SOURCE_TABLE = "nse_indices_historical_2025_to_2026"
START_DATE = "2025-01-01"
END_DATE = "2026-10-30"
TOLERANCE = 0.02
EXPECTED = {
    2025: {
        "batch_id": 5,
        "filename": "nifty50_nse_2025.csv",
        "sha256": "ce1faf932060e5edde6615044e18c4754e8de73285e2ca412f2b22c9415f65d1",
        "rows": 249,
        "overlaps": 44,
        "new": 205,
        "start": "2025-01-01",
        "end": "2025-12-31",
    },
    2026: {
        "batch_id": 6,
        "filename": "nifty50_nse_2026.csv",
        "sha256": "b2a6d13df4c5168aa110fef27dde05b184692e2a8137a4da20075aad36fcea90",
        "rows": 205,
        "overlaps": 0,
        "new": 205,
        "start": "2026-01-01",
        "end": "2026-10-30",
    },
}
EXPECTED_PARENT = {"raw": 20559, "quality": 20559, "close": 20505, "ohlc": 20385}
EXPECTED_PARENT_NIFTY = {"raw": 3728, "close": 3728, "ohlc": 3728}
EXPECTED_NEXT = {"raw": 20969, "quality": 20969, "close": 20915, "ohlc": 20795}
EXPECTED_NEXT_NIFTY = {"close": 4138, "ohlc": 4138}
COMPOSITE_PATH = (
    "composite_snapshot://batch_3+NSE_NIFTY50_external_batches_5_6"
    "?policy=replace_NIFTY50_2025_01_01_to_2026_10_30"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def count(con: sqlite3.Connection, table: str, batch_id: int) -> int:
    return int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=?", (batch_id,)
    ).fetchone()[0])


def instrument_count(con: sqlite3.Connection, table: str, batch_id: int) -> int:
    return int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=? AND instrument_code=?",
        (batch_id, INSTRUMENT),
    ).fetchone()[0])


def main() -> int:
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    con = connect_readonly(DATABASE)
    try:
        print("NIFTY 50 NSE COMPOSITE SNAPSHOT PROMOTION PREFLIGHT")
        print("=" * 94)
        print(f"Database: {DATABASE}")
        print(f"Parent snapshot: batch {PARENT_BATCH_ID}")
        print(f"External source batches: {EXTERNAL_BATCH_IDS}")
        print("Mode: READ-ONLY; no database changes or backup will be made")

        required_tables = (
            "import_batches", "raw_daily_records", "daily_quality_assessments",
            "daily_close_series", "daily_ohlcv_analytical", "aggregated_ohlcv",
            "aggregated_close_series", "historical_data_sources",
            "historical_instrument_source_mappings", "historical_source_batch_links",
            "external_index_source_batches", "external_index_daily_records",
            "exchange_calendar_events",
        )
        missing = [name for name in required_tables if not exists(con, name)]
        require(not missing, f"Required tables missing: {missing}")
        print(f"[PASS] Required tables exist ({len(required_tables)})")

        parent = con.execute(
            "SELECT * FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)
        ).fetchone()
        require(parent is not None and parent["status"] == "completed",
                "Parent snapshot batch 3 is missing or not completed.")
        completed = [int(r[0]) for r in con.execute(
            "SELECT id FROM import_batches WHERE status='completed' ORDER BY id"
        ).fetchall()]
        require(completed and completed[-1] == PARENT_BATCH_ID,
                f"Batch 3 is not the latest completed snapshot: {completed}")
        print(f"[PASS] Parent snapshot batch 3 is latest completed snapshot ({completed})")

        parent_counts = {
            "raw": count(con, "raw_daily_records", PARENT_BATCH_ID),
            "quality": count(con, "daily_quality_assessments", PARENT_BATCH_ID),
            "close": count(con, "daily_close_series", PARENT_BATCH_ID),
            "ohlc": count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID),
        }
        require(parent_counts == EXPECTED_PARENT,
                f"Unexpected parent snapshot counts: {parent_counts}; expected {EXPECTED_PARENT}")
        print(f"[PASS] Parent batch 3 counts match baseline: {parent_counts}")

        mapping = con.execute(
            "SELECT * FROM historical_instrument_source_mappings WHERE mapping_code=?",
            (MAPPING_CODE,),
        ).fetchone()
        require(mapping is not None, "NIFTY50 NSE source mapping is missing.")
        require(mapping["source_code"] == SOURCE_CODE and mapping["instrument_code"] == INSTRUMENT,
                "NIFTY50 mapping source/instrument identity is unexpected.")
        require(mapping["source_table"] == SOURCE_TABLE and mapping["timeframe"] == "1D",
                "NIFTY50 mapping table/timeframe is unexpected.")
        require(mapping["mapping_status"] == "pending_review" and mapping["mapping_role"] == "pending_review",
                "NIFTY50 mapping is not pending_review; stop and review current state.")
        mapping_meta = json.loads(mapping["metadata_json"] or "{}")
        mapped_ids = sorted(int(x) for x in mapping_meta.get("external_source_batch_ids", []))
        require(mapped_ids == [5, 6], f"Mapping metadata batch IDs are {mapped_ids}, not [5, 6].")
        print("[PASS] NSE NIFTY50 mapping exists and is pending_review for batches 5 and 6")

        source = con.execute(
            "SELECT * FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)
        ).fetchone()
        require(source is not None and source["source_type"] == "official_exchange_portal",
                "NSE official source registry row is missing or has unexpected type.")
        print("[PASS] NSE official exchange source registry row exists")

        staged_all: list[sqlite3.Row] = []
        for year, exp in EXPECTED.items():
            print(f"\nYEAR {year}")
            print("-" * 94)
            batches = con.execute(
                """SELECT * FROM external_index_source_batches
                   WHERE id=? AND instrument_code=? AND calendar_year=? AND source_filename=?""",
                (exp["batch_id"], INSTRUMENT, year, exp["filename"]),
            ).fetchall()
            require(len(batches) == 1, f"Expected exactly one external batch {exp['batch_id']} for {year}.")
            batch = batches[0]
            require(batch["source_provider"] == "NSE Indices historical-data report",
                    f"Unexpected provider in batch {exp['batch_id']}.")
            require(batch["source_sha256"] == exp["sha256"],
                    f"File hash mismatch in batch {exp['batch_id']}.")
            require(batch["source_row_count"] == exp["rows"] and batch["unique_date_count"] == exp["rows"],
                    f"Source batch {exp['batch_id']} row counts are unexpected.")
            require(batch["import_status"] == "staged_validated_calendar_incomplete",
                    f"Source batch {exp['batch_id']} has unexpected status {batch['import_status']}.")
            require(batch["expected_session_count"] == 0,
                    f"Source batch {exp['batch_id']} unexpectedly asserts annual sessions.")

            rows = con.execute(
                "SELECT * FROM external_index_daily_records WHERE batch_id=? ORDER BY candle_date",
                (exp["batch_id"],),
            ).fetchall()
            require(len(rows) == exp["rows"],
                    f"Batch {exp['batch_id']} staged {len(rows)} rows, expected {exp['rows']}.")
            dates = [r["candle_date"] for r in rows]
            require(len(set(dates)) == len(dates), f"Duplicate staged dates in {year}.")
            require(min(dates) == exp["start"] and max(dates) == exp["end"],
                    f"Unexpected {year} date range {min(dates)}..{max(dates)}.")
            overlap_rows = 0
            for r in rows:
                require(r["instrument_code"] == INSTRUMENT and r["source_index_name"] == INDEX_NAME,
                        f"Instrument identity mismatch on {r['candle_date']}.")
                vals = [float(r[k]) for k in ("open", "high", "low", "close")]
                o, h, l, c = vals
                require(all(v > 0 for v in vals) and h >= max(o, l, c) and l <= min(o, h, c),
                        f"Invalid OHLC geometry on {r['candle_date']}.")
                require(r["quality_status"] == "valid_ohlc", f"Invalid quality status on {r['candle_date']}.")
                issues = json.loads(r["issue_codes"] or "[]")
                require(not issues, f"Staged issue codes found on {r['candle_date']}: {issues}.")
                if r["overlap_status"] != "no_legacy_daily_record":
                    overlap_rows += 1
                if r["overlap_status"] in ("ohlc_mismatch_review", "close_mismatch_review"):
                    raise RuntimeError(f"Overlap mismatch review status on {r['candle_date']}.")
                if r["overlap_status"] == "ohlc_match_within_0_02":
                    for field in ("open", "high", "low", "close"):
                        require(r[f"legacy_{field}"] is not None,
                                f"Missing stored legacy {field} on overlap {r['candle_date']}.")
                        require(abs(float(r[field]) - float(r[f"legacy_{field}"])) <= TOLERANCE,
                                f"Overlap {field} mismatch on {r['candle_date']}.")
                staged_all.append(r)
            require(overlap_rows == exp["overlaps"],
                    f"{year} overlap count {overlap_rows}, expected {exp['overlaps']}.")
            link_count = con.execute(
                """SELECT COUNT(*) FROM historical_source_batch_links
                   WHERE source_code=? AND external_source_batch_id=? AND link_role='staged_external_file'""",
                (SOURCE_CODE, exp["batch_id"]),
            ).fetchone()[0]
            require(link_count == 1, f"Expected one staged source link for external batch {exp['batch_id']}.")
            print(f"[PASS] Batch {exp['batch_id']} | rows={len(rows)} | overlaps={overlap_rows} | new={len(rows)-overlap_rows} | hash/status verified")

        all_dates = [r["candle_date"] for r in staged_all]
        require(len(all_dates) == 454 and len(set(all_dates)) == 454,
                "Combined staged records are not 454 unique dates.")
        require(min(all_dates) == START_DATE and max(all_dates) == END_DATE,
                "Combined staged date window is unexpected.")
        overlap_rows = [r for r in staged_all if r["overlap_status"] != "no_legacy_daily_record"]
        new_rows = [r for r in staged_all if r["overlap_status"] == "no_legacy_daily_record"]
        require(len(overlap_rows) == 44 and len(new_rows) == 410,
                f"Unexpected combined overlap/new counts: {len(overlap_rows)}/{len(new_rows)}.")
        print("\nCANONICAL OVERLAP AND REPLACEMENT CHECKS")
        print("-" * 94)

        overlap_dates = sorted(r["candle_date"] for r in overlap_rows)
        require(len(set(overlap_dates)) == 44, "Overlap dates are not unique.")
        for d in overlap_dates:
            parent_ohlc = con.execute(
                """SELECT open, high, low, close FROM daily_ohlcv_analytical
                   WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                (PARENT_BATCH_ID, INSTRUMENT, d),
            ).fetchall()
            require(len(parent_ohlc) == 1, f"Expected one parent OHLC row on overlap date {d}; found {len(parent_ohlc)}.")
            staged = next(r for r in overlap_rows if r["candle_date"] == d)
            for i, field in enumerate(("open", "high", "low", "close")):
                require(abs(float(staged[field]) - float(parent_ohlc[0][i])) <= TOLERANCE,
                        f"Direct canonical overlap mismatch on {d} ({field}).")
            parent_close = con.execute(
                """SELECT close FROM daily_close_series
                   WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                (PARENT_BATCH_ID, INSTRUMENT, d),
            ).fetchall()
            require(len(parent_close) == 1, f"Expected one parent close row on {d}; found {len(parent_close)}.")
            require(abs(float(staged["close"]) - float(parent_close[0][0])) <= TOLERANCE,
                    f"Direct canonical close mismatch on {d}.")
            raw_n = con.execute(
                """SELECT COUNT(*) FROM raw_daily_records
                   WHERE import_batch_id=? AND instrument_code=? AND date(source_timestamp)=?""",
                (PARENT_BATCH_ID, INSTRUMENT, d),
            ).fetchone()[0]
            require(raw_n == 1, f"Expected one parent raw NIFTY50 record on {d}; found {raw_n}.")
        print("[PASS] All 44 overlapping dates have one matching parent raw/close/OHLC record")

        parent_instrument = {
            "raw": int(con.execute(
                "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=?",
                (PARENT_BATCH_ID, INSTRUMENT),
            ).fetchone()[0]),
            "close": instrument_count(con, "daily_close_series", PARENT_BATCH_ID),
            "ohlc": instrument_count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID),
        }
        require(parent_instrument == EXPECTED_PARENT_NIFTY,
                f"Unexpected parent NIFTY50 counts: {parent_instrument}.")
        print(f"[PASS] Parent NIFTY50 counts match baseline: {parent_instrument}")

        # Ensure all Saturday/Sunday rows are registered NSE equity special sessions.
        weekend_dates = sorted({d for d in all_dates if date.fromisoformat(d).weekday() >= 5})
        if weekend_dates:
            marks = ",".join("?" for _ in weekend_dates)
            registered = {r[0] for r in con.execute(
                f"""SELECT session_date FROM exchange_calendar_events
                    WHERE exchange='NSE' AND market_segment='EQUITY'
                      AND event_type='special_session_open' AND session_date IN ({marks})""",
                tuple(weekend_dates),
            ).fetchall()}
            require(registered == set(weekend_dates),
                    f"Weekend sessions differ: staged={weekend_dates}, registered={sorted(registered)}.")
        holidays = con.execute(
            """SELECT session_date FROM exchange_calendar_events
               WHERE exchange='NSE' AND market_segment='EQUITY' AND event_type='holiday_closed'
                 AND session_date BETWEEN ? AND ?""",
            (START_DATE, END_DATE),
        ).fetchall()
        holiday_set = {r[0] for r in holidays}
        unexpected_holidays = sorted(set(all_dates) & holiday_set)
        require(not unexpected_holidays, f"Staged NIFTY50 rows fall on NSE holidays: {unexpected_holidays}.")
        print(f"[PASS] Weekend sessions registered: {weekend_dates}")
        print("[PASS] No staged rows fall on registered NSE holiday dates")

        # No existing composite snapshot from this exact policy may already exist.
        already = con.execute(
            "SELECT id FROM import_batches WHERE source_path=?", (COMPOSITE_PATH,)
        ).fetchone()
        if already is not None:
            raise RuntimeError(
                f"NIFTY50 composite snapshot was already created as batch {already['id']}."
            )
        next_batch_id = int(con.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM import_batches"
        ).fetchone()[0])
        require(next_batch_id == 4,
                f"Expected next import batch ID 4, found {next_batch_id}; inspect new import batches first.")
        print(f"[PASS] Promotion has not already run; next import batch ID is {next_batch_id}")

        expected_next = {
            "raw": parent_counts["raw"] - len(overlap_rows) + len(staged_all),
            "quality": parent_counts["quality"] - len(overlap_rows) + len(staged_all),
            "close": parent_counts["close"] - len(overlap_rows) + len(staged_all),
            "ohlc": parent_counts["ohlc"] - len(overlap_rows) + len(staged_all),
        }
        require(expected_next == EXPECTED_NEXT,
                f"Expected composite row counts differ: {expected_next}.")
        expected_nifty = {
            "close": parent_instrument["close"] - len(overlap_rows) + len(staged_all),
            "ohlc": parent_instrument["ohlc"] - len(overlap_rows) + len(staged_all),
        }
        require(expected_nifty == EXPECTED_NEXT_NIFTY,
                f"Expected NIFTY50 rows differ: {expected_nifty}.")

        # Source contribution links expected in the new snapshot. Refuse collisions.
        link_codes = [
            f"LEGACY:IMPORT:4:CONTRIBUTION",
            f"NSE:SNAPSHOT:4:EXTERNAL:1",
            f"NSE:SNAPSHOT:4:EXTERNAL:2",
            f"BSE:SNAPSHOT:4:EXTERNAL:3",
            f"BSE:SNAPSHOT:4:EXTERNAL:4",
            f"NSE:SNAPSHOT:4:EXTERNAL:5",
            f"NSE:SNAPSHOT:4:EXTERNAL:6",
        ]
        if exists(con, "historical_source_batch_links"):
            marks = ",".join("?" for _ in link_codes)
            collisions = con.execute(
                f"SELECT link_code FROM historical_source_batch_links WHERE link_code IN ({marks})",
                tuple(link_codes),
            ).fetchall()
            require(not collisions, f"Future snapshot contribution link codes already exist: {[r[0] for r in collisions]}.")

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        require(integrity == "ok", f"SQLite integrity check failed: {integrity}.")
        require(not fk_errors, f"SQLite foreign-key errors: {len(fk_errors)}.")
        print("[PASS] SQLite integrity check and foreign-key check")

        print("\nPROPOSED COMPOSITE SNAPSHOT")
        print("-" * 94)
        print(f"New import batch ID                 : {next_batch_id}")
        print(f"Parent batch preserved              : {PARENT_BATCH_ID}")
        print(f"NIFTY50 replacement window          : {START_DATE} to {END_DATE}")
        print(f"NIFTY50 NSE rows to add              : {len(staged_all)}")
        print(f"Legacy NIFTY50 rows omitted in new snapshot: {len(overlap_rows)}")
        print(f"New dates beyond parent snapshot    : {len(new_rows)}")
        print(f"Expected raw rows                   : {expected_next['raw']}")
        print(f"Expected quality assessments        : {expected_next['quality']}")
        print(f"Expected daily close rows            : {expected_next['close']}")
        print(f"Expected full-OHLC rows              : {expected_next['ohlc']}")
        print(f"Expected NIFTY50 daily close/OHLC    : {expected_nifty['close']} / {expected_nifty['ohlc']}")
        print("NSE NIFTY50 mapping after promotion : preferred_for_period / active")
        print("NSE preferred period                : 2025-01-01 to 2026-10-30")
        print("Existing BANKNIFTY/SENSEX mappings  : unchanged")
        print("Other instrument source mappings    : unchanged")
        print("Aggregates                          : not copied/rebuilt for new batch by this step")
        print("Data volume                         : unavailable; no source volume field imported")
        print("Parent batch 3 and its aggregates   : unchanged")
        print("Earlier snapshots 1 and 2           : unchanged")

        print("\nSOURCE CONTRIBUTION PLAN")
        print("-" * 94)
        print("Batch 3 legacy snapshot contribution")
        print("NSE external batches 1 and 2 (BANKNIFTY historical slices)")
        print("BSE external batches 3 and 4 (SENSEX historical slices)")
        print("NSE external batches 5 and 6 (NIFTY50 2025 and 2026 slices)")

        print("\nFINAL RESULT")
        print("=" * 94)
        print("PROMOTION PREFLIGHT PASSED — no database changes were made.")
        print("Next step: review this plan, then prepare/run a separate promotion apply script.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nPREFLIGHT FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
