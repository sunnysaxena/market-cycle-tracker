#!/usr/bin/env python3
"""Read-only historical data quality and provenance auditor for Market Cycle Tracker.

Audits one completed snapshot batch. It never changes SQLite records.
CSV reports are written to backend/data/audit_reports by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
DEFAULT_OUTPUT = ROOT / "backend" / "data" / "audit_reports"
FLOAT_TOLERANCE = 1e-6
CLOSE_TOLERANCE = 0.01


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit of daily history, source provenance and aggregates."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--batch-id", type=int, default=None,
                        help="Completed snapshot batch to audit (default: latest completed).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Source timestamps in this database are ISO-like; accept date-only too.
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def period_info(d: date, timeframe: str) -> tuple[date, date]:
    if timeframe == "1W":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if timeframe == "1M":
        start = date(d.year, d.month, 1)
        if d.month == 12:
            next_month = date(d.year + 1, 1, 1)
        else:
            next_month = date(d.year, d.month + 1, 1)
        return start, next_month - timedelta(days=1)
    if timeframe == "1Y":
        return date(d.year, 1, 1), date(d.year, 12, 31)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def finite_number(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def close_enough(a: Any, b: Any, tol: float = FLOAT_TOLERANCE) -> bool:
    return finite_number(a) and finite_number(b) and abs(float(a) - float(b)) <= tol


def add_issue(
    issues: list[dict[str, Any]],
    *, severity: str, category: str, instrument: str = "",
    candle_date: str = "", timeframe: str = "1D",
    code: str, detail: str, source_table: str = "",
) -> None:
    issues.append({
        "severity": severity,
        "category": category,
        "instrument_code": instrument,
        "candle_date": candle_date,
        "timeframe": timeframe,
        "issue_code": code,
        "source_table": source_table,
        "detail": detail,
    })


def main() -> int:
    args = parse_args()
    con = connect_readonly(args.database)
    run_time = datetime.now(timezone.utc).isoformat()
    try:
        required_tables = [
            "import_batches", "raw_daily_records", "daily_quality_assessments",
            "daily_close_series", "daily_ohlcv_analytical",
            "aggregated_close_series", "aggregated_ohlcv",
            "historical_data_sources", "historical_instrument_source_mappings",
            "historical_source_batch_links", "exchange_calendar_years",
            "exchange_calendar_events",
        ]
        missing_tables = [t for t in required_tables if not table_exists(con, t)]
        if missing_tables:
            raise RuntimeError("Required tables missing: " + ", ".join(missing_tables))

        if args.batch_id is None:
            batch = con.execute("""
                SELECT id, status, imported_rows, source_path, source_sha256
                FROM import_batches
                WHERE status = 'completed'
                ORDER BY id DESC LIMIT 1
            """).fetchone()
        else:
            batch = con.execute("""
                SELECT id, status, imported_rows, source_path, source_sha256
                FROM import_batches WHERE id = ?
            """, (args.batch_id,)).fetchone()
        if batch is None:
            raise RuntimeError("No matching import batch found.")
        if batch["status"] != "completed":
            raise RuntimeError(f"Batch {batch['id']} is not completed: {batch['status']}")
        batch_id = int(batch["id"])

        print("\nMARKET CYCLE TRACKER — HISTORICAL DATA QUALITY AUDIT")
        print("=" * 88)
        print(f"Database       : {args.database.resolve()}")
        print(f"Snapshot batch : {batch_id}")
        print(f"Batch rows     : {batch['imported_rows']}")
        print("Mode           : READ-ONLY")
        print(f"Started (UTC)  : {run_time}")

        issues: list[dict[str, Any]] = []
        gap_rows: list[dict[str, Any]] = []
        mapping_audit: list[dict[str, Any]] = []
        aggregate_audit: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []

        raw_rows = con.execute("""
            SELECT id, instrument_code, source_table, source_row_number,
                   source_id, source_timestamp, open_raw, high_raw, low_raw,
                   close_raw, volume_raw
            FROM raw_daily_records
            WHERE import_batch_id = ?
            ORDER BY instrument_code, source_timestamp, id
        """, (batch_id,)).fetchall()
        raw_by_instrument: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in raw_rows:
            raw_by_instrument[row["instrument_code"]].append(row)

        quality_rows = con.execute("""
            SELECT raw_record_id, instrument_code, source_table, source_timestamp,
                   record_status, close_eligible, full_ohlc_eligible,
                   volume_eligible, issue_codes
            FROM daily_quality_assessments
            WHERE import_batch_id = ?
        """, (batch_id,)).fetchall()
        quality_by_id = {r["raw_record_id"]: r for r in quality_rows}

        close_rows = con.execute("""
            SELECT instrument_code, candle_date, close, raw_record_id,
                   source_table, source_quality_status, issue_codes
            FROM daily_close_series
            WHERE import_batch_id = ?
            ORDER BY instrument_code, candle_date
        """, (batch_id,)).fetchall()
        close_by_inst: dict[str, dict[str, sqlite3.Row]] = defaultdict(dict)
        for row in close_rows:
            close_by_inst[row["instrument_code"]][row["candle_date"]] = row

        ohlc_rows = con.execute("""
            SELECT instrument_code, candle_date, open, high, low, close,
                   volume, volume_status, source_volume_raw, raw_record_id,
                   source_table, quality_status, issue_codes
            FROM daily_ohlcv_analytical
            WHERE import_batch_id = ?
            ORDER BY instrument_code, candle_date
        """, (batch_id,)).fetchall()
        ohlc_by_inst: dict[str, dict[str, sqlite3.Row]] = defaultdict(dict)
        for row in ohlc_rows:
            ohlc_by_inst[row["instrument_code"]][row["candle_date"]] = row

        instruments = sorted(set(raw_by_instrument) | set(close_by_inst) | set(ohlc_by_inst))
        if not instruments:
            raise RuntimeError(f"No historical data found in batch {batch_id}.")

        source_mappings = con.execute("""
            SELECT mapping_id, mapping_code, source_code, instrument_code,
                   source_symbol, source_table, timeframe, mapping_role,
                   valid_from, valid_to, priority, mapping_status
            FROM historical_instrument_source_mappings
            WHERE mapping_status = 'active' AND timeframe = '1D'
            ORDER BY instrument_code, priority, mapping_id
        """).fetchall()
        mappings_by_inst: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for m in source_mappings:
            mappings_by_inst[m["instrument_code"]].append(m)

        exchange_for_instrument = {"SENSEX": "BSE"}
        # All other instruments in this initial registry are NSE indices.
        exchange_years = {
            (r["exchange"], int(r["calendar_year"])): r
            for r in con.execute("""
                SELECT exchange, market_segment, calendar_year,
                       verification_level, coverage_status, source_title
                FROM exchange_calendar_years
                WHERE market_segment = 'EQUITY'
            """).fetchall()
        }
        calendar_events: dict[tuple[str, str], sqlite3.Row] = {}
        for event in con.execute("""
            SELECT exchange, session_date, event_type, event_name,
                   verification_level
            FROM exchange_calendar_events
            WHERE market_segment = 'EQUITY'
        """).fetchall():
            calendar_events[(event["exchange"], event["session_date"])] = event

        # --- Raw duplicates and quality assessment checks ---
        raw_date_groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for row in raw_rows:
            d = as_date(row["source_timestamp"])
            if d:
                raw_date_groups[(row["instrument_code"], d.isoformat())].append(row)
        for (instrument, d), group in raw_date_groups.items():
            if len(group) > 1:
                sources = sorted({str(r["source_table"]) for r in group})
                add_issue(issues, severity="review", category="raw_duplicates",
                          instrument=instrument, candle_date=d,
                          code="duplicate_raw_instrument_date",
                          source_table=";".join(sources),
                          detail=f"{len(group)} raw rows share this instrument/date; raw IDs="
                                 + ",".join(str(r["id"]) for r in group))

        quality_counts: dict[str, Counter] = defaultdict(Counter)
        for q in quality_rows:
            quality_counts[q["instrument_code"]][q["record_status"]] += 1
        for row in raw_rows:
            q = quality_by_id.get(row["id"])
            if q is None:
                add_issue(issues, severity="error", category="quality_assessment",
                          instrument=row["instrument_code"],
                          candle_date=str(row["source_timestamp"] or "")[:10],
                          code="missing_quality_assessment",
                          source_table=row["source_table"],
                          detail=f"Raw record {row['id']} has no assessment.")

        # --- Source registry mapping validation ---
        mapping_match_counts: Counter = Counter()
        for row in raw_rows:
            d = as_date(row["source_timestamp"])
            d_text = d.isoformat() if d else ""
            matching = []
            for m in mappings_by_inst.get(row["instrument_code"], []):
                if m["source_table"] and m["source_table"] != row["source_table"]:
                    continue
                if m["valid_from"] and d_text and d_text < m["valid_from"]:
                    continue
                if m["valid_to"] and d_text and d_text > m["valid_to"]:
                    continue
                matching.append(m)
            chosen = sorted(matching, key=lambda x: (x["priority"], x["mapping_id"]))[0] if matching else None
            mapping_audit.append({
                "raw_record_id": row["id"],
                "instrument_code": row["instrument_code"],
                "source_table": row["source_table"],
                "source_date": d_text,
                "matching_mapping_count": len(matching),
                "matched_mapping_code": chosen["mapping_code"] if chosen else "",
                "mapping_role": chosen["mapping_role"] if chosen else "",
                "mapping_status": "matched" if len(matching) == 1 else (
                    "ambiguous" if matching else "unmapped"
                ),
            })
            if not matching:
                add_issue(issues, severity="error", category="source_provenance",
                          instrument=row["instrument_code"], candle_date=d_text,
                          code="missing_source_mapping", source_table=row["source_table"],
                          detail="No active 1D source mapping matches instrument, table and date.")
            elif len(matching) > 1:
                add_issue(issues, severity="review", category="source_provenance",
                          instrument=row["instrument_code"], candle_date=d_text,
                          code="ambiguous_source_mapping", source_table=row["source_table"],
                          detail="Multiple active source mappings match this raw record: "
                                 + ",".join(m["mapping_code"] for m in matching))
            else:
                mapping_match_counts[(row["instrument_code"], chosen["mapping_role"])] += 1

        # --- Daily quality checks and candidate session gaps ---
        summary_by_inst: dict[str, dict[str, Any]] = {}
        for instrument in instruments:
            closes = close_by_inst.get(instrument, {})
            ohlc = ohlc_by_inst.get(instrument, {})
            raws = raw_by_instrument.get(instrument, [])
            dates = sorted(closes)
            exchange = exchange_for_instrument.get(instrument, "NSE")

            invalid_ohlc = 0
            flat_ohlc = 0
            close_without_ohlc = 0
            close_mismatch = 0
            volume_unavailable = 0
            return_outliers = 0

            for d, row in ohlc.items():
                vals = [row["open"], row["high"], row["low"], row["close"]]
                if not all(finite_number(v) for v in vals):
                    invalid_ohlc += 1
                    add_issue(issues, severity="error", category="daily_ohlc",
                              instrument=instrument, candle_date=d,
                              code="non_finite_or_null_ohlc",
                              source_table=row["source_table"],
                              detail=f"OHLC values are null or non-finite: {vals}")
                    continue
                opn, high, low, close = map(float, vals)
                problems = []
                if min(vals) <= 0:
                    problems.append("non_positive_price")
                if high < max(opn, close):
                    problems.append("high_below_open_or_close")
                if low > min(opn, close):
                    problems.append("low_above_open_or_close")
                if high < low:
                    problems.append("high_below_low")
                if problems:
                    invalid_ohlc += 1
                    add_issue(issues, severity="error", category="daily_ohlc",
                              instrument=instrument, candle_date=d,
                              code="invalid_ohlc_relationship",
                              source_table=row["source_table"],
                              detail=";".join(problems))
                if opn == high == low == close:
                    flat_ohlc += 1
                    add_issue(issues, severity="review", category="daily_ohlc",
                              instrument=instrument, candle_date=d,
                              code="flat_ohlc_candle_review",
                              source_table=row["source_table"],
                              detail="OHLC are all equal. Could be genuine or close-only/backfill data; review source context.")
                if row["volume"] is None or row["volume_status"] == "unavailable":
                    volume_unavailable += 1

                q = quality_by_id.get(row["raw_record_id"])
                if q and not int(q["full_ohlc_eligible"]):
                    add_issue(issues, severity="error", category="quality_assessment",
                              instrument=instrument, candle_date=d,
                              code="ohlc_curated_but_not_quality_eligible",
                              source_table=row["source_table"],
                              detail=f"Curated full OHLC row references raw record {row['raw_record_id']} whose assessment is not full-OHLC eligible.")

            for d, row in closes.items():
                full = ohlc.get(d)
                if full is None:
                    close_without_ohlc += 1
                    add_issue(issues, severity="review", category="daily_coverage",
                              instrument=instrument, candle_date=d,
                              code="close_without_full_ohlc",
                              source_table=row["source_table"],
                              detail="Close-only record has no corresponding full-OHLC analytical candle.")
                elif abs(float(row["close"]) - float(full["close"])) > CLOSE_TOLERANCE:
                    close_mismatch += 1
                    add_issue(issues, severity="error", category="daily_consistency",
                              instrument=instrument, candle_date=d,
                              code="close_series_ohlc_close_mismatch",
                              source_table=row["source_table"],
                              detail=f"Close series={row['close']}; OHLC close={full['close']}; tolerance={CLOSE_TOLERANCE}.")
                q = quality_by_id.get(row["raw_record_id"])
                if q and not int(q["close_eligible"]):
                    add_issue(issues, severity="error", category="quality_assessment",
                              instrument=instrument, candle_date=d,
                              code="close_curated_but_not_quality_eligible",
                              source_table=row["source_table"],
                              detail=f"Curated close references raw record {row['raw_record_id']} whose assessment is not close eligible.")

            # Price moves are warnings only. They never invalidate or remove candles.
            returns: list[tuple[str, float]] = []
            for idx in range(1, len(dates)):
                prev_d, current_d = dates[idx - 1], dates[idx]
                prev_close = float(closes[prev_d]["close"])
                current_close = float(closes[current_d]["close"])
                if prev_close > 0:
                    returns.append((current_d, (current_close / prev_close - 1.0) * 100.0))
            return_threshold = 25.0 if instrument == "INDIA_VIX" else 12.0
            if returns:
                vals = [r for _, r in returns]
                med = statistics.median(vals)
                mad = statistics.median([abs(v - med) for v in vals])
                robust_threshold = max(return_threshold, 10.0 * 1.4826 * mad)
                for d, pct in returns:
                    if abs(pct - med) > robust_threshold and abs(pct) >= return_threshold:
                        return_outliers += 1
                        add_issue(issues, severity="review", category="market_move",
                                  instrument=instrument, candle_date=d,
                                  code="unusual_daily_close_return",
                                  source_table=closes[d]["source_table"],
                                  detail=f"Daily close return {pct:.4f}%; median={med:.4f}%; review threshold={robust_threshold:.4f}%. This is a review alert, not an invalidation.")

            # Calendar-aware weekday gap candidates. Missing dates are never called confirmed
            # unless a loaded exchange calendar covers the year; otherwise they are candidates.
            if dates:
                first_d, last_d = as_date(dates[0]), as_date(dates[-1])
                assert first_d and last_d
                cur = first_d
                while cur <= last_d:
                    ds = cur.isoformat()
                    event = calendar_events.get((exchange, ds))
                    cal_year = exchange_years.get((exchange, cur.year))
                    present = ds in closes
                    expected = False
                    gap_type = ""
                    verification = "calendar_not_loaded"
                    calendar_detail = "No annual exchange calendar registered for this exchange/year."
                    if event and event["event_type"] == "holiday_closed":
                        expected = False
                    elif event and event["event_type"] == "special_session_open":
                        expected = True
                        gap_type = "special_session_record_missing"
                        verification = event["verification_level"]
                        calendar_detail = event["event_name"]
                    elif cur.weekday() < 5:
                        expected = True
                        if cal_year:
                            gap_type = "calendar_session_record_missing"
                            verification = cal_year["verification_level"]
                            calendar_detail = f"Annual calendar status: {cal_year['coverage_status']}"
                        else:
                            gap_type = "weekday_gap_candidate_unverified_calendar"
                    if expected and not present:
                        gap_rows.append({
                            "instrument_code": instrument,
                            "exchange": exchange,
                            "candidate_date": ds,
                            "gap_type": gap_type,
                            "calendar_verification": verification,
                            "calendar_detail": calendar_detail,
                            "classification": "candidate_not_confirmed",
                        })
                    # Uncatalogued weekend observations are logged as review, not errors.
                    if present and cur.weekday() >= 5 and event is None:
                        add_issue(issues, severity="info", category="calendar_review",
                                  instrument=instrument, candle_date=ds,
                                  code="weekend_candle_without_calendar_event",
                                  source_table=(ohlc.get(ds) or closes.get(ds))["source_table"],
                                  detail="Weekend candle exists but no matching special-session event is registered for this exchange/date.")
                    cur += timedelta(days=1)

            raw_dup_dates = sum(1 for (inst, _), group in raw_date_groups.items()
                                if inst == instrument and len(group) > 1)
            qa = quality_counts[instrument]
            summary_by_inst[instrument] = {
                "instrument_code": instrument,
                "exchange_assumption": exchange,
                "raw_records": len(raws),
                "quality_assessments": sum(qa.values()),
                "quality_accepted": qa.get("accepted", 0),
                "quality_review_required": qa.get("review_required", 0),
                "quality_quarantined": qa.get("quarantined", 0),
                "daily_close_records": len(closes),
                "daily_full_ohlc_records": len(ohlc),
                "first_daily_date": dates[0] if dates else "",
                "last_daily_date": dates[-1] if dates else "",
                "raw_duplicate_dates": raw_dup_dates,
                "invalid_ohlc_records": invalid_ohlc,
                "flat_ohlc_review_records": flat_ohlc,
                "close_without_full_ohlc": close_without_ohlc,
                "close_ohlc_mismatches": close_mismatch,
                "volume_unavailable_records": volume_unavailable,
                "unusual_return_review_alerts": return_outliers,
                "weekday_gap_candidates": sum(1 for g in gap_rows if g["instrument_code"] == instrument),
            }

        # --- Aggregation recomputation checks ---
        timeframe_names = ("1W", "1M", "1Y")
        for instrument in instruments:
            daily_ohlc = sorted(ohlc_by_inst.get(instrument, {}).items())
            daily_close = sorted(close_by_inst.get(instrument, {}).items())
            for timeframe in timeframe_names:
                expected_ohlc: dict[str, dict[str, Any]] = {}
                grouped: dict[str, list[tuple[str, sqlite3.Row]]] = defaultdict(list)
                for d_text, row in daily_ohlc:
                    d = as_date(d_text)
                    if not d:
                        continue
                    start, end = period_info(d, timeframe)
                    grouped[start.isoformat()].append((d_text, row))
                for pstart, items in grouped.items():
                    items.sort(key=lambda x: x[0])
                    expected_ohlc[pstart] = {
                        "period_end": period_info(as_date(items[0][0]), timeframe)[1].isoformat(),
                        "first_session_date": items[0][0],
                        "last_session_date": items[-1][0],
                        "open": float(items[0][1]["open"]),
                        "high": max(float(x[1]["high"]) for x in items),
                        "low": min(float(x[1]["low"]) for x in items),
                        "close": float(items[-1][1]["close"]),
                        "session_count": len(items),
                    }
                stored_ohlc_rows = con.execute("""
                    SELECT period_start, period_end, first_session_date,
                           last_session_date, open, high, low, close, session_count
                    FROM aggregated_ohlcv
                    WHERE import_batch_id = ? AND instrument_code = ? AND timeframe = ?
                    ORDER BY period_start
                """, (batch_id, instrument, timeframe)).fetchall()
                stored_ohlc = {r["period_start"]: r for r in stored_ohlc_rows}
                for pstart, expected in expected_ohlc.items():
                    stored = stored_ohlc.get(pstart)
                    status = "match"
                    details = []
                    if stored is None:
                        status = "missing_aggregate"
                        details.append("stored OHLC aggregate absent")
                    else:
                        for fld in ("period_end", "first_session_date", "last_session_date", "session_count"):
                            if stored[fld] != expected[fld]:
                                details.append(f"{fld}: stored={stored[fld]} expected={expected[fld]}")
                        for fld in ("open", "high", "low", "close"):
                            if not close_enough(stored[fld], expected[fld]):
                                details.append(f"{fld}: stored={stored[fld]} expected={expected[fld]}")
                        if details:
                            status = "aggregate_mismatch"
                    aggregate_audit.append({
                        "instrument_code": instrument, "timeframe": timeframe,
                        "series_type": "OHLC", "period_start": pstart,
                        "period_end": expected["period_end"],
                        "expected_session_count": expected["session_count"],
                        "stored_session_count": stored["session_count"] if stored else "",
                        "audit_status": status, "details": "; ".join(details),
                    })
                    if status != "match":
                        add_issue(issues, severity="error", category="aggregation",
                                  instrument=instrument, candle_date=pstart,
                                  timeframe=timeframe, code=status,
                                  detail="; ".join(details))
                for pstart, stored in stored_ohlc.items():
                    if pstart not in expected_ohlc:
                        aggregate_audit.append({
                            "instrument_code": instrument, "timeframe": timeframe,
                            "series_type": "OHLC", "period_start": pstart,
                            "period_end": stored["period_end"],
                            "expected_session_count": "",
                            "stored_session_count": stored["session_count"],
                            "audit_status": "extra_aggregate",
                            "details": "Stored aggregate has no contributing daily OHLC group.",
                        })
                        add_issue(issues, severity="error", category="aggregation",
                                  instrument=instrument, candle_date=pstart,
                                  timeframe=timeframe, code="extra_aggregate",
                                  detail="Stored OHLC aggregate has no contributing daily OHLC group.")

                expected_close: dict[str, dict[str, Any]] = {}
                close_groups: dict[str, list[tuple[str, sqlite3.Row]]] = defaultdict(list)
                for d_text, row in daily_close:
                    d = as_date(d_text)
                    if not d:
                        continue
                    start, _ = period_info(d, timeframe)
                    close_groups[start.isoformat()].append((d_text, row))
                for pstart, items in close_groups.items():
                    items.sort(key=lambda x: x[0])
                    _, end = period_info(as_date(items[0][0]), timeframe)
                    expected_close[pstart] = {
                        "period_end": end.isoformat(),
                        "first_session_date": items[0][0],
                        "last_session_date": items[-1][0],
                        "close": float(items[-1][1]["close"]),
                        "session_count": len(items),
                    }
                stored_close_rows = con.execute("""
                    SELECT period_start, period_end, first_session_date,
                           last_session_date, close, session_count
                    FROM aggregated_close_series
                    WHERE import_batch_id = ? AND instrument_code = ? AND timeframe = ?
                    ORDER BY period_start
                """, (batch_id, instrument, timeframe)).fetchall()
                stored_close = {r["period_start"]: r for r in stored_close_rows}
                for pstart, expected in expected_close.items():
                    stored = stored_close.get(pstart)
                    status = "match"
                    details = []
                    if stored is None:
                        status = "missing_aggregate"
                        details.append("stored close aggregate absent")
                    else:
                        for fld in ("period_end", "first_session_date", "last_session_date", "session_count"):
                            if stored[fld] != expected[fld]:
                                details.append(f"{fld}: stored={stored[fld]} expected={expected[fld]}")
                        if not close_enough(stored["close"], expected["close"]):
                            details.append(f"close: stored={stored['close']} expected={expected['close']}")
                        if details:
                            status = "aggregate_mismatch"
                    aggregate_audit.append({
                        "instrument_code": instrument, "timeframe": timeframe,
                        "series_type": "Close", "period_start": pstart,
                        "period_end": expected["period_end"],
                        "expected_session_count": expected["session_count"],
                        "stored_session_count": stored["session_count"] if stored else "",
                        "audit_status": status, "details": "; ".join(details),
                    })
                    if status != "match":
                        add_issue(issues, severity="error", category="aggregation",
                                  instrument=instrument, candle_date=pstart,
                                  timeframe=timeframe, code=status,
                                  detail="; ".join(details))
                for pstart, stored in stored_close.items():
                    if pstart not in expected_close:
                        aggregate_audit.append({
                            "instrument_code": instrument, "timeframe": timeframe,
                            "series_type": "Close", "period_start": pstart,
                            "period_end": stored["period_end"],
                            "expected_session_count": "",
                            "stored_session_count": stored["session_count"],
                            "audit_status": "extra_aggregate",
                            "details": "Stored close aggregate has no contributing daily close group.",
                        })
                        add_issue(issues, severity="error", category="aggregation",
                                  instrument=instrument, candle_date=pstart,
                                  timeframe=timeframe, code="extra_aggregate",
                                  detail="Stored close aggregate has no contributing daily close group.")

        # Add final aggregate counts and issue counts to instrument summary.
        for instrument in instruments:
            summary_by_inst[instrument]["aggregation_periods_checked"] = sum(
                1 for a in aggregate_audit if a["instrument_code"] == instrument
            )
            summary_by_inst[instrument]["aggregation_mismatches"] = sum(
                1 for a in aggregate_audit
                if a["instrument_code"] == instrument and a["audit_status"] != "match"
            )
            summary_by_inst[instrument]["error_issues"] = sum(
                1 for i in issues if i["instrument_code"] == instrument and i["severity"] == "error"
            )
            summary_by_inst[instrument]["review_issues"] = sum(
                1 for i in issues if i["instrument_code"] == instrument and i["severity"] == "review"
            )

        summary_rows = [summary_by_inst[i] for i in instruments]

        # Quality assessment rows without a corresponding raw record (orphaned assessment).
        raw_ids = {r["id"] for r in raw_rows}
        for q in quality_rows:
            if q["raw_record_id"] not in raw_ids:
                add_issue(issues, severity="error", category="quality_assessment",
                          instrument=q["instrument_code"],
                          candle_date=str(q["source_timestamp"] or "")[:10],
                          code="orphan_quality_assessment",
                          source_table=q["source_table"],
                          detail=f"Assessment references raw_record_id {q['raw_record_id']} not in selected batch.")

        # Registry and batch-link sanity checks for this snapshot.
        source_link_rows = con.execute("""
            SELECT l.link_code, l.source_code, l.import_batch_id,
                   l.external_source_batch_id, l.link_role
            FROM historical_source_batch_links l
            WHERE l.import_batch_id = ? OR l.external_source_batch_id IS NOT NULL
            ORDER BY l.link_code
        """, (batch_id,)).fetchall()
        valid_source_codes = {r[0] for r in con.execute(
            "SELECT source_code FROM historical_data_sources WHERE is_active = 1"
        ).fetchall()}
        for link in source_link_rows:
            if link["source_code"] not in valid_source_codes:
                add_issue(issues, severity="error", category="source_provenance",
                          code="inactive_or_missing_linked_source",
                          detail=f"Batch link {link['link_code']} points to inactive/missing source {link['source_code']}.")

        # Output reports.
        args.output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = args.output_dir / f"historical_quality_summary_batch_{batch_id}.csv"
        issues_path = args.output_dir / f"historical_quality_issues_batch_{batch_id}.csv"
        gaps_path = args.output_dir / f"historical_session_gap_candidates_batch_{batch_id}.csv"
        mapping_path = args.output_dir / f"historical_source_mapping_audit_batch_{batch_id}.csv"
        aggregate_path = args.output_dir / f"historical_aggregation_audit_batch_{batch_id}.csv"

        write_csv(summary_path, summary_rows, list(summary_rows[0].keys()) if summary_rows else ["instrument_code"])
        write_csv(issues_path, issues, [
            "severity", "category", "instrument_code", "candle_date",
            "timeframe", "issue_code", "source_table", "detail",
        ])
        write_csv(gaps_path, gap_rows, [
            "instrument_code", "exchange", "candidate_date", "gap_type",
            "calendar_verification", "calendar_detail", "classification",
        ])
        write_csv(mapping_path, mapping_audit, [
            "raw_record_id", "instrument_code", "source_table", "source_date",
            "matching_mapping_count", "matched_mapping_code", "mapping_role", "mapping_status",
        ])
        write_csv(aggregate_path, aggregate_audit, [
            "instrument_code", "timeframe", "series_type", "period_start",
            "period_end", "expected_session_count", "stored_session_count",
            "audit_status", "details",
        ])

        severity_counts = Counter(i["severity"] for i in issues)
        issue_code_counts = Counter(i["issue_code"] for i in issues)
        aggregate_status_counts = Counter(a["audit_status"] for a in aggregate_audit)
        mapping_status_counts = Counter(m["mapping_status"] for m in mapping_audit)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()

        print("\nINSTRUMENT SUMMARY")
        print("-" * 108)
        print(f"{'INSTRUMENT':<12}{'RAW':>8}{'CLOSE':>9}{'OHLC':>9}{'GAP CAND.':>12}{'OHLC ERR':>11}{'AGG MISM.':>12}")
        for s in summary_rows:
            print(
                f"{s['instrument_code']:<12}{s['raw_records']:>8}"
                f"{s['daily_close_records']:>9}{s['daily_full_ohlc_records']:>9}"
                f"{s['weekday_gap_candidates']:>12}{s['invalid_ohlc_records']:>11}"
                f"{s['aggregation_mismatches']:>12}"
            )

        print("\nISSUE SEVERITY COUNTS")
        print("-" * 65)
        for severity in ("error", "review", "info"):
            print(f"{severity}: {severity_counts.get(severity, 0)}")
        print("\nTOP ISSUE CODES")
        for code, count in issue_code_counts.most_common(15):
            print(f"{code}: {count}")

        print("\nSOURCE MAPPING AUDIT")
        for status, count in mapping_status_counts.items():
            print(f"{status}: {count}")
        print("\nAGGREGATION AUDIT")
        for status, count in aggregate_status_counts.items():
            print(f"{status}: {count}")
        print(f"Total aggregate periods compared: {len(aggregate_audit)}")
        print(f"Weekday/session gap candidates (not confirmed): {len(gap_rows)}")

        print("\nDATABASE CHECKS")
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print("Database mode: read-only; no database records modified.")

        print("\nREPORT FILES")
        for p in (summary_path, issues_path, gaps_path, mapping_path, aggregate_path):
            print(p.resolve())

        if integrity != "ok" or fk_errors:
            print("\nAUDIT WARNING: Database integrity checks reported a problem.")
            return 2
        print("\nAudit completed. Review issues and gap candidates; no automatic corrections were made.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nAUDIT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
