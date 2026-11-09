#!/usr/bin/env python3
"""Read-only promotion preflight for BANKNIFTY, FINNIFTY, MIDCPNIFTY and INDIA_VIX.

The script validates staged NSE external batches 7-14 and computes the proposed
composite snapshot counts. It intentionally has no --apply mode and never writes
to the SQLite database.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
INPUT_DIR = ROOT / "backend" / "data" / "incoming"
PARENT_BATCH_ID = 4
SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"
START_DATE = "2025-01-01"
END_DATE = "2026-10-30"
TOLERANCE = 0.02

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
    require(prior_target is None,
            f"Target composite snapshot already exists as batch {prior_target['id']}.")
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
    print("\nFINAL RESULT")
    print("=" * 112)
    print(f"PROMOTION PREFLIGHT PASSED — {CHECKS} read-only checks passed; no database changes were made.")
    print("Next step: review this plan, then prepare a separate promotion apply script.")


def main() -> int:
    print("NSE FOUR-INSTRUMENT COMPOSITE PROMOTION PREFLIGHT")
    print("=" * 112)
    print(f"Database: {DATABASE}")
    print(f"Parent snapshot: batch {PARENT_BATCH_ID}")
    print("External source batches: 7–14")
    print("Mode: READ-ONLY; no database changes will be made")
    try:
        with connect_readonly(DATABASE) as con:
            plan = collect_plan(con)
        print_plan(plan)
        return 0
    except Exception as exc:
        print(f"\nPREFLIGHT FAILED: {exc}", file=sys.stderr)
        print("No database changes were made.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
