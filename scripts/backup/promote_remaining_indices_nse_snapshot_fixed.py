#!/usr/bin/env python3
"""Read-only promotion preflight for BANKNIFTY, FINNIFTY, MIDCPNIFTY and INDIA_VIX.

The script validates staged NSE external batches 7-14 and computes the proposed
composite snapshot counts. It intentionally has no --apply mode and never writes
to the SQLite database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
INPUT_DIR = ROOT / "backend" / "data" / "incoming"
PARENT_BATCH_ID = 4
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
START_DATE = "2025-01-01"
END_DATE = "2026-10-30"
TOLERANCE = 0.02
# raw_daily_records has a unique key on (import_batch_id, source_table, source_row_number).
# The NSE indices CSVs share a generic source_table by year, so namespace each CSV's
# original row numbers by its external batch ID in the composite raw table. The
# original CSV row number remains unchanged in external_index_daily_records.
SOURCE_ROW_NAMESPACE_MULTIPLIER = 1_000_000

# ext batch id: expected metadata and source provenance
BATCHES: dict[int, dict[str, Any]] = {
    7: {"instrument": "BANKNIFTY", "index": "NIFTY BANK", "year": 2025,
        "filename": "banknifty_nse_2025.csv", "sha256": "f7c37da33d75b2a00013d98808bc7c1fd7c3ff84579f42b45169cebd97b9c480",
        "size": 17519, "rows": 249, "overlaps": 44, "new": 205,
        "table": "nse_indices_historical_2025", "provider": "NSE Indices historical-data report",
        "url": "https://www.niftyindices.com/reports/historical-data"},
    8: {"instrument": "BANKNIFTY", "index": "NIFTY BANK", "year": 2026,
        "filename": "banknifty_nse_2026.csv", "sha256": "19be5246d61cd4916f5235f714a3a1dca3268215b5a2cdf58cac11f37a61b5f7",
        "size": 14466, "rows": 205, "overlaps": 0, "new": 205,
        "table": "nse_indices_historical_2026", "provider": "NSE Indices historical-data report",
        "url": "https://www.niftyindices.com/reports/historical-data"},
    9: {"instrument": "FINNIFTY", "index": "NIFTY FINANCIAL SERVICES", "year": 2025,
        "filename": "finnifty_nse_2025.csv", "sha256": "93d057c238adee9345c142a196805ce6687b90acaa8903f911409749467fc2b7",
        "size": 21031, "rows": 249, "overlaps": 44, "new": 205,
        "table": "nse_indices_historical_2025", "provider": "NSE Indices historical-data report",
        "url": "https://www.niftyindices.com/reports/historical-data"},
    10: {"instrument": "FINNIFTY", "index": "NIFTY FINANCIAL SERVICES", "year": 2026,
         "filename": "finnifty_nse_2026.csv", "sha256": "3083d3df03d8021a2e773b49babfa30fb399bb6ee7c5fccd11317ab18499100a",
         "size": 17334, "rows": 205, "overlaps": 0, "new": 205,
         "table": "nse_indices_historical_2026", "provider": "NSE Indices historical-data report",
         "url": "https://www.niftyindices.com/reports/historical-data"},
    11: {"instrument": "MIDCPNIFTY", "index": "NIFTY MIDCAP SELECT", "year": 2025,
         "filename": "midcpnifty_nse_2025.csv", "sha256": "2faa00bad52d394f6e103a1d3c8c6b2ce2a8e449b9c107aa1527a4ace3ea39ad",
         "size": 19749, "rows": 249, "overlaps": 44, "new": 205,
         "table": "nse_indices_historical_2025", "provider": "NSE Indices historical-data report",
         "url": "https://www.niftyindices.com/reports/historical-data"},
    12: {"instrument": "MIDCPNIFTY", "index": "NIFTY MIDCAP SELECT", "year": 2026,
         "filename": "midcpnifty_nse_2026.csv", "sha256": "70d5aabe13455a8f9a9e306249d32cc1ea0a8b6666a933f3401d2caa2dd91572",
         "size": 16304, "rows": 205, "overlaps": 0, "new": 205,
         "table": "nse_indices_historical_2026", "provider": "NSE Indices historical-data report",
         "url": "https://www.niftyindices.com/reports/historical-data"},
    13: {"instrument": "INDIA_VIX", "index": "INDIA VIX", "year": 2025,
         "filename": "indiavix_nse_2025.csv", "sha256": "ffc7cce46a8b81c4d242bb03e1afd81698574803b17b58918810b41426c0fe6c",
         "size": 14498, "rows": 249, "overlaps": 44, "new": 205,
         "table": "nse_india_vix_historical_2025", "provider": "NSE India VIX historical data",
         "url": "https://www.nseindia.com/reports-indices-historical-vix"},
    14: {"instrument": "INDIA_VIX", "index": "INDIA VIX", "year": 2026,
         "filename": "indiavix_nse_2026.csv", "sha256": "058e7fe8708fef1bd1365671863a9a2473baa2703787620d13e49b21b5ba6885",
         "size": 11861, "rows": 205, "overlaps": 0, "new": 205,
         "table": "nse_india_vix_historical_2026", "provider": "NSE India VIX historical data",
         "url": "https://www.nseindia.com/reports-indices-historical-vix"},
}

EXPECTED_PARENT = {"raw": 20969, "quality": 20969, "close": 20915, "ohlc": 20795}
EXPECTED_PARENT_AGG = {"ohlc": 5529, "close": 5560}
EXPECTED_PARENT_INSTRUMENTS = {
    "BANKNIFTY": {"raw": 3736, "close": 3736, "ohlc": 3736},
    "FINNIFTY": {"raw": 3313, "close": 3313, "ohlc": 3199},
    "INDIA_VIX": {"raw": 3819, "close": 3765, "ohlc": 3759},
    "MIDCPNIFTY": {"raw": 649, "close": 649, "ohlc": 649},
    "NIFTY50": {"raw": 4138, "close": 4138, "ohlc": 4138},
    "SENSEX": {"raw": 5314, "close": 5314, "ohlc": 5314},
}
EXPECTED_NEW = {"raw": 22609, "quality": 22609, "close": 22555, "ohlc": 22435}
EXPECTED_NEW_INSTRUMENTS = {
    "BANKNIFTY": {"raw": 4146, "close": 4146, "ohlc": 4146},
    "FINNIFTY": {"raw": 3723, "close": 3723, "ohlc": 3609},
    "INDIA_VIX": {"raw": 4229, "close": 4175, "ohlc": 4169},
    "MIDCPNIFTY": {"raw": 1059, "close": 1059, "ohlc": 1059},
    "NIFTY50": {"raw": 4138, "close": 4138, "ohlc": 4138},
    "SENSEX": {"raw": 5314, "close": 5314, "ohlc": 5314},
}
COMPOSITE_PATH = (
    "composite_snapshot://batch_4+NSE_external_batches_7_14"
    "?policy=replace_BANKNIFTY_FINNIFTY_MIDCPNIFTY_INDIA_VIX_2025_01_01_to_2026_10_30"
)

CHECKS = 0


def require(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise RuntimeError(message)


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def count(con: sqlite3.Connection, table: str, batch_id: int, instrument: str | None = None) -> int:
    if instrument is None:
        sql = f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=?"
        args: tuple[Any, ...] = (batch_id,)
    else:
        sql = f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=? AND instrument_code=?"
        args = (batch_id, instrument)
    return int(con.execute(sql, args).fetchone()[0])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mapping_code(spec: dict[str, Any]) -> str:
    return f"NSE:{spec['instrument']}:{spec['table']}:1D"


def namespaced_source_row_number(external_batch_id: int, original_row_number: int) -> int:
    """Return a unique raw-table row locator while preserving the original in staging.

    Multiple instrument CSVs share the same year-specific source_table string. The
    composite raw table's unique index does not include instrument_code, so a stable
    batch namespace prevents valid rows from colliding. The original CSV row number
    remains recorded on external_index_daily_records and is recoverable via source_id.
    """
    original = int(original_row_number)
    if original < 0 or original >= SOURCE_ROW_NAMESPACE_MULTIPLIER:
        raise ValueError(
            f"Original source row number {original} must be between 0 and "
            f"{SOURCE_ROW_NAMESPACE_MULTIPLIER - 1}."
        )
    return int(external_batch_id) * SOURCE_ROW_NAMESPACE_MULTIPLIER + original


def validate_parent(con: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    parent = con.execute("SELECT * FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)).fetchone()
    require(parent is not None and parent["status"] == "completed",
            "Parent snapshot batch 4 is missing or not completed.")
    completed = [int(r[0]) for r in con.execute(
        "SELECT id FROM import_batches WHERE status='completed' ORDER BY id"
    ).fetchall()]
    require(completed == [1, 2, 3, 4],
            f"Expected completed snapshots [1,2,3,4]; found {completed}.")

    parent_counts = {
        "raw": count(con, "raw_daily_records", PARENT_BATCH_ID),
        "quality": count(con, "daily_quality_assessments", PARENT_BATCH_ID),
        "close": count(con, "daily_close_series", PARENT_BATCH_ID),
        "ohlc": count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID),
    }
    require(parent_counts == EXPECTED_PARENT,
            f"Parent batch 4 counts differ from audited baseline: {parent_counts}.")
    parent_agg = {
        "ohlc": count(con, "aggregated_ohlcv", PARENT_BATCH_ID),
        "close": count(con, "aggregated_close_series", PARENT_BATCH_ID),
    }
    require(parent_agg == EXPECTED_PARENT_AGG,
            f"Parent batch 4 aggregate counts differ from baseline: {parent_agg}.")

    actual_by_instrument: dict[str, dict[str, int]] = {}
    for instrument, expected in EXPECTED_PARENT_INSTRUMENTS.items():
        actual = {
            "raw": count(con, "raw_daily_records", PARENT_BATCH_ID, instrument),
            "close": count(con, "daily_close_series", PARENT_BATCH_ID, instrument),
            "ohlc": count(con, "daily_ohlcv_analytical", PARENT_BATCH_ID, instrument),
        }
        require(actual == expected,
                f"Parent batch 4 {instrument} counts differ: actual={actual}, expected={expected}.")
        actual_by_instrument[instrument] = actual

    return parent_counts, parent_agg


def validate_one_batch(con: sqlite3.Connection, batch_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    path = INPUT_DIR / spec["filename"]
    require(path.is_file(), f"Original CSV file is missing: {path}.")
    require(path.stat().st_size == spec["size"],
            f"CSV size changed for {spec['filename']}: {path.stat().st_size} vs {spec['size']}.")
    actual_hash = file_sha256(path)
    require(actual_hash == spec["sha256"],
            f"CSV SHA-256 changed for {spec['filename']}: {actual_hash}.")

    batch = con.execute(
        "SELECT * FROM external_index_source_batches WHERE id=?", (batch_id,)
    ).fetchone()
    require(batch is not None, f"External source batch {batch_id} is missing.")
    require(batch["source_provider"] == spec["provider"] and batch["source_url"] == spec["url"],
            f"External source batch {batch_id} provider or URL mismatch.")
    require(batch["instrument_code"] == spec["instrument"] and batch["source_index_name"] == spec["index"],
            f"External source batch {batch_id} instrument/index mismatch.")
    require(batch["source_filename"] == spec["filename"] and batch["source_sha256"] == spec["sha256"],
            f"External source batch {batch_id} file identity/hash mismatch.")
    require(int(batch["source_size_bytes"]) == spec["size"],
            f"External source batch {batch_id} file-size metadata mismatch.")
    require(int(batch["calendar_year"]) == spec["year"],
            f"External source batch {batch_id} calendar year mismatch.")
    require(int(batch["source_row_count"]) == spec["rows"] and int(batch["unique_date_count"]) == spec["rows"],
            f"External source batch {batch_id} row/unique-date counts mismatch.")
    require(batch["import_status"] == "staged_validated_calendar_incomplete" and int(batch["expected_session_count"]) == 0,
            f"External source batch {batch_id} status/calendar assertion mismatch.")

    date_start = f"{spec['year']}-01-01"
    date_end = "2025-12-31" if spec["year"] == 2025 else "2026-10-30"
    rows = con.execute(
        "SELECT * FROM external_index_daily_records WHERE batch_id=? ORDER BY candle_date",
        (batch_id,),
    ).fetchall()
    require(len(rows) == spec["rows"],
            f"External batch {batch_id} has {len(rows)} records; expected {spec['rows']}.")
    dates = [str(r["candle_date"]) for r in rows]
    require(len(set(dates)) == spec["rows"], f"External batch {batch_id} has duplicate dates.")
    require(min(dates) == date_start and max(dates) == date_end,
            f"External batch {batch_id} date range is {min(dates)}..{max(dates)}; expected {date_start}..{date_end}.")

    overlap_rows = 0
    new_rows = 0
    weekend_dates: list[str] = []
    for row in rows:
        require(row["instrument_code"] == spec["instrument"] and row["source_index_name"] == spec["index"],
                f"External batch {batch_id} record identity mismatch on {row['candle_date']}.")
        vals = [float(row[k]) for k in ("open", "high", "low", "close")]
        o, h, l, c = vals
        require(all(v > 0 for v in vals) and h >= max(o, l, c) and l <= min(o, h, c),
                f"External batch {batch_id} has invalid OHLC geometry on {row['candle_date']}.")
        require(row["quality_status"] == "valid_ohlc" and json.loads(row["issue_codes"] or "[]") == [],
                f"External batch {batch_id} has quality/issue flags on {row['candle_date']}.")
        if row["overlap_status"] == "ohlc_match_within_0_02":
            overlap_rows += 1
            for field in ("open", "high", "low", "close"):
                legacy_value = row[f"legacy_{field}"]
                require(legacy_value is not None and abs(float(row[field]) - float(legacy_value)) <= TOLERANCE,
                        f"External batch {batch_id} {field} overlap mismatch on {row['candle_date']}.")
        elif row["overlap_status"] == "no_legacy_daily_record":
            new_rows += 1
            require(all(row[f"legacy_{field}"] is None for field in ("open", "high", "low", "close")),
                    f"External batch {batch_id} new date unexpectedly has legacy values on {row['candle_date']}.")
        else:
            raise RuntimeError(
                f"External batch {batch_id} has unexpected overlap status {row['overlap_status']!r} on {row['candle_date']}."
            )
        if len(str(row["candle_date"])) == 10:
            from datetime import date
            if date.fromisoformat(str(row["candle_date"])).weekday() >= 5:
                weekend_dates.append(str(row["candle_date"]))

    require(overlap_rows == spec["overlaps"] and new_rows == spec["new"],
            f"External batch {batch_id} overlap/new counts are {overlap_rows}/{new_rows}; expected {spec['overlaps']}/{spec['new']}.")
    link_count = int(con.execute(
        "SELECT COUNT(*) FROM historical_source_batch_links WHERE source_code=? AND external_source_batch_id=? AND link_role='staged_external_file'",
        (SOURCE_CODE, batch_id),
    ).fetchone()[0])
    require(link_count == 1, f"External batch {batch_id} expected exactly one staged-source link; found {link_count}.")

    code = f"NSE:{spec['instrument']}:{spec['table']}:1D"
    mapping = con.execute(
        "SELECT * FROM historical_instrument_source_mappings WHERE mapping_code=?", (code,)
    ).fetchone()
    require(mapping is not None, f"Year-specific source mapping is missing: {code}.")
    require(mapping["source_code"] == SOURCE_CODE and mapping["instrument_code"] == spec["instrument"]
            and mapping["source_table"] == spec["table"] and mapping["timeframe"] == "1D",
            f"Mapping identity/table mismatch for {code}.")
    require(mapping["mapping_role"] == "pending_review" and mapping["mapping_status"] == "pending_review",
            f"Mapping {code} is not pending_review before promotion.")
    require(mapping["valid_from"] == date_start and mapping["valid_to"] == date_end,
            f"Mapping {code} validity period mismatch.")
    metadata = json.loads(mapping["metadata_json"] or "{}")
    require(metadata.get("external_source_batch_ids") == [batch_id],
            f"Mapping {code} external batch metadata mismatch.")
    require(metadata.get("source_filenames") == [spec["filename"]],
            f"Mapping {code} filename metadata mismatch.")
    require(metadata.get("source_table_provenance") == spec["table"],
            f"Mapping {code} source_table_provenance mismatch.")

    return {"rows": len(rows), "overlaps": overlap_rows, "new": new_rows,
            "weekend_dates": weekend_dates, "mapping_code": code, "mapping_id": int(mapping["mapping_id"])}


def validate_direct_overlaps(con: sqlite3.Connection, batch_id: int, spec: dict[str, Any]) -> None:
    rows = con.execute(
        "SELECT candle_date, open, high, low, close FROM external_index_daily_records WHERE batch_id=? AND overlap_status='ohlc_match_within_0_02' ORDER BY candle_date",
        (batch_id,),
    ).fetchall()
    for row in rows:
        day = row["candle_date"]
        raw_n = int(con.execute(
            "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=? AND date(source_timestamp)=?",
            (PARENT_BATCH_ID, spec["instrument"], day),
        ).fetchone()[0])
        close = con.execute(
            "SELECT close FROM daily_close_series WHERE import_batch_id=? AND instrument_code=? AND candle_date=?",
            (PARENT_BATCH_ID, spec["instrument"], day),
        ).fetchall()
        ohlc = con.execute(
            "SELECT open, high, low, close FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=? AND candle_date=?",
            (PARENT_BATCH_ID, spec["instrument"], day),
        ).fetchall()
        require(raw_n == 1 and len(close) == 1 and len(ohlc) == 1,
                f"Parent batch 4 expected one raw/close/OHLC row for {spec['instrument']} {day}.")
        for field in ("open", "high", "low", "close"):
            require(abs(float(row[field]) - float(ohlc[0][field])) <= TOLERANCE,
                    f"Direct parent {field} mismatch for {spec['instrument']} on {day}.")
        require(abs(float(row["close"]) - float(close[0][0])) <= TOLERANCE,
                f"Direct parent close mismatch for {spec['instrument']} on {day}.")


def collect_plan(con: sqlite3.Connection) -> dict[str, Any]:
    required_tables = (
        "import_batches", "raw_daily_records", "daily_quality_assessments",
        "daily_close_series", "daily_ohlcv_analytical", "aggregated_ohlcv",
        "aggregated_close_series", "historical_data_sources",
        "historical_instrument_source_mappings", "historical_source_batch_links",
        "historical_snapshot_sources", "external_index_source_batches",
        "external_index_daily_records", "exchange_calendar_events",
    )
    missing = [name for name in required_tables if not table_exists(con, name)]
    require(not missing, f"Required tables are missing: {missing}.")

    parent_counts, parent_agg = validate_parent(con)
    source = con.execute("SELECT * FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)).fetchone()
    require(source is not None and int(source["is_active"]) == 1,
            "Active NSE official source-registry entry is missing.")
    require(source["source_type"] == "official_exchange_portal",
            f"Unexpected NSE source type: {source['source_type']}.")

    results: dict[int, dict[str, Any]] = {}
    overlap_dates_by_instrument: dict[str, set[str]] = {}
    for batch_id, spec in BATCHES.items():
        results[batch_id] = validate_one_batch(con, batch_id, spec)
        validate_direct_overlaps(con, batch_id, spec)
        overlap_set = {
            str(r[0]) for r in con.execute(
                "SELECT candle_date FROM external_index_daily_records WHERE batch_id=? AND overlap_status='ohlc_match_within_0_02'",
                (batch_id,),
            ).fetchall()
        }
        overlap_dates_by_instrument.setdefault(spec["instrument"], set()).update(overlap_set)

    # Each instrument has 44 overlapping 2025 sessions and 205 new 2025 dates + 205 new 2026 dates.
    require(set(overlap_dates_by_instrument) == {"BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIA_VIX"},
            "The staged instrument set does not match the four expected instruments.")
    for instrument, dates in overlap_dates_by_instrument.items():
        require(len(dates) == 44, f"{instrument} overlap-date set has {len(dates)} dates; expected 44.")

    # Preflight the raw_daily_records unique key before opening a write transaction.
    # The table's uniqueness key is (import_batch_id, source_table, source_row_number);
    # source_table names are shared across BANKNIFTY/FINNIFTY/MIDCPNIFTY for each year.
    replacement_keys = {
        (instrument, day)
        for instrument, dates in overlap_dates_by_instrument.items()
        for day in dates
    }
    projected_raw_keys: set[tuple[str, int]] = set()
    retained_parent_rows = con.execute(
        "SELECT instrument_code, source_table, source_row_number, source_timestamp "
        "FROM raw_daily_records WHERE import_batch_id=?",
        (PARENT_BATCH_ID,),
    ).fetchall()
    for row in retained_parent_rows:
        day = str(row["source_timestamp"] or "")[:10]
        if (row["instrument_code"], day) in replacement_keys:
            continue
        if row["source_row_number"] is None:
            continue
        key = (str(row["source_table"]), int(row["source_row_number"]))
        require(key not in projected_raw_keys,
                f"Parent retained raw source key is already duplicated: {key}.")
        projected_raw_keys.add(key)

    for batch_id, spec in BATCHES.items():
        source_rows = con.execute(
            "SELECT source_row_number FROM external_index_daily_records WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
        require(len(source_rows) == int(spec["rows"]),
                f"External batch {batch_id} source-row count changed during unique-key preflight.")
        for source_row in source_rows:
            require(source_row["source_row_number"] is not None,
                    f"External batch {batch_id} has a null original source_row_number.")
            namespaced = namespaced_source_row_number(batch_id, int(source_row["source_row_number"]))
            key = (str(spec["table"]), namespaced)
            require(key not in projected_raw_keys,
                    f"Projected raw source key collision for external batch {batch_id}: {key}.")
            projected_raw_keys.add(key)
    require(len(projected_raw_keys) == len(retained_parent_rows) - len(replacement_keys) + 1816,
            "Projected raw source-key count does not equal the retained parent plus 1,816 staged rows.")

    total_rows = sum(int(x["rows"]) for x in results.values())
    total_overlaps = sum(int(x["overlaps"]) for x in results.values())
    total_new = sum(int(x["new"]) for x in results.values())
    require((total_rows, total_overlaps, total_new) == (1816, 176, 1640),
            f"Combined staged totals differ: rows={total_rows}, overlaps={total_overlaps}, new={total_new}.")

    # The 2025 overlaps must be present in raw, close and full-OHLC curated daily tables.
    replacement_counts: dict[str, dict[str, int]] = {}
    for instrument in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIA_VIX"):
        raw_n = int(con.execute(
            "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=? AND date(source_timestamp) BETWEEN ? AND ?",
            (PARENT_BATCH_ID, instrument, START_DATE, "2025-03-03"),
        ).fetchone()[0])
        quality_n = int(con.execute(
            "SELECT COUNT(*) FROM daily_quality_assessments q JOIN raw_daily_records r ON r.id=q.raw_record_id WHERE q.import_batch_id=? AND q.instrument_code=? AND date(q.source_timestamp) BETWEEN ? AND ?",
            (PARENT_BATCH_ID, instrument, START_DATE, "2025-03-03"),
        ).fetchone()[0])
        close_n = int(con.execute(
            "SELECT COUNT(*) FROM daily_close_series WHERE import_batch_id=? AND instrument_code=? AND candle_date BETWEEN ? AND ?",
            (PARENT_BATCH_ID, instrument, START_DATE, "2025-03-03"),
        ).fetchone()[0])
        ohlc_n = int(con.execute(
            "SELECT COUNT(*) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=? AND candle_date BETWEEN ? AND ?",
            (PARENT_BATCH_ID, instrument, START_DATE, "2025-03-03"),
        ).fetchone()[0])
        expected_dates = len(overlap_dates_by_instrument[instrument])
        actual = {"raw": raw_n, "quality": quality_n, "close": close_n, "ohlc": ohlc_n}
        expected = {"raw": expected_dates, "quality": expected_dates, "close": expected_dates, "ohlc": expected_dates}
        require(actual == expected,
                f"{instrument} replacement-window counts differ: actual={actual}, expected={expected}.")
        replacement_counts[instrument] = actual

    replaced = {"raw": 176, "quality": 176, "close": 176, "ohlc": 176}
    calculated = {
        "raw": parent_counts["raw"] - replaced["raw"] + total_rows,
        "quality": parent_counts["quality"] - replaced["quality"] + total_rows,
        "close": parent_counts["close"] - replaced["close"] + total_rows,
        "ohlc": parent_counts["ohlc"] - replaced["ohlc"] + total_rows,
    }
    require(calculated == EXPECTED_NEW,
            f"Calculated composite row counts differ from expected baseline: {calculated}.")

    expected_new_instruments: dict[str, dict[str, int]] = {}
    for instrument, parent_values in EXPECTED_PARENT_INSTRUMENTS.items():
        if instrument in replacement_counts:
            delta = 454 - 44
            expected_new_instruments[instrument] = {
                "raw": parent_values["raw"] + delta,
                "close": parent_values["close"] + delta,
                "ohlc": parent_values["ohlc"] + delta,
            }
        else:
            expected_new_instruments[instrument] = dict(parent_values)
    require(expected_new_instruments == EXPECTED_NEW_INSTRUMENTS,
            f"Calculated per-instrument totals differ: {expected_new_instruments}.")

    # Confirm special-session rows are present and each has one official NSE calendar exception.
    weekend_groups = sum(len(item["weekend_dates"]) for item in results.values())
    require(weekend_groups == 8, f"Expected 8 staged weekend instrument-date rows; found {weekend_groups}.")
    weekend_dates = sorted({d for item in results.values() for d in item["weekend_dates"]})
    require(weekend_dates == ["2025-02-01", "2026-02-01"],
            f"Unexpected staged weekend dates: {weekend_dates}.")
    for day in weekend_dates:
        event_n = int(con.execute(
            "SELECT COUNT(*) FROM exchange_calendar_events WHERE exchange='NSE' AND market_segment='EQUITY' AND session_date=? AND event_type='special_session_open'",
            (day,),
        ).fetchone()[0])
        require(event_n == 1, f"NSE special-session event {day} is missing or duplicated.")
    staged_dates = [
        str(r[0]) for r in con.execute(
            "SELECT candle_date FROM external_index_daily_records WHERE batch_id IN (7,8,9,10,11,12,13,14)"
        ).fetchall()
    ]
    holiday_rows = con.execute(
        "SELECT session_date FROM exchange_calendar_events WHERE exchange='NSE' AND market_segment='EQUITY' AND event_type='holiday_closed' AND session_date BETWEEN ? AND ?",
        (START_DATE, END_DATE),
    ).fetchall()
    holiday_dates = {str(r[0]) for r in holiday_rows}
    require(not (set(staged_dates) & holiday_dates),
            f"Staged records fall on registered NSE holidays: {sorted(set(staged_dates) & holiday_dates)}.")

    # Confirm there is no partial/previously-created target snapshot and no manifest-link collision.
    prior_target = con.execute("SELECT id FROM import_batches WHERE source_path=?", (COMPOSITE_PATH,)).fetchone()
    if prior_target is not None:
        raise RuntimeError(
            f"Target composite snapshot already exists as batch {prior_target['id']}."
        )
    require(prior_target is None, "Target composite snapshot must not already exist.")
    next_batch_id = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM import_batches").fetchone()[0])
    require(next_batch_id == 5, f"Expected next composite snapshot batch ID 5; found {next_batch_id}.")
    contribution_codes = [f"NSE:SNAPSHOT:5:EXTERNAL:{batch_id}" for batch_id in BATCHES]
    contribution_codes.append("LEGACY:IMPORT:5:CONTRIBUTION")
    marks = ",".join("?" for _ in contribution_codes)
    collisions = [str(r[0]) for r in con.execute(
        f"SELECT link_code FROM historical_source_batch_links WHERE link_code IN ({marks})",
        tuple(contribution_codes),
    ).fetchall()]
    require(not collisions, f"Snapshot contribution link-code collisions: {collisions}.")

    # Integrity checks are read-only and ensure the baseline DB is currently consistent.
    integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
    require(integrity == "ok", f"SQLite integrity check failed: {integrity}.")
    fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
    require(not fk_errors, f"SQLite foreign-key check found {len(fk_errors)} errors.")

    return {
        "parent_counts": parent_counts,
        "parent_agg": parent_agg,
        "total_rows": total_rows,
        "total_overlaps": total_overlaps,
        "total_new": total_new,
        "weekend_dates": weekend_dates,
        "results": results,
        "replacement_counts": replacement_counts,
        "expected_new": calculated,
        "expected_new_instruments": expected_new_instruments,
        "next_batch_id": next_batch_id,
        "contribution_codes": contribution_codes,
        "integrity": integrity,
        "fk_errors": len(fk_errors),
        "source_row_namespace_multiplier": SOURCE_ROW_NAMESPACE_MULTIPLIER,
    }


def print_plan(plan: dict[str, Any]) -> None:
    print("NSE COMPOSITE SNAPSHOT PROMOTION PREFLIGHT — FOUR INSTRUMENTS")
    print("=" * 112)
    print(f"Database: {DATABASE}")
    print(f"Parent snapshot: batch {PARENT_BATCH_ID} (completed; preserved unchanged)")
    print("External NSE batches: 7–14")
    print("Mode: READ-ONLY; no database changes or backup will be made")
    print("OHLC source only; no index volume is imported.")
    print("Annual exchange-session completeness is not asserted.")

    print("\nSOURCE RECONCILIATION")
    print("-" * 112)
    for batch_id, spec in BATCHES.items():
        item = plan["results"][batch_id]
        print(f"{spec['instrument']:10} {spec['year']} | batch={batch_id:2} | rows={item['rows']} | overlaps={item['overlaps']} | new={item['new']} | map={item['mapping_code']}")
    print(f"Combined staged records : {plan['total_rows']:,}")
    print(f"Canonical overlaps      : {plan['total_overlaps']:,}")
    print(f"New dates               : {plan['total_new']:,}")
    print("Overlap mismatches      : 0")
    print(f"Registered weekend dates: {plan['weekend_dates']}")

    print("\nPROPOSED COMPOSITE SNAPSHOT")
    print("-" * 112)
    print(f"New import batch ID              : {plan['next_batch_id']}")
    print(f"Parent batch preserved           : {PARENT_BATCH_ID}")
    print(f"Replacement window               : {START_DATE} to {END_DATE}")
    print(f"Instruments replaced              : BANKNIFTY, FINNIFTY, MIDCPNIFTY, INDIA_VIX")
    print(f"External NSE rows to add           : {plan['total_rows']:,}")
    print(f"Parent legacy rows omitted         : {plan['total_overlaps']:,}")
    print(f"New dates beyond parent            : {plan['total_new']:,}")
    print(f"Expected raw records               : {plan['expected_new']['raw']:,}")
    print(f"Expected quality assessments       : {plan['expected_new']['quality']:,}")
    print(f"Expected daily close records       : {plan['expected_new']['close']:,}")
    print(f"Expected full-OHLC records         : {plan['expected_new']['ohlc']:,}")
    print("\nEXPECTED PER-INSTRUMENT COUNTS (raw / close / full OHLC)")
    for instrument, values in plan["expected_new_instruments"].items():
        print(f"  {instrument:10}: {values['raw']:,} / {values['close']:,} / {values['ohlc']:,}")
    print("\nSOURCE MAPPING PLAN")
    print("  Eight year-specific mappings: pending_review -> preferred_for_period / active")
    print("  Existing BANKNIFTY/FINNIFTY/MIDCPNIFTY/INDIA_VIX legacy mappings: retained as legacy references")
    print("  Existing NIFTY50 and SENSEX preferred mappings: unchanged")
    print("\nAGGREGATE PLAN")
    print(f"  Parent batch 4 aggregates preserved: OHLC={plan['parent_agg']['ohlc']:,}; close={plan['parent_agg']['close']:,}")
    print("  New batch 5 aggregates: not copied or built by promotion; run aggregation builder afterwards")
    print("\nSOURCE CONTRIBUTION PLAN")
    print("  Parent composite snapshot batch 4 retained as the legacy snapshot contribution")
    print("  NSE external batches 1–6 retained through parent batch 4 lineage")
    print("  NSE external batches 7–14 added to new composite snapshot batch 5")
    print("  Total manifest contributions expected: 9 (parent batch 4 + eight new source files)")
    print("\nPRESERVATION")
    print("  Batches 1, 2, 3 and 4 remain untouched")
    print("  Parent daily, quality and aggregate rows remain unchanged")
    print("  Volume remains unavailable for these NSE index OHLC files")
    print("  Raw source_row_number is namespaced as external_batch_id * 1,000,000 + original CSV row number")
    print("  Original CSV row number remains unchanged in external_index_daily_records; source_id links each promoted row")
    print("\nFINAL RESULT")
    print("=" * 112)
    print(f"PROMOTION PREFLIGHT PASSED — {CHECKS} read-only checks passed; no database changes were made.")
    print("Next step: review this plan, then prepare a separate promotion apply script.")



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_backup() -> tuple[Path, str]:
    BACKUP_DIR = ROOT / "backend" / "data" / "backups"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"historical_staging_before_remaining_indices_promotion_{stamp}.db"
    if backup.exists():
        raise FileExistsError(backup)
    source = sqlite3.connect(DATABASE, timeout=120)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    check = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = check.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        check.close()
    require(integrity == "ok", f"Backup integrity failed: {integrity}.")
    require(not fk_errors, f"Backup has {len(fk_errors)} foreign-key errors.")
    return backup, hashlib.sha256(backup.read_bytes()).hexdigest()


def snapshot_counts(con: sqlite3.Connection, batch_id: int) -> dict[str, int]:
    tables = (
        "raw_daily_records", "daily_quality_assessments", "daily_close_series",
        "daily_ohlcv_analytical", "aggregated_ohlcv", "aggregated_close_series",
    )
    return {table: int(con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE import_batch_id=?", (batch_id,)
    ).fetchone()[0]) for table in tables}


def create_snapshot_manifest(
    con: sqlite3.Connection,
    new_batch_id: int,
    parent: sqlite3.Row,
    external_rows: list[sqlite3.Row],
    created_at: str,
) -> None:
    # This table is created by the earlier snapshot promotion and is required by preflight.
    con.execute(
        """INSERT INTO historical_snapshot_sources (
            snapshot_import_batch_id, source_kind, source_import_batch_id,
            external_source_batch_id, instrument_code, date_from, date_to,
            source_filename, source_sha256, selection_rule, notes, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_batch_id, "parent_composite_snapshot", PARENT_BATCH_ID, None,
            None, None, None, "composite_snapshot_batch_4", parent["source_sha256"],
            "Copy all retained daily records from parent composite snapshot batch 4, excluding only the 176 instrument-date overlap records replaced by validated NSE rows.",
            "Parent composite batch 4 carries the prior legacy, BANKNIFTY, NIFTY50 and SENSEX source lineage; its original rows and aggregates remain unchanged.",
            created_at,
        ),
    )
    for ext in external_rows:
        spec = BATCHES[int(ext["id"])]
        year = int(spec["year"])
        date_from = f"{year}-01-01"
        date_to = "2025-12-31" if year == 2025 else "2026-10-30"
        kind = "nse_india_vix_csv" if spec["instrument"] == "INDIA_VIX" else "nse_indices_csv"
        con.execute(
            """INSERT INTO historical_snapshot_sources (
                snapshot_import_batch_id, source_kind, source_import_batch_id,
                external_source_batch_id, instrument_code, date_from, date_to,
                source_filename, source_sha256, selection_rule, notes, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_batch_id, kind, None, int(ext["id"]), spec["instrument"],
                date_from, date_to, ext["source_filename"], ext["source_sha256"],
                f"Use all validated {spec['index']} daily OHLC rows for {year}; replace only matching legacy instrument-date records in this new composite snapshot.",
                f"Official NSE historical CSV; {spec['rows']} validated rows; source table provenance {spec['table']}; index volume unavailable. "
                f"Promoted raw source_row_number is namespaced as external batch ID * {SOURCE_ROW_NAMESPACE_MULTIPLIER} + original CSV row number; original row number remains in external_index_daily_records.",
                created_at,
            ),
        )


def insert_snapshot_links(
    con: sqlite3.Connection,
    new_batch_id: int,
    created_at: str,
) -> None:
    # The manifest above records precise parent lineage; this link keeps the parent
    # composite represented in the source-batch-link index as well.
    con.execute(
        """INSERT INTO historical_source_batch_links (
            link_code, source_code, import_batch_id, external_source_batch_id,
            link_role, notes, created_at_utc
        ) VALUES (?, ?, ?, ?, 'contributed_to_snapshot', ?, ?)""",
        (
            "LEGACY:IMPORT:5:CONTRIBUTION", "LEGACY_MYSQL_DUMP_20260308",
            new_batch_id, None,
            "Parent composite snapshot batch 4 retained as the base contribution; detailed multi-source lineage is recorded in historical_snapshot_sources.",
            created_at,
        ),
    )
    for batch_id, spec in BATCHES.items():
        con.execute(
            """INSERT INTO historical_source_batch_links (
                link_code, source_code, import_batch_id, external_source_batch_id,
                link_role, notes, created_at_utc
            ) VALUES (?, ?, ?, ?, 'contributed_to_snapshot', ?, ?)""",
            (
                f"NSE:SNAPSHOT:5:EXTERNAL:{batch_id}", SOURCE_CODE,
                new_batch_id, batch_id,
                f"NSE {spec['index']} {spec['year']} external CSV batch {batch_id} promoted into composite snapshot 5.",
                created_at,
            ),
        )


plan_parent_counts: dict[int, dict[str, int]] = {}


def apply_promotion() -> None:
    backup, backup_sha = make_backup()
    print(f"\nVerified database backup: {backup}")
    print(f"Backup SHA-256: {backup_sha}")

    con = sqlite3.connect(DATABASE, timeout=180)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 180000")
    try:
        con.execute("BEGIN IMMEDIATE")
        # Re-run all source and replacement checks while holding the write lock.
        plan = collect_plan(con)
        require(plan["next_batch_id"] == 5, "Target composite batch ID changed before apply.")
        print("\nTransactional preflight recheck passed; beginning composite build.")

        parent = con.execute("SELECT * FROM import_batches WHERE id=?", (PARENT_BATCH_ID,)).fetchone()
        external_rows = con.execute(
            "SELECT * FROM external_index_source_batches WHERE id IN (7,8,9,10,11,12,13,14) ORDER BY id"
        ).fetchall()
        require(len(external_rows) == 8, "Expected all eight external source batch registry rows.")

        source_fingerprint = {
            "parent_batch_id": PARENT_BATCH_ID,
            "parent_sha256": parent["source_sha256"],
            "external_batches": [
                {"id": int(r["id"]), "sha256": r["source_sha256"], "calendar_year": int(r["calendar_year"]),
                 "instrument_code": r["instrument_code"]}
                for r in external_rows
            ],
            "policy": "replace_BANKNIFTY_FINNIFTY_MIDCPNIFTY_INDIA_VIX_2025-01-01_to_2026-10-30_with_NSE_sources",
        }
        composite_hash = hashlib.sha256(
            json.dumps(source_fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source_size = int(parent["source_size_bytes"]) + sum(int(r["source_size_bytes"]) for r in external_rows)
        created_at = utc_now()

        cur = con.execute(
            """INSERT INTO import_batches (
                source_path, source_sha256, source_size_bytes,
                status, imported_rows, imported_at_utc
            ) VALUES (?, ?, ?, 'building', 0, ?)""",
            (COMPOSITE_PATH, composite_hash, source_size, created_at),
        )
        new_batch_id = int(cur.lastrowid)
        require(new_batch_id == 5, f"Inserted snapshot batch {new_batch_id}; expected 5.")

        create_snapshot_manifest(con, new_batch_id, parent, external_rows, created_at)

        # Identify exactly the 176 old instrument-date records backed by matching NSE overlaps.
        replacement_keys: set[tuple[str, str]] = set()
        for batch_id, spec in BATCHES.items():
            overlaps = con.execute(
                """SELECT candle_date FROM external_index_daily_records
                   WHERE batch_id=? AND overlap_status='ohlc_match_within_0_02'""",
                (batch_id,),
            ).fetchall()
            replacement_keys.update((spec["instrument"], str(r["candle_date"])) for r in overlaps)
        require(len(replacement_keys) == 176, f"Expected 176 unique instrument-date replacements; found {len(replacement_keys)}.")

        # Copy all parent raw records except the exact replacement keys.
        old_to_new: dict[int, int] = {}
        replaced_old_ids: set[int] = set()
        parent_raw_rows = con.execute(
            "SELECT * FROM raw_daily_records WHERE import_batch_id=? ORDER BY id",
            (PARENT_BATCH_ID,),
        ).fetchall()
        for row in parent_raw_rows:
            day = str(row["source_timestamp"] or "")[:10]
            if (row["instrument_code"], day) in replacement_keys:
                replaced_old_ids.add(int(row["id"]))
                continue
            cur = con.execute(
                """INSERT INTO raw_daily_records (
                    import_batch_id, instrument_code, source_table, source_row_number,
                    source_id, source_timestamp, open_raw, high_raw, low_raw, close_raw, volume_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, row["instrument_code"], row["source_table"], row["source_row_number"],
                 row["source_id"], row["source_timestamp"], row["open_raw"], row["high_raw"],
                 row["low_raw"], row["close_raw"], row["volume_raw"]),
            )
            old_to_new[int(row["id"])] = int(cur.lastrowid)
        require(len(replaced_old_ids) == 176, f"Replaced {len(replaced_old_ids)} parent raw records; expected 176.")

        # Copy quality assessments, preserving all original assessment decisions.
        copied_quality = 0
        quality_rows = con.execute(
            "SELECT * FROM daily_quality_assessments WHERE import_batch_id=? ORDER BY raw_record_id",
            (PARENT_BATCH_ID,),
        ).fetchall()
        for row in quality_rows:
            old_id = int(row["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = old_to_new.get(old_id)
            require(new_raw_id is not None, f"Missing raw-ID remap for quality record {old_id}.")
            con.execute(
                """INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code, source_table,
                    source_timestamp, record_status, close_eligible, full_ohlc_eligible,
                    volume_eligible, issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_raw_id, new_batch_id, row["instrument_code"], row["source_table"],
                 row["source_timestamp"], row["record_status"], row["close_eligible"],
                 row["full_ohlc_eligible"], row["volume_eligible"], row["issue_codes"],
                 row["assessed_at_utc"]),
            )
            copied_quality += 1
        require(copied_quality == plan["parent_counts"]["quality"] - 176,
                f"Copied {copied_quality} retained quality rows unexpectedly.")

        # Copy retained curated close rows, with their raw-record foreign keys remapped.
        copied_close = 0
        close_rows = con.execute(
            "SELECT * FROM daily_close_series WHERE import_batch_id=? ORDER BY instrument_code,candle_date",
            (PARENT_BATCH_ID,),
        ).fetchall()
        for row in close_rows:
            old_id = int(row["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = old_to_new.get(old_id)
            require(new_raw_id is not None, f"Missing raw-ID remap for close record {old_id}.")
            con.execute(
                """INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close, raw_record_id,
                    source_id, source_table, source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, row["instrument_code"], row["candle_date"], row["close"],
                 new_raw_id, row["source_id"], row["source_table"],
                 row["source_quality_status"], row["issue_codes"]),
            )
            copied_close += 1
        require(copied_close == plan["parent_counts"]["close"] - 176,
                f"Copied {copied_close} retained close rows unexpectedly.")

        # Copy retained curated OHLC rows, preserving their quality/volume annotations.
        copied_ohlc = 0
        ohlc_rows = con.execute(
            "SELECT * FROM daily_ohlcv_analytical WHERE import_batch_id=? ORDER BY instrument_code,candle_date",
            (PARENT_BATCH_ID,),
        ).fetchall()
        for row in ohlc_rows:
            old_id = int(row["raw_record_id"])
            if old_id in replaced_old_ids:
                continue
            new_raw_id = old_to_new.get(old_id)
            require(new_raw_id is not None, f"Missing raw-ID remap for OHLC record {old_id}.")
            con.execute(
                """INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date, open, high, low, close,
                    volume, volume_status, source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, row["instrument_code"], row["candle_date"], row["open"],
                 row["high"], row["low"], row["close"], row["volume"], row["volume_status"],
                 row["source_volume_raw"], new_raw_id, row["source_id"], row["source_table"],
                 row["quality_status"], row["issue_codes"]),
            )
            copied_ohlc += 1
        require(copied_ohlc == plan["parent_counts"]["ohlc"] - 176,
                f"Copied {copied_ohlc} retained OHLC rows unexpectedly.")

        # Promote the 1,816 validated NSE OHLC records with table-specific provenance.
        external_rows = con.execute(
            """SELECT r.id AS external_record_id, r.batch_id, b.calendar_year,
                      r.source_row_number, r.instrument_code, r.source_index_name,
                      r.candle_date, r.open_raw, r.high_raw, r.low_raw, r.close_raw,
                      r.open, r.high, r.low, r.close
               FROM external_index_daily_records r
               JOIN external_index_source_batches b ON b.id=r.batch_id
               WHERE r.batch_id IN (7,8,9,10,11,12,13,14)
               ORDER BY r.instrument_code, r.candle_date, r.batch_id"""
        ).fetchall()
        require(len(external_rows) == 1816, f"Found {len(external_rows)} external rows to promote; expected 1,816.")
        mapping = {batch_id: spec for batch_id, spec in BATCHES.items()}
        issue_codes = json.dumps(["nse_indices_historical_source", "volume_unavailable"], separators=(",", ":"))
        inserted_per_batch: dict[int, int] = {batch_id: 0 for batch_id in BATCHES}
        for row in external_rows:
            batch_id = int(row["batch_id"])
            spec = mapping[batch_id]
            instrument = spec["instrument"]
            year = int(spec["year"])
            source_table = spec["table"]
            source_id = f"NSE_EXT:{int(row['external_record_id'])}"
            source_timestamp = f"{row['candle_date']} 00:00:00"
            cur = con.execute(
                """INSERT INTO raw_daily_records (
                    import_batch_id, instrument_code, source_table, source_row_number,
                    source_id, source_timestamp, open_raw, high_raw, low_raw, close_raw, volume_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_batch_id, instrument, source_table,
                 namespaced_source_row_number(batch_id, int(row["source_row_number"])),
                 source_id, source_timestamp, row["open_raw"], row["high_raw"],
                 row["low_raw"], row["close_raw"], None),
            )
            new_raw_id = int(cur.lastrowid)
            con.execute(
                """INSERT INTO daily_quality_assessments (
                    raw_record_id, import_batch_id, instrument_code, source_table,
                    source_timestamp, record_status, close_eligible, full_ohlc_eligible,
                    volume_eligible, issue_codes, assessed_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'accepted', 1, 1, 0, ?, ?)""",
                (new_raw_id, new_batch_id, instrument, source_table, source_timestamp, issue_codes, created_at),
            )
            con.execute(
                """INSERT INTO daily_close_series (
                    import_batch_id, instrument_code, candle_date, close, raw_record_id,
                    source_id, source_table, source_quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', ?)""",
                (new_batch_id, instrument, row["candle_date"], row["close"],
                 new_raw_id, source_id, source_table, issue_codes),
            )
            con.execute(
                """INSERT INTO daily_ohlcv_analytical (
                    import_batch_id, instrument_code, candle_date, open, high, low, close,
                    volume, volume_status, source_volume_raw, raw_record_id, source_id,
                    source_table, quality_status, issue_codes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'unavailable', NULL, ?, ?, ?, 'accepted', ?)""",
                (new_batch_id, instrument, row["candle_date"], row["open"], row["high"],
                 row["low"], row["close"], new_raw_id, source_id, source_table, issue_codes),
            )
            inserted_per_batch[batch_id] += 1

        for batch_id, spec in BATCHES.items():
            require(inserted_per_batch[batch_id] == int(spec["rows"]),
                    f"Promoted external batch {batch_id}: {inserted_per_batch[batch_id]} rows; expected {spec['rows']}.")

        actual_counts = {
            "raw": count(con, "raw_daily_records", new_batch_id),
            "quality": count(con, "daily_quality_assessments", new_batch_id),
            "close": count(con, "daily_close_series", new_batch_id),
            "ohlc": count(con, "daily_ohlcv_analytical", new_batch_id),
        }
        require(actual_counts == plan["expected_new"],
                f"New snapshot counts differ: actual={actual_counts}; expected={plan['expected_new']}.")
        for instrument, expected in EXPECTED_NEW_INSTRUMENTS.items():
            actual = {
                "raw": count(con, "raw_daily_records", new_batch_id, instrument),
                "close": count(con, "daily_close_series", new_batch_id, instrument),
                "ohlc": count(con, "daily_ohlcv_analytical", new_batch_id, instrument),
            }
            require(actual == expected,
                    f"New {instrument} counts differ: actual={actual}; expected={expected}.")

        # Verify source-table-specific counts and latest dates for every promoted instrument.
        for batch_id, spec in BATCHES.items():
            table_rows = int(con.execute(
                "SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=? AND instrument_code=? AND source_table=?",
                (new_batch_id, spec["instrument"], spec["table"]),
            ).fetchone()[0])
            require(table_rows == int(spec["rows"]),
                    f"{spec['instrument']} {spec['year']} source-table count={table_rows}; expected={spec['rows']}.")
        duplicate_raw_keys = con.execute(
            """SELECT source_table, source_row_number, COUNT(*) AS n
               FROM raw_daily_records WHERE import_batch_id=?
               GROUP BY source_table, source_row_number HAVING COUNT(*) > 1
               LIMIT 5""",
            (new_batch_id,),
        ).fetchall()
        require(not duplicate_raw_keys,
                f"New snapshot has duplicate (source_table, source_row_number) keys: {[tuple(r) for r in duplicate_raw_keys]}.")

        for instrument in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIA_VIX"):
            latest = con.execute(
                "SELECT MAX(candle_date) FROM daily_ohlcv_analytical WHERE import_batch_id=? AND instrument_code=?",
                (new_batch_id, instrument),
            ).fetchone()[0]
            require(latest == END_DATE, f"Unexpected latest {instrument} OHLC date: {latest}.")

        missing_quality = int(con.execute(
            """SELECT COUNT(*) FROM raw_daily_records r
               LEFT JOIN daily_quality_assessments q ON q.raw_record_id=r.id
               WHERE r.import_batch_id=? AND q.raw_record_id IS NULL""",
            (new_batch_id,),
        ).fetchone()[0])
        require(missing_quality == 0, f"New snapshot has {missing_quality} raw rows without quality assessments.")

        # Activate the eight exact table/year mappings only after successful row-level checks.
        activated = 0
        for batch_id, spec in BATCHES.items():
            code = mapping_code(spec)
            start = f"{spec['year']}-01-01"
            end = "2025-12-31" if spec["year"] == 2025 else "2026-10-30"
            notes = (
                f"Official NSE daily OHLC for {spec['index']} ({spec['instrument']}); "
                f"{spec['rows']} validated {spec['year']} rows promoted into composite snapshot batch 5. "
                f"Source-table provenance: {spec['table']}. Price overlap reconciliation passed within {TOLERANCE:.2f} points. "
                "No index-volume field was supplied. Annual exchange-session completeness is not asserted."
            )
            con.execute(
                """UPDATE historical_instrument_source_mappings
                   SET mapping_role='preferred_for_period', mapping_status='active',
                       valid_from=?, valid_to=?, priority=10, notes=?, updated_at_utc=?
                   WHERE mapping_code=? AND mapping_status='pending_review' AND mapping_role='pending_review'""",
                (start, end, notes, created_at, code),
            )
            changed = int(con.execute("SELECT changes()").fetchone()[0])
            require(changed == 1, f"Mapping {code} was not activated exactly once (changes={changed}).")
            activated += changed
        require(activated == 8, f"Activated {activated} mappings; expected 8.")

        # Append source-batch lineage without discarding prior NSE source metadata.
        source_row = con.execute(
            "SELECT metadata_json FROM historical_data_sources WHERE source_code=?", (SOURCE_CODE,)
        ).fetchone()
        require(source_row is not None, "NSE source-registry row disappeared during promotion.")
        source_meta = json.loads(source_row["metadata_json"] or "{}")
        prior_external = source_meta.get("external_source_batch_ids", [])
        if not isinstance(prior_external, list):
            prior_external = []
        source_meta["external_source_batch_ids"] = sorted({int(x) for x in prior_external} | set(BATCHES))
        prior_snapshots = source_meta.get("composite_snapshot_batch_ids", [])
        if not isinstance(prior_snapshots, list):
            prior_snapshots = []
        snapshot_ids = {int(x) for x in prior_snapshots}
        if source_meta.get("composite_snapshot_batch_id") is not None:
            snapshot_ids.add(int(source_meta["composite_snapshot_batch_id"]))
        snapshot_ids.add(new_batch_id)
        source_meta["composite_snapshot_batch_ids"] = sorted(snapshot_ids)
        source_meta["composite_snapshot_batch_id"] = new_batch_id
        con.execute(
            "UPDATE historical_data_sources SET metadata_json=?, updated_at_utc=? WHERE source_code=?",
            (json.dumps(source_meta, sort_keys=True), created_at, SOURCE_CODE),
        )

        insert_snapshot_links(con, new_batch_id, created_at)

        # Ensure each raw row in the new snapshot has exactly one active, date-valid source mapping.
        unmapped = int(con.execute(
            """SELECT COUNT(*) FROM raw_daily_records r
               WHERE r.import_batch_id=? AND NOT EXISTS (
                   SELECT 1 FROM historical_instrument_source_mappings m
                   WHERE m.instrument_code=r.instrument_code AND m.source_table=r.source_table
                     AND m.timeframe='1D' AND m.mapping_status='active'
                     AND (m.valid_from IS NULL OR date(r.source_timestamp)>=m.valid_from)
                     AND (m.valid_to IS NULL OR date(r.source_timestamp)<=m.valid_to)
               )""",
            (new_batch_id,),
        ).fetchone()[0])
        require(unmapped == 0, f"New snapshot has {unmapped} raw records without an active date-valid source mapping.")

        # The four promoted instruments must now show NSE preferred mappings for both years.
        for batch_id, spec in BATCHES.items():
            code = mapping_code(spec)
            row = con.execute(
                "SELECT mapping_role, mapping_status FROM historical_instrument_source_mappings WHERE mapping_code=?",
                (code,),
            ).fetchone()
            require(row is not None and row["mapping_role"] == "preferred_for_period" and row["mapping_status"] == "active",
                    f"Activated mapping state is incorrect for {code}.")

        insert_count = int(con.execute(
            "SELECT COUNT(*) FROM historical_snapshot_sources WHERE snapshot_import_batch_id=?",
            (new_batch_id,),
        ).fetchone()[0])
        require(insert_count == 9, f"Snapshot source manifest rows={insert_count}; expected 9.")
        link_count = int(con.execute(
            "SELECT COUNT(*) FROM historical_source_batch_links WHERE import_batch_id=? AND link_role='contributed_to_snapshot'",
            (new_batch_id,),
        ).fetchone()[0])
        require(link_count == 9, f"Snapshot contribution links={link_count}; expected 9.")

        # Older snapshots and the parent aggregates are immutable across promotion.
        for batch_id in (1, 2, 3, 4):
            old_counts = snapshot_counts(con, batch_id)
            require(old_counts == plan_parent_counts[batch_id],
                    f"Prior snapshot batch {batch_id} changed: {old_counts} vs {plan_parent_counts[batch_id]}.")
        require(snapshot_counts(con, PARENT_BATCH_ID)["aggregated_ohlcv"] == EXPECTED_PARENT_AGG["ohlc"] and
                snapshot_counts(con, PARENT_BATCH_ID)["aggregated_close_series"] == EXPECTED_PARENT_AGG["close"],
                "Parent batch 4 aggregate counts changed unexpectedly.")
        require(count(con, "aggregated_ohlcv", new_batch_id) == 0 and
                count(con, "aggregated_close_series", new_batch_id) == 0,
                "New snapshot unexpectedly contains aggregate rows before the rebuild step.")

        con.execute(
            "UPDATE import_batches SET status='completed', imported_rows=?, imported_at_utc=? WHERE id=?",
            (actual_counts["raw"], created_at, new_batch_id),
        )
        require(int(con.execute("SELECT changes()").fetchone()[0]) == 1,
                "New composite snapshot did not transition to completed exactly once.")

        integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        require(integrity == "ok", f"SQLite integrity check failed: {integrity}.")
        require(not fk_errors, f"Foreign-key check found {len(fk_errors)} errors.")
        con.commit()

        print("\nFOUR-INSTRUMENT NSE COMPOSITE PROMOTION COMMITTED")
        print("=" * 112)
        print(f"New composite import_batch_id : {new_batch_id}")
        print(f"Raw records                  : {actual_counts['raw']:,}")
        print(f"Quality assessments          : {actual_counts['quality']:,}")
        print(f"Daily close records          : {actual_counts['close']:,}")
        print(f"Full OHLC records             : {actual_counts['ohlc']:,}")
        print(f"NSE records promoted          : {len(external_rows):,}")
        print(f"Source mappings activated     : {activated}")
        print(f"Snapshot source manifest rows : {insert_count}")
        print(f"Contribution links            : {link_count}")
        print("Parent batches 1–4            : preserved unchanged")
        print(f"Parent batch 4 aggregates     : OHLC={EXPECTED_PARENT_AGG['ohlc']:,}; close={EXPECTED_PARENT_AGG['close']:,}")
        print("New batch aggregates          : not built; run aggregation builder next")
        print("Index volume                  : unavailable; no source volume imported")
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
    parser = argparse.ArgumentParser(description="Promote NSE BANKNIFTY, FINNIFTY, MIDCPNIFTY and INDIA_VIX history into a new composite snapshot.")
    parser.add_argument("--apply", action="store_true", help="Create a verified backup and transactionally promote. Default is read-only dry run.")
    args = parser.parse_args()
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    with connect_readonly(DATABASE) as con:
        plan = collect_plan(con)
    print_plan(plan)

    if not args.apply:
        print("\nDRY RUN ONLY — no database changes or backup created.")
        print("After reviewing the plan, apply with:")
        print("python scripts\\promote_remaining_indices_nse_snapshot.py --apply")
        return 0

    # Capture counts for all previous snapshots before opening the write transaction.
    with connect_readonly(DATABASE) as con:
        plan_parent_counts = {batch_id: snapshot_counts(con, batch_id) for batch_id in (1, 2, 3, 4)}
    print("\nApply requested. A verified database backup will be created before the write transaction.")
    # Inject the unchanged baseline into module-level state used by transactional post-checks.
    globals()["plan_parent_counts"] = plan_parent_counts
    apply_promotion()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
