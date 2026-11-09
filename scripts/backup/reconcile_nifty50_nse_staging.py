#!/usr/bin/env python3
"""Read-only reconciliation of staged NSE NIFTY 50 CSV batches 5 and 6.

Run from the project root:
    python scripts\\reconcile_nifty50_nse_staging.py

This script does not modify the database. It verifies the staged source-batch
metadata and records, compares overlapping candles with canonical snapshot
batch 3, checks the NSE weekend-session calendar, and validates DB integrity.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "historical_staging.db"
SNAPSHOT_BATCH = 3
INSTRUMENT = "NIFTY50"
INDEX_NAME = "NIFTY 50"
EXPECTED = {
    2025: {
        "batch_id": 5,
        "filename": "nifty50_nse_2025.csv",
        "sha256": "ce1faf932060e5edde6615044e18c4754e8de73285e2ca412f2b22c9415f65d1",
        "rows": 249,
        "overlaps": 44,
        "new_dates": 205,
        "start": "2025-01-01",
        "end": "2025-12-31",
    },
    2026: {
        "batch_id": 6,
        "filename": "nifty50_nse_2026.csv",
        "sha256": "b2a6d13df4c5168aa110fef27dde05b184692e2a8137a4da20075aad36fcea90",
        "rows": 205,
        "overlaps": 0,
        "new_dates": 205,
        "start": "2026-01-01",
        "end": "2026-10-30",
    },
}
TOLERANCE = 0.02


class Audit:
    def __init__(self) -> None:
        self.checks = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        self.checks += 1
        if condition:
            print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))
        else:
            message = f"{label}" + (f" — {detail}" if detail else "")
            self.errors.append(message)
            print(f"[FAIL] {message}")

    def warn(self, label: str, detail: str) -> None:
        self.warnings.append(f"{label} — {detail}")
        print(f"[REVIEW] {label} — {detail}")


def one(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = con.execute(sql, params).fetchone()
    return row[0] if row else None


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return one(
        con,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ) == 1


def run_audit(db_path: Path) -> int:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")

    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    audit = Audit()
    try:
        print("NIFTY 50 NSE STAGING RECONCILIATION (READ-ONLY)")
        print("=" * 88)
        print(f"Database: {db_path}")
        print(f"Canonical snapshot: batch {SNAPSHOT_BATCH}")
        print("Mode: READ-ONLY; no database changes will be made")

        required = (
            "external_index_source_batches",
            "external_index_daily_records",
            "historical_instrument_source_mappings",
            "historical_source_batch_links",
            "daily_ohlcv_analytical",
            "daily_close_series",
            "exchange_calendar_events",
        )
        missing = [name for name in required if not table_exists(con, name)]
        audit.check("Required staging and canonical tables exist", not missing,
                    f"missing={missing}" if missing else "all 7 tables found")
        if missing:
            return 1

        mapping_code = "NSE:NIFTY50:nse_indices_historical_2025_to_2026:1D"
        mapping = con.execute(
            """SELECT mapping_status, mapping_role, source_code, instrument_code,
                      valid_from, valid_to, metadata_json
               FROM historical_instrument_source_mappings WHERE mapping_code=?""",
            (mapping_code,),
        ).fetchone()
        audit.check("NIFTY50 source mapping exists", mapping is not None)
        if mapping is None:
            return 1
        audit.check(
            "Source mapping remains pending review",
            mapping["mapping_status"] == "pending_review" and mapping["mapping_role"] == "pending_review",
            f"status={mapping['mapping_status']}; role={mapping['mapping_role']}",
        )
        audit.check(
            "Source mapping identifies NSE / NIFTY50",
            mapping["source_code"] == "NSE_INDICES_HISTORICAL_DATA" and mapping["instrument_code"] == INSTRUMENT,
            f"source={mapping['source_code']}; instrument={mapping['instrument_code']}",
        )
        try:
            mapping_metadata = json.loads(mapping["metadata_json"] or "{}")
            metadata_ids = sorted(int(x) for x in mapping_metadata.get("external_source_batch_ids", []))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata_ids = []
        audit.check("Mapping metadata references batches 5 and 6", metadata_ids == [5, 6],
                    f"metadata batch IDs={metadata_ids}")

        combined = {"rows": 0, "overlaps": 0, "new": 0, "mismatches": 0}
        staged_dates_by_year: dict[int, list[str]] = {}
        staged_weekend_dates: set[str] = set()

        for year, exp in EXPECTED.items():
            print(f"\nYEAR {year}")
            print("-" * 88)
            batches = con.execute(
                """SELECT id, source_sha256, source_row_count, unique_date_count,
                          import_status, calendar_year, instrument_code, source_filename,
                          expected_session_count
                   FROM external_index_source_batches
                   WHERE instrument_code=? AND calendar_year=? AND source_filename=?
                   ORDER BY id""",
                (INSTRUMENT, year, exp["filename"]),
            ).fetchall()
            audit.check(f"{year} source batch is uniquely registered", len(batches) == 1,
                        f"matching metadata rows={len(batches)}")
            if len(batches) != 1:
                continue
            batch = batches[0]
            audit.check(f"{year} external batch ID is {exp['batch_id']}", batch["id"] == exp["batch_id"],
                        f"actual ID={batch['id']}")
            audit.check(f"{year} file SHA-256 matches validated file", batch["source_sha256"] == exp["sha256"])
            audit.check(f"{year} source batch metadata is correct",
                        batch["calendar_year"] == year and batch["instrument_code"] == INSTRUMENT
                        and batch["source_filename"] == exp["filename"])
            audit.check(f"{year} source batch row counts match",
                        batch["source_row_count"] == exp["rows"]
                        and batch["unique_date_count"] == exp["rows"],
                        f"source_rows={batch['source_row_count']}; unique_dates={batch['unique_date_count']}")
            audit.check(f"{year} staged status is calendar-incomplete",
                        batch["import_status"] == "staged_validated_calendar_incomplete",
                        f"status={batch['import_status']}")
            audit.check(f"{year} expected session count is not asserted",
                        batch["expected_session_count"] == 0,
                        f"value={batch['expected_session_count']}")

            rows = con.execute(
                """SELECT candle_date, instrument_code, source_index_name,
                          open, high, low, close, overlap_status, quality_status, issue_codes
                   FROM external_index_daily_records WHERE batch_id=?
                   ORDER BY candle_date""",
                (exp["batch_id"],),
            ).fetchall()
            dates = [r["candle_date"] for r in rows]
            staged_dates_by_year[year] = dates
            combined["rows"] += len(rows)
            audit.check(f"{year} staged record count is {exp['rows']}", len(rows) == exp["rows"],
                        f"actual={len(rows)}")
            audit.check(f"{year} dates are unique", len(dates) == len(set(dates)))
            audit.check(f"{year} date range is correct",
                        bool(dates) and min(dates) == exp["start"] and max(dates) == exp["end"],
                        f"actual={min(dates) if dates else None} .. {max(dates) if dates else None}")
            audit.check(f"{year} all records identify NIFTY50",
                        all(r["instrument_code"] == INSTRUMENT and r["source_index_name"] == INDEX_NAME for r in rows))

            bad_ohlc = []
            bad_quality = []
            overlap_count = 0
            mismatch_count = 0
            for row in rows:
                o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
                if any(v is None or float(v) <= 0 for v in (o, h, l, c)):
                    bad_ohlc.append(row["candle_date"])
                elif float(h) < max(float(o), float(l), float(c)) or float(l) > min(float(o), float(h), float(c)):
                    bad_ohlc.append(row["candle_date"])
                if row["quality_status"] != "valid_ohlc":
                    bad_quality.append((row["candle_date"], row["quality_status"]))
                if row["overlap_status"] != "no_legacy_daily_record":
                    overlap_count += 1
                if row["overlap_status"] in ("ohlc_mismatch_review", "close_mismatch_review"):
                    mismatch_count += 1
                if date.fromisoformat(row["candle_date"]).weekday() >= 5:
                    staged_weekend_dates.add(row["candle_date"])

            combined["overlaps"] += overlap_count
            combined["new"] += len(rows) - overlap_count
            combined["mismatches"] += mismatch_count
            audit.check(f"{year} OHLC values and geometry are valid", not bad_ohlc,
                        f"invalid records={len(bad_ohlc)}")
            audit.check(f"{year} quality status is valid_ohlc for every row", not bad_quality,
                        f"non-valid rows={len(bad_quality)}")
            audit.check(f"{year} overlap count matches plan", overlap_count == exp["overlaps"],
                        f"actual={overlap_count}; expected={exp['overlaps']}")
            audit.check(f"{year} overlap mismatch statuses are absent", mismatch_count == 0,
                        f"mismatch records={mismatch_count}")

            link_count = one(
                con,
                """SELECT COUNT(*) FROM historical_source_batch_links
                   WHERE source_code='NSE_INDICES_HISTORICAL_DATA'
                     AND external_source_batch_id=? AND link_role='staged_external_file'""",
                (exp["batch_id"],),
            )
            audit.check(f"{year} has one staged source-batch link", link_count == 1,
                        f"link rows={link_count}")

            # Recompute the legacy overlap comparison directly against the canonical snapshot.
            record_mismatches: list[str] = []
            ohlc_overlap_count = 0
            close_only_overlap_count = 0
            for row in rows:
                canonical = con.execute(
                    """SELECT open, high, low, close FROM daily_ohlcv_analytical
                       WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                    (SNAPSHOT_BATCH, INSTRUMENT, row["candle_date"]),
                ).fetchone()
                if canonical is not None:
                    ohlc_overlap_count += 1
                    fields = ("open", "high", "low", "close")
                    if any(abs(float(row[k]) - float(canonical[i])) > TOLERANCE
                           for i, k in enumerate(fields)):
                        record_mismatches.append(row["candle_date"])
                else:
                    canonical_close = con.execute(
                        """SELECT close FROM daily_close_series
                           WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                        (SNAPSHOT_BATCH, INSTRUMENT, row["candle_date"]),
                    ).fetchone()
                    if canonical_close is not None:
                        close_only_overlap_count += 1
                        if abs(float(row["close"]) - float(canonical_close[0])) > TOLERANCE:
                            record_mismatches.append(row["candle_date"])
            audit.check(f"{year} canonical overlap comparison has no mismatches",
                        not record_mismatches,
                        f"OHLC overlaps={ohlc_overlap_count}; close-only overlaps={close_only_overlap_count}; mismatches={len(record_mismatches)}")

        print("\nCOMBINED STAGING RECONCILIATION")
        print("-" * 88)
        audit.check("Total staged rows equal 454", combined["rows"] == 454,
                    f"actual={combined['rows']}")
        audit.check("Total overlaps equal 44", combined["overlaps"] == 44,
                    f"actual={combined['overlaps']}")
        audit.check("Total new dates equal 410", combined["new"] == 410,
                    f"actual={combined['new']}")
        audit.check("No overlap mismatch records", combined["mismatches"] == 0,
                    f"mismatch records={combined['mismatches']}")

        # All weekend dates in the staged files must be registered NSE equity special sessions.
        registered = set()
        if staged_weekend_dates:
            marks = ",".join("?" for _ in staged_weekend_dates)
            registered = {
                r[0] for r in con.execute(
                    f"""SELECT session_date FROM exchange_calendar_events
                        WHERE exchange='NSE' AND market_segment='EQUITY'
                          AND event_type='special_session_open'
                          AND session_date IN ({marks})""",
                    tuple(sorted(staged_weekend_dates)),
                ).fetchall()
            }
        audit.check("All staged weekend dates have NSE special-session events",
                    registered == staged_weekend_dates,
                    f"staged={sorted(staged_weekend_dates)}; registered={sorted(registered)}")

        all_dates = [d for items in staged_dates_by_year.values() for d in items]
        holiday_dates: set[str] = set()
        if all_dates:
            marks = ",".join("?" for _ in all_dates)
            holiday_dates = {
                r[0] for r in con.execute(
                    f"""SELECT session_date FROM exchange_calendar_events
                        WHERE exchange='NSE' AND market_segment='EQUITY'
                          AND event_type='holiday_closed' AND session_date IN ({marks})""",
                    tuple(all_dates),
                ).fetchall()
            }
        audit.check("No staged source rows fall on registered NSE holidays",
                    not holiday_dates,
                    f"holiday dates found={sorted(holiday_dates)}")

        integrity = one(con, "PRAGMA integrity_check")
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        audit.check("SQLite integrity check is OK", integrity == "ok", f"result={integrity}")
        audit.check("Foreign-key check has zero errors", len(fk_errors) == 0,
                    f"errors={len(fk_errors)}")

        print("\nFINAL RESULT")
        print("=" * 88)
        print(f"Checks performed: {audit.checks}")
        print(f"Failures: {len(audit.errors)}")
        print("Canonical daily / quality / aggregate tables: read only; unchanged")
        if audit.errors:
            print("Result: REVIEW REQUIRED — do not promote until every failure is resolved.")
            return 1
        print("Result: STAGING RECONCILIATION PASSED — source remains pending_review.")
        print("Next action: prepare a separate promotion dry run; this script does not promote data.")
        return 0
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    return run_audit(args.database)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
