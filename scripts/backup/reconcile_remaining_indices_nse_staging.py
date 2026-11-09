#!/usr/bin/env python3
"""Read-only reconciliation for NSE BANKNIFTY, FINNIFTY, MIDCPNIFTY and INDIA_VIX staging.

Run from the Market Cycle Tracker project root:
    python scripts\\reconcile_remaining_indices_nse_staging.py

The script verifies external staging batches 7-14 against the validated CSV hashes,
checks year-specific source mappings and links, recomputes overlap comparisons against
canonical snapshot batch 4, verifies weekend/holiday calendar exceptions, and checks
canonical batch/aggregate counts and SQLite integrity. It does not modify the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "historical_staging.db"
DEFAULT_INPUT = ROOT / "backend" / "data" / "incoming"
SNAPSHOT_BATCH = 4
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
TOLERANCE = 0.02
TIME_WINDOWS = {
    2025: ("2025-01-01", "2025-12-31", 249),
    2026: ("2026-01-01", "2026-10-30", 205),
}
INSTRUMENTS = {
    "BANKNIFTY": {
        "index_name": "NIFTY BANK",
        "stem": "banknifty",
        "source_table_prefix": "nse_indices_historical",
        "parser_kind": "equity",
        "hashes": {
            2025: "f7c37da33d75b2a00013d98808bc7c1fd7c3ff84579f42b45169cebd97b9c480",
            2026: "19be5246d61cd4916f5235f714a3a1dca3268215b5a2cdf58cac11f37a61b5f7",
        },
        "batch_ids": {2025: 7, 2026: 8},
    },
    "FINNIFTY": {
        "index_name": "NIFTY FINANCIAL SERVICES",
        "stem": "finnifty",
        "source_table_prefix": "nse_indices_historical",
        "parser_kind": "equity",
        "hashes": {
            2025: "93d057c238adee9345c142a196805ce6687b90acaa8903f911409749467fc2b7",
            2026: "3083d3df03d8021a2e773b49babfa30fb399bb6ee7c5fccd11317ab18499100a",
        },
        "batch_ids": {2025: 9, 2026: 10},
    },
    "MIDCPNIFTY": {
        "index_name": "NIFTY MIDCAP SELECT",
        "stem": "midcpnifty",
        "source_table_prefix": "nse_indices_historical",
        "parser_kind": "equity",
        "hashes": {
            2025: "2faa00bad52d394f6e103a1d3c8c6b2ce2a8e449b9c107aa1527a4ace3ea39ad",
            2026: "70d5aabe13455a8f9a9e306249d32cc1ea0a8b6666a933f3401d2caa2dd91572",
        },
        "batch_ids": {2025: 11, 2026: 12},
    },
    "INDIA_VIX": {
        "index_name": "INDIA VIX",
        "stem": "indiavix",
        "source_table_prefix": "nse_india_vix_historical",
        "parser_kind": "vix",
        "hashes": {
            2025: "ffc7cce46a8b81c4d242bb03e1afd81698574803b17b58918810b41426c0fe6c",
            2026: "058e7fe8708fef1bd1365671863a9a2473baa2703787620d13e49b21b5ba6885",
        },
        "batch_ids": {2025: 13, 2026: 14},
    },
}

EXPECTED_CANONICAL_COUNTS = {
    "raw_daily_records": 20969,
    "daily_quality_assessments": 20969,
    "daily_close_series": 20915,
    "daily_ohlcv_analytical": 20795,
    "aggregated_ohlcv": 5529,
    "aggregated_close_series": 5560,
}


@dataclass
class Audit:
    checks: int = 0
    failures: list[str] | None = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks += 1
        message = f"{label}" + (f" — {detail}" if detail else "")
        if ok:
            print(f"[PASS] {message}")
        else:
            assert self.failures is not None
            self.failures.append(message)
            print(f"[FAIL] {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = con.execute(sql, params).fetchone()
    return row[0] if row is not None else None


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return scalar(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)) == 1


def expected_filename(instrument: str, year: int) -> str:
    return f"{INSTRUMENTS[instrument]['stem']}_nse_{year}.csv"


def expected_source_table(instrument: str, year: int) -> str:
    return f"{INSTRUMENTS[instrument]['source_table_prefix']}_{year}"


def expected_mapping_code(instrument: str, year: int) -> str:
    return f"NSE:{instrument}:{expected_source_table(instrument, year)}:1D"


def run(db_path: Path, input_dir: Path, snapshot_batch: int) -> int:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    audit = Audit()
    try:
        print("NSE STAGING RECONCILIATION — BANKNIFTY / FINNIFTY / MIDCPNIFTY / INDIA_VIX")
        print("=" * 112)
        print(f"Database: {db_path}")
        print(f"Canonical snapshot: batch {snapshot_batch}")
        print("External source batches: 7–14")
        print("Mode: READ-ONLY; no database changes will be made")
        print("Overlap tolerance: 0.02 index points")

        required = (
            "external_index_source_batches", "external_index_daily_records",
            "historical_data_sources", "historical_instrument_source_mappings",
            "historical_source_batch_links", "daily_ohlcv_analytical",
            "daily_close_series", "raw_daily_records", "daily_quality_assessments",
            "aggregated_ohlcv", "aggregated_close_series", "exchange_calendar_events",
        )
        missing = [name for name in required if not table_exists(con, name)]
        audit.check("Required staging, canonical and calendar tables exist", not missing,
                    f"missing={missing}" if missing else f"all {len(required)} tables found")
        if missing:
            return 1

        source = con.execute(
            "SELECT source_code, is_active FROM historical_data_sources WHERE source_code=?",
            (SOURCE_CODE,),
        ).fetchone()
        audit.check("NSE official source registry entry exists", source is not None)
        if source is None:
            return 1
        audit.check("NSE source registry is active", int(source["is_active"]) == 1,
                    f"is_active={source['is_active']}")

        raw_snapshot_count = scalar(
            con, "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=?", (snapshot_batch,)
        )
        audit.check("Canonical snapshot batch has raw records", raw_snapshot_count > 0,
                    f"batch={snapshot_batch}; raw rows={raw_snapshot_count}")

        total_rows = total_overlaps = total_new = total_weekends = total_mismatches = 0
        all_dates: set[str] = set()
        staged_weekend_dates: set[str] = set()
        staged_weekend_row_count = 0
        instrument_totals: dict[str, dict[str, int]] = {}
        mapping_rows_seen: set[str] = set()

        for instrument, spec in INSTRUMENTS.items():
            print(f"\n{instrument}")
            print("-" * 112)
            inst_rows = inst_overlaps = inst_new = 0
            for year in (2025, 2026):
                start, end, expected_count = TIME_WINDOWS[year]
                batch_id = spec["batch_ids"][year]
                filename = expected_filename(instrument, year)
                source_table = expected_source_table(instrument, year)
                expected_hash = spec["hashes"][year]
                path = input_dir / filename
                file_exists = path.is_file()
                audit.check(f"{year} source CSV exists", file_exists, filename)
                if not file_exists:
                    continue
                actual_hash = sha256_file(path)
                audit.check(f"{year} source CSV SHA-256 matches validated file", actual_hash == expected_hash,
                            f"actual={actual_hash}")

                batches = con.execute(
                    """SELECT id, source_provider, source_url, instrument_code, source_index_name,
                              source_filename, source_sha256, source_size_bytes, calendar_year,
                              expected_session_count, source_row_count, unique_date_count, import_status
                       FROM external_index_source_batches
                       WHERE instrument_code=? AND calendar_year=? AND source_filename=?
                       ORDER BY id""",
                    (instrument, year, filename),
                ).fetchall()
                audit.check(f"{year} external source batch is unique", len(batches) == 1,
                            f"matching rows={len(batches)}")
                if len(batches) != 1:
                    continue
                batch = batches[0]
                audit.check(f"{year} external batch ID is {batch_id}", batch["id"] == batch_id,
                            f"actual={batch['id']}")
                expected_provider = "NSE India VIX historical data" if instrument == "INDIA_VIX" else "NSE Indices historical-data report"
                expected_url = "https://www.nseindia.com/reports-indices-historical-vix" if instrument == "INDIA_VIX" else "https://www.niftyindices.com/reports/historical-data"
                audit.check(f"{year} source provider and URL are correct",
                            batch["source_provider"] == expected_provider and batch["source_url"] == expected_url,
                            f"provider={batch['source_provider']}; URL={batch['source_url']}")
                audit.check(f"{year} source batch metadata matches",
                            batch["instrument_code"] == instrument and batch["source_index_name"] == spec["index_name"]
                            and batch["source_filename"] == filename and batch["calendar_year"] == year
                            and batch["source_sha256"] == expected_hash and batch["source_size_bytes"] == path.stat().st_size,
                            f"instrument={batch['instrument_code']}; index={batch['source_index_name']}; year={batch['calendar_year']}")
                audit.check(f"{year} source row counts match validated file",
                            batch["source_row_count"] == expected_count and batch["unique_date_count"] == expected_count,
                            f"source_rows={batch['source_row_count']}; unique_dates={batch['unique_date_count']}")
                audit.check(f"{year} calendar-incomplete status is retained",
                            batch["import_status"] == "staged_validated_calendar_incomplete"
                            and batch["expected_session_count"] == 0,
                            f"status={batch['import_status']}; expected_session_count={batch['expected_session_count']}")

                rows = con.execute(
                    """SELECT source_row_number, instrument_code, source_index_name, candle_date,
                              raw_date, open, high, low, close, overlap_status, quality_status, issue_codes
                       FROM external_index_daily_records WHERE batch_id=? ORDER BY candle_date""",
                    (batch_id,),
                ).fetchall()
                dates = [str(row["candle_date"]) for row in rows]
                total_rows += len(rows)
                inst_rows += len(rows)
                all_dates.update(dates)
                audit.check(f"{year} staged row count is {expected_count}", len(rows) == expected_count,
                            f"actual={len(rows)}")
                audit.check(f"{year} dates are unique", len(dates) == len(set(dates)))
                audit.check(f"{year} date range is correct",
                            bool(dates) and min(dates) == start and max(dates) == end,
                            f"actual={min(dates) if dates else None} .. {max(dates) if dates else None}")
                audit.check(f"{year} all records identify the expected instrument/index",
                            all(row["instrument_code"] == instrument and row["source_index_name"] == spec["index_name"] for row in rows))

                bad_ohlc: list[str] = []
                bad_quality: list[str] = []
                bad_issues: list[str] = []
                overlap_count = mismatch_count = ohlc_overlap_count = close_only_overlap_count = 0
                record_mismatches: list[str] = []
                for row in rows:
                    vals = [row[key] for key in ("open", "high", "low", "close")]
                    try:
                        nums = [float(value) for value in vals]
                        if any(not (value > 0) for value in nums):
                            raise ValueError("non-positive OHLC")
                        o, h, l, c = nums
                        if h < max(o, l, c) or l > min(o, h, c):
                            raise ValueError("invalid OHLC geometry")
                    except (TypeError, ValueError):
                        bad_ohlc.append(str(row["candle_date"]))
                    if row["quality_status"] != "valid_ohlc":
                        bad_quality.append(str(row["candle_date"]))
                    try:
                        codes = json.loads(row["issue_codes"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        codes = ["INVALID_JSON"]
                    if codes:
                        bad_issues.append(str(row["candle_date"]))
                    overlap_status = row["overlap_status"]
                    if overlap_status != "no_legacy_daily_record":
                        overlap_count += 1
                    if overlap_status in ("ohlc_mismatch_review", "close_mismatch_review"):
                        mismatch_count += 1
                    if date.fromisoformat(str(row["candle_date"])).weekday() >= 5:
                        staged_weekend_dates.add(str(row["candle_date"]))
                        staged_weekend_row_count += 1

                    canonical = con.execute(
                        """SELECT open, high, low, close FROM daily_ohlcv_analytical
                           WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                        (snapshot_batch, instrument, row["candle_date"]),
                    ).fetchone()
                    if canonical is not None:
                        ohlc_overlap_count += 1
                        if any(abs(float(row[field]) - float(canonical[index])) > TOLERANCE
                               for index, field in enumerate(("open", "high", "low", "close"))):
                            record_mismatches.append(str(row["candle_date"]))
                    else:
                        canonical_close = con.execute(
                            """SELECT close FROM daily_close_series
                               WHERE import_batch_id=? AND instrument_code=? AND candle_date=?""",
                            (snapshot_batch, instrument, row["candle_date"]),
                        ).fetchone()
                        if canonical_close is not None:
                            close_only_overlap_count += 1
                            if abs(float(row["close"]) - float(canonical_close[0])) > TOLERANCE:
                                record_mismatches.append(str(row["candle_date"]))

                expected_overlaps = 44 if year == 2025 else 0
                new_count = len(rows) - overlap_count
                total_overlaps += overlap_count
                total_new += new_count
                total_mismatches += mismatch_count + len(record_mismatches)
                inst_overlaps += overlap_count
                inst_new += new_count
                audit.check(f"{year} OHLC values and geometry are valid", not bad_ohlc,
                            f"invalid rows={len(bad_ohlc)}")
                audit.check(f"{year} all staged rows have valid_ohlc quality", not bad_quality,
                            f"non-valid rows={len(bad_quality)}")
                audit.check(f"{year} issue-code arrays are empty", not bad_issues,
                            f"rows with issue codes={len(bad_issues)}")
                audit.check(f"{year} overlap count matches validated baseline", overlap_count == expected_overlaps,
                            f"actual={overlap_count}; expected={expected_overlaps}")
                audit.check(f"{year} overlap status contains no mismatch flags", mismatch_count == 0,
                            f"mismatch-status rows={mismatch_count}")
                audit.check(f"{year} direct canonical overlap comparison has no mismatches",
                            not record_mismatches,
                            f"OHLC overlaps={ohlc_overlap_count}; close-only overlaps={close_only_overlap_count}; mismatches={len(record_mismatches)}")
                audit.check(f"{year} full OHLC/close-only overlap counts match expected structure",
                            ohlc_overlap_count == expected_overlaps and close_only_overlap_count == 0,
                            f"OHLC={ohlc_overlap_count}; close-only={close_only_overlap_count}")

                link_count = scalar(
                    con,
                    """SELECT COUNT(*) FROM historical_source_batch_links
                       WHERE source_code=? AND external_source_batch_id=? AND link_role='staged_external_file'""",
                    (SOURCE_CODE, batch_id),
                )
                audit.check(f"{year} one source-batch link exists", link_count == 1,
                            f"link rows={link_count}")

                mapping_code = expected_mapping_code(instrument, year)
                mapping = con.execute(
                    """SELECT mapping_code, source_code, instrument_code, source_symbol,
                              source_table, timeframe, mapping_role, valid_from, valid_to,
                              mapping_status, metadata_json
                       FROM historical_instrument_source_mappings WHERE mapping_code=?""",
                    (mapping_code,),
                ).fetchone()
                mapping_rows_seen.add(mapping_code)
                audit.check(f"{year} exact year-specific source mapping exists", mapping is not None,
                            mapping_code)
                if mapping is not None:
                    audit.check(f"{year} mapping identifies source/instrument/table",
                                mapping["source_code"] == SOURCE_CODE
                                and mapping["instrument_code"] == instrument
                                and mapping["source_symbol"] == spec["index_name"]
                                and mapping["source_table"] == source_table
                                and mapping["timeframe"] == "1D",
                                f"source={mapping['source_code']}; instrument={mapping['instrument_code']}; table={mapping['source_table']}")
                    audit.check(f"{year} mapping remains pending review until promotion",
                                mapping["mapping_role"] == "pending_review" and mapping["mapping_status"] == "pending_review",
                                f"role={mapping['mapping_role']}; status={mapping['mapping_status']}")
                    audit.check(f"{year} mapping validity dates are exact",
                                mapping["valid_from"] == start and mapping["valid_to"] == end,
                                f"period={mapping['valid_from']}..{mapping['valid_to']}")
                    try:
                        metadata = json.loads(mapping["metadata_json"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        metadata = {}
                    audit.check(f"{year} mapping metadata references its staged batch/file/hash",
                                metadata.get("external_source_batch_ids") == [batch_id]
                                and metadata.get("source_filenames") == [filename]
                                and metadata.get("source_sha256") == expected_hash
                                and metadata.get("source_table_provenance") == source_table,
                                f"batch_ids={metadata.get('external_source_batch_ids')}; filenames={metadata.get('source_filenames')}")

            instrument_totals[instrument] = {"rows": inst_rows, "overlaps": inst_overlaps, "new": inst_new}
            print(f"{instrument:10} | rows={inst_rows} | overlaps={inst_overlaps} | new_dates={inst_new}")

        print("\nCOMBINED STAGING RECONCILIATION")
        print("-" * 112)
        audit.check("All eight expected instrument/year mappings were checked", len(mapping_rows_seen) == 8,
                    f"unique mapping codes checked={len(mapping_rows_seen)}")
        audit.check("Total staged records equal 1,816", total_rows == 1816, f"actual={total_rows}")
        audit.check("Total overlaps equal 176", total_overlaps == 176, f"actual={total_overlaps}")
        audit.check("Total new dates equal 1,640", total_new == 1640, f"actual={total_new}")
        audit.check("No overlap mismatches were found", total_mismatches == 0,
                    f"mismatch flags/direct comparison failures={total_mismatches}")
        audit.check("Each instrument has 454 staged records", all(v["rows"] == 454 for v in instrument_totals.values()),
                    f"per-instrument={instrument_totals}")
        audit.check("Each instrument has 44 overlaps and 410 new dates",
                    all(v["overlaps"] == 44 and v["new"] == 410 for v in instrument_totals.values()),
                    f"per-instrument={instrument_totals}")

        weekend_expected = {"2025-02-01", "2026-02-01"}
        audit.check("Total staged weekend rows equal eight", staged_weekend_row_count == 8,
                    f"actual={staged_weekend_row_count}; distinct weekend dates={len(staged_weekend_dates)}")
        if staged_weekend_dates:
            marks = ",".join("?" for _ in staged_weekend_dates)
            registered = {
                row[0] for row in con.execute(
                    f"""SELECT session_date FROM exchange_calendar_events
                        WHERE exchange='NSE' AND market_segment='EQUITY'
                          AND event_type='special_session_open' AND session_date IN ({marks})""",
                    tuple(sorted(staged_weekend_dates)),
                ).fetchall()
            }
        else:
            registered = set()
        audit.check("Staged weekend dates are exactly the two expected special sessions",
                    staged_weekend_dates == weekend_expected,
                    f"dates={sorted(staged_weekend_dates)}")
        audit.check("All staged weekend sessions are registered with NSE calendar",
                    registered == staged_weekend_dates,
                    f"registered={sorted(registered)}")

        if all_dates:
            marks = ",".join("?" for _ in all_dates)
            holiday_dates = {
                row[0] for row in con.execute(
                    f"""SELECT session_date FROM exchange_calendar_events
                        WHERE exchange='NSE' AND market_segment='EQUITY'
                          AND event_type='holiday_closed' AND session_date IN ({marks})""",
                    tuple(sorted(all_dates)),
                ).fetchall()
            }
        else:
            holiday_dates = set()
        audit.check("No staged records fall on registered NSE holiday dates", not holiday_dates,
                    f"holiday dates found={sorted(holiday_dates)}")

        print("\nCANONICAL SNAPSHOT PRESERVATION CHECKS")
        print("-" * 112)
        for table, expected_count in EXPECTED_CANONICAL_COUNTS.items():
            actual = scalar(con, f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=?", (snapshot_batch,))
            audit.check(f"Canonical batch {snapshot_batch} {table} count unchanged from baseline",
                        actual == expected_count, f"actual={actual}; expected={expected_count}")

        integrity = scalar(con, "PRAGMA integrity_check")
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        audit.check("SQLite integrity check is OK", integrity == "ok", f"result={integrity}")
        audit.check("Foreign-key check has zero errors", len(fk_errors) == 0, f"errors={len(fk_errors)}")

        print("\nFINAL RESULT")
        print("=" * 112)
        print(f"Checks performed: {audit.checks}")
        assert audit.failures is not None
        print(f"Failures: {len(audit.failures)}")
        print("Canonical daily / quality / aggregate tables: read only; unchanged")
        if audit.failures:
            print("Result: RECONCILIATION FAILED — do not promote until all failures are resolved.")
            return 1
        print("Result: STAGING RECONCILIATION PASSED — all eight source batches remain pending_review.")
        print("Next action: prepare a separate composite promotion dry run; this script does not promote data.")
        return 0
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--snapshot-batch", type=int, default=SNAPSHOT_BATCH)
    args = parser.parse_args()
    return run(args.database, args.input_dir, args.snapshot_batch)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
