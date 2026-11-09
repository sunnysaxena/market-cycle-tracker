#!/usr/bin/env python3
"""Read-only validation of 2025-2026 NSE daily OHLC CSVs for four indices.

Files expected under backend/data/incoming:
  banknifty_nse_2025.csv, banknifty_nse_2026.csv
  finnifty_nse_2025.csv, finnifty_nse_2026.csv
  midcpnifty_nse_2025.csv, midcpnifty_nse_2026.csv
  indiavix_nse_2025.csv, indiavix_nse_2026.csv

The three equity index files use the NSE Indices "Index Name, Date, Open..."
format. INDIA_VIX uses the separate "Date, Open, High, Low, Close, ..."
format. The script reads CSV files and snapshot batch 4 through a read-only
SQLite connection. It does not import, stage, repair, or modify database rows.

A per-date CSV report is written to backend/data/audit_reports/.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "backend" / "data" / "incoming"
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
REPORT = ROOT / "backend" / "data" / "audit_reports" / "remaining_indices_nse_2025_2026_validation_batch_4.csv"
BATCH_ID = 4
TOLERANCE = 0.02  # index points; differences are reported, never auto-corrected
YEARS = {
    2025: (date(2025, 1, 1), date(2025, 12, 31)),
    2026: (date(2026, 1, 1), date(2026, 10, 30)),
}

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "BANKNIFTY": {"prefix": "banknifty", "index_name": "NIFTY BANK", "format": "nse_index"},
    "FINNIFTY": {"prefix": "finnifty", "index_name": "NIFTY FINANCIAL SERVICES", "format": "nse_index"},
    "MIDCPNIFTY": {"prefix": "midcpnifty", "index_name": "NIFTY MIDCAP SELECT", "format": "nse_index"},
    "INDIA_VIX": {"prefix": "indiavix", "index_name": None, "format": "india_vix"},
}
OHLC_FIELDS = ("open", "high", "low", "close")
DATE_FORMATS = (
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%d-%b-%y",
    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y%m%d", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
)


def normalize_header(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def normalize_index_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def parse_date(value: str | None) -> date:
    text = (value or "").strip().strip('"').strip()
    if not text:
        raise ValueError("blank date")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"unsupported date format: {text!r}") from exc


def parse_number(value: str | None, field: str) -> float:
    text = (value or "").strip().strip('"').strip().replace(",", "")
    if text.upper() in {"", "-", "—", "NA", "N/A", "NULL", "NONE"}:
        raise ValueError(f"missing {field}")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"non-finite {field}")
    return number


def valid_ohlc(values: dict[str, float]) -> str | None:
    o, h, l, c = (values[k] for k in OHLC_FIELDS)
    if min(o, h, l, c) <= 0:
        return "OHLC values must all be positive"
    if h + 1e-9 < max(o, c, l):
        return "high is below open, close or low"
    if l - 1e-9 > min(o, c, h):
        return "low is above open, close or high"
    return None


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def open_readonly_db() -> sqlite3.Connection:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")
    conn = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def load_existing(conn: sqlite3.Connection, instrument: str) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    ohlc_rows = conn.execute("""
        SELECT candle_date, open, high, low, close
        FROM daily_ohlcv_analytical
        WHERE import_batch_id = ? AND instrument_code = ?
          AND candle_date BETWEEN '2025-01-01' AND '2026-10-30'
    """, (BATCH_ID, instrument)).fetchall()
    close_rows = conn.execute("""
        SELECT candle_date, close
        FROM daily_close_series
        WHERE import_batch_id = ? AND instrument_code = ?
          AND candle_date BETWEEN '2025-01-01' AND '2026-10-30'
    """, (BATCH_ID, instrument)).fetchall()
    ohlc = {
        row["candle_date"]: {k: float(row[k]) for k in OHLC_FIELDS}
        for row in ohlc_rows
    }
    closes = {row["candle_date"]: float(row["close"]) for row in close_rows}
    return ohlc, closes


def load_calendar(conn: sqlite3.Connection) -> tuple[dict[str, tuple[str, str]], set[str], set[str]]:
    rows = conn.execute("""
        SELECT session_date, event_type, event_name
        FROM exchange_calendar_events
        WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
          AND session_date BETWEEN '2025-01-01' AND '2026-12-31'
    """).fetchall()
    events: dict[str, tuple[str, str]] = {}
    special: set[str] = set()
    holidays: set[str] = set()
    for row in rows:
        d = row["session_date"]
        events[d] = (row["event_type"], row["event_name"] or "")
        if row["event_type"] == "special_session_open":
            special.add(d)
        elif row["event_type"] == "holiday_closed":
            holidays.add(d)
    return events, special, holidays


def find_column(headers: list[str], aliases: set[str], required_name: str) -> int:
    normalized = [normalize_header(h) for h in headers]
    for idx, name in enumerate(normalized):
        if name in aliases:
            return idx
    raise ValueError(f"missing required {required_name} column; headers={headers}")


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]], str]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing expected CSV: {path}")
    raw = path.read_bytes()
    text = None
    encoding_used = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnicodeError(f"Could not decode {path.name}")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(text.splitlines(), dialect))
    # Find the header in the first 20 lines to tolerate an occasional report title.
    header_idx = None
    for idx, row in enumerate(rows[:20]):
        norm = {normalize_header(cell) for cell in row}
        if {"date", "open", "high", "low", "close"}.issubset(norm):
            if "indexname" in norm or "date" in norm:
                header_idx = idx
                break
    if header_idx is None:
        raise ValueError(f"Could not locate Date/Open/High/Low/Close header in {path.name}; first lines={rows[:3]}")
    return rows[header_idx], rows[header_idx + 1:], encoding_used or "unknown"


def parse_file(instrument: str, year: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = INSTRUMENTS[instrument]
    path = INCOMING / f"{cfg['prefix']}_nse_{year}.csv"
    headers, rows, encoding = read_csv_rows(path)
    col = {
        key: find_column(headers, aliases, key)
        for key, aliases in {
            "date": {"date", "indexdate", "tradingdate", "timestamp", "tradedate"},
            "open": {"open", "openindexvalue", "openvalue", "openprice"},
            "high": {"high", "highindexvalue", "highvalue", "highprice"},
            "low": {"low", "lowindexvalue", "lowvalue", "lowprice"},
            "close": {"close", "closeindexvalue", "closingindexvalue", "closingvalue", "closeprice", "closingprice"},
        }.items()
    }
    index_col = None
    if cfg["format"] == "nse_index":
        index_col = find_column(headers, {"indexname"}, "Index Name")
    elif cfg["format"] == "india_vix":
        # INDIA_VIX export intentionally has no Index Name field.
        pass

    file_hash, file_size = sha256_file(path)
    expected_start, expected_end = YEARS[year]
    parsed: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    blank_rows = 0
    wrong_names: Counter[str] = Counter()
    wrong_year_rows = 0
    outside_window_rows = 0
    non_data_lines = 0

    for line_no, row in enumerate(rows, start=2):
        if not row or not any((cell or "").strip() for cell in row):
            blank_rows += 1
            continue
        # Ignore common footer lines that do not contain a parseable date.
        if col["date"] >= len(row):
            non_data_lines += 1
            continue
        try:
            d = parse_date(row[col["date"]])
        except ValueError:
            non_data_lines += 1
            continue
        try:
            values = {k: parse_number(row[col[k]] if col[k] < len(row) else None, k) for k in OHLC_FIELDS}
            issue = valid_ohlc(values)
        except ValueError as exc:
            values = {k: None for k in OHLC_FIELDS}
            issue = str(exc)
        index_name = "INDIA VIX" if index_col is None else (row[index_col].strip() if index_col < len(row) else "")
        if index_col is not None and normalize_index_name(index_name) != normalize_index_name(cfg["index_name"]):
            wrong_names[index_name] += 1
        if d.year != year:
            wrong_year_rows += 1
        if d < expected_start or d > expected_end:
            outside_window_rows += 1
        parsed.append({
            "instrument": instrument,
            "year_file": year,
            "date": d.isoformat(),
            "index_name": index_name,
            **values,
            "ohlc_issue": issue,
            "source_file": path.name,
            "source_line": line_no,
        })
        if issue and len(parse_errors) < 10:
            parse_errors.append(f"line {line_no}: {issue}")

    date_counts = Counter(r["date"] for r in parsed)
    duplicate_dates = sorted(d for d, n in date_counts.items() if n > 1)
    good = [r for r in parsed if r["ohlc_issue"] is None]
    dates = [r["date"] for r in parsed]
    info = {
        "instrument": instrument,
        "year": year,
        "file": path.name,
        "sha256": file_hash,
        "size_bytes": file_size,
        "encoding": encoding,
        "headers": headers,
        "rows": len(parsed),
        "blank_rows": blank_rows,
        "non_data_lines": non_data_lines,
        "valid_ohlc_rows": len(good),
        "invalid_ohlc_rows": len(parsed) - len(good),
        "wrong_index_name_rows": sum(wrong_names.values()),
        "wrong_index_names": dict(wrong_names),
        "wrong_year_rows": wrong_year_rows,
        "outside_window_rows": outside_window_rows,
        "unique_dates": len(set(dates)),
        "duplicate_date_groups": len(duplicate_dates),
        "duplicate_dates": duplicate_dates,
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
        "expected_start": expected_start.isoformat(),
        "expected_end": expected_end.isoformat(),
        "sample_issues": parse_errors,
    }
    return parsed, info


def main() -> int:
    print("\nNSE HISTORICAL CSV VALIDATION — BANKNIFTY / FINNIFTY / MIDCPNIFTY / INDIA_VIX")
    print("=" * 104)
    print(f"Input folder : {INCOMING}")
    print(f"Database     : {DATABASE}")
    print(f"Snapshot     : batch {BATCH_ID}")
    print("Mode         : CSV read + SQLite read-only; no staging, import, or database changes")
    print(f"Overlap tolerance: {TOLERANCE:.2f} index points")
    print("Expected CSVs: 8 files (2025 and 2026 for each of four instruments)")

    conn = open_readonly_db()
    try:
        batch = conn.execute("SELECT id, status FROM import_batches WHERE id = ?", (BATCH_ID,)).fetchone()
        if batch is None or batch["status"] != "completed":
            raise RuntimeError(f"Snapshot batch {BATCH_ID} is missing or not completed")
        calendar_events, special_dates, holiday_dates = load_calendar(conn)

        all_records: list[dict[str, Any]] = []
        file_infos: list[dict[str, Any]] = []
        existing_by_instrument: dict[str, tuple[dict[str, dict[str, float]], dict[str, float]]] = {}
        for instrument in INSTRUMENTS:
            existing_by_instrument[instrument] = load_existing(conn, instrument)
            for year in YEARS:
                records, info = parse_file(instrument, year)
                all_records.extend(records)
                file_infos.append(info)

        print("\nFILE VALIDATION")
        print("-" * 104)
        structural_failures = 0
        for info in file_infos:
            print(f"\n{info['file']} | instrument={info['instrument']} | expected={info['expected_start']}..{info['expected_end']}")
            print(f"  SHA-256: {info['sha256']}")
            print(f"  Size/encoding: {info['size_bytes']:,} bytes / {info['encoding']}")
            print(f"  Parsed rows / unique dates: {info['rows']} / {info['unique_dates']}")
            print(f"  Valid / invalid OHLC rows: {info['valid_ohlc_rows']} / {info['invalid_ohlc_rows']}")
            print(f"  Date range: {info['min_date']} .. {info['max_date']}")
            print(f"  Wrong index names / wrong year / outside window: {info['wrong_index_name_rows']} / {info['wrong_year_rows']} / {info['outside_window_rows']}")
            print(f"  Duplicate date groups: {info['duplicate_date_groups']}")
            print(f"  Blank / non-data lines: {info['blank_rows']} / {info['non_data_lines']}")
            if info["wrong_index_names"]:
                print(f"  Observed unexpected index names: {info['wrong_index_names']}")
            if info["duplicate_dates"]:
                print(f"  Duplicate dates: {', '.join(info['duplicate_dates'][:12])}")
            if info["sample_issues"]:
                print(f"  Sample OHLC issues: {' | '.join(info['sample_issues'][:5])}")
            if (info["rows"] == 0 or info["invalid_ohlc_rows"] or info["wrong_index_name_rows"]
                    or info["wrong_year_rows"] or info["outside_window_rows"] or info["duplicate_date_groups"]):
                structural_failures += 1

        per_instrument: dict[str, dict[str, Any]] = {}
        report_rows: list[dict[str, Any]] = []
        for instrument in INSTRUMENTS:
            records = [r for r in all_records if r["instrument"] == instrument]
            by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                by_date[record["date"]].append(record)
            existing_ohlc, existing_closes = existing_by_instrument[instrument]
            overlap_ohlc = 0
            overlap_close_only = 0
            overlap_match = 0
            overlap_mismatch = 0
            new_dates = 0
            duplicate_groups = 0
            invalid_source_rows = 0
            weekend_unregistered: list[str] = []
            holiday_conflicts: list[str] = []
            mismatch_samples: list[tuple[str, str, float]] = []
            for date_text in sorted(by_date):
                group = by_date[date_text]
                if len(group) > 1:
                    duplicate_groups += 1
                valid_group = [r for r in group if r["ohlc_issue"] is None]
                invalid_source_rows += len(group) - len(valid_group)
                unique_values = {
                    tuple(round(float(r[k]), 8) for k in OHLC_FIELDS)
                    for r in valid_group
                }
                exact_duplicate = len(group) > 1 and len(valid_group) == len(group) and len(unique_values) == 1
                duplicate_conflict = len(group) > 1 and not exact_duplicate
                usable = len(valid_group) == len(group) and len(unique_values) == 1
                representative = valid_group[0] if valid_group else group[0]
                old_close = existing_closes.get(date_text)
                old_ohlc = existing_ohlc.get(date_text)
                comparison_status = "source_invalid_or_duplicate_conflict" if not usable else "new_date_not_in_snapshot"
                diff_map: dict[str, float | None] = {k: None for k in OHLC_FIELDS}
                exceeds = False
                if usable:
                    if old_ohlc is not None:
                        overlap_ohlc += 1
                        diff_map = {k: float(representative[k]) - old_ohlc[k] for k in OHLC_FIELDS}
                        fields_over = [k for k, v in diff_map.items() if abs(v) > TOLERANCE]
                        exceeds = bool(fields_over)
                        if exceeds:
                            overlap_mismatch += 1
                            mismatch_samples.extend((date_text, k, diff_map[k]) for k in fields_over[:2])
                            comparison_status = "ohlc_overlap_mismatch_over_tolerance"
                        else:
                            overlap_match += 1
                            comparison_status = "ohlc_overlap_match_within_tolerance"
                    elif old_close is not None:
                        overlap_close_only += 1
                        close_diff = float(representative["close"]) - old_close
                        diff_map["close"] = close_diff
                        if abs(close_diff) > TOLERANCE:
                            overlap_mismatch += 1
                            mismatch_samples.append((date_text, "close", close_diff))
                            comparison_status = "close_only_overlap_mismatch_over_tolerance"
                        else:
                            overlap_match += 1
                            comparison_status = "close_only_overlap_match_within_tolerance"
                    else:
                        new_dates += 1
                day = date.fromisoformat(date_text)
                event = calendar_events.get(date_text)
                if day.weekday() >= 5 and date_text not in special_dates:
                    weekend_unregistered.append(date_text)
                if date_text in holiday_dates:
                    holiday_conflicts.append(date_text)
                report_rows.append({
                    "instrument_code": instrument,
                    "source_date": date_text,
                    "source_file": ";".join(sorted({r["source_file"] for r in group})),
                    "source_line_numbers": ";".join(str(r["source_line"]) for r in group),
                    "source_rows_for_date": len(group),
                    "index_name": representative["index_name"],
                    "open": representative["open"], "high": representative["high"],
                    "low": representative["low"], "close": representative["close"],
                    "ohlc_issue": " | ".join(sorted({r["ohlc_issue"] for r in group if r["ohlc_issue"]})),
                    "duplicate_status": "none" if len(group) == 1 else ("exact_duplicate" if exact_duplicate else "conflicting_or_invalid_duplicate"),
                    "existing_snapshot_type": "full_ohlc" if old_ohlc is not None else ("close_only" if old_close is not None else "new_date"),
                    "existing_open": old_ohlc.get("open") if old_ohlc else None,
                    "existing_high": old_ohlc.get("high") if old_ohlc else None,
                    "existing_low": old_ohlc.get("low") if old_ohlc else None,
                    "existing_close": old_ohlc.get("close") if old_ohlc else old_close,
                    "open_difference": diff_map["open"],
                    "high_difference": diff_map["high"],
                    "low_difference": diff_map["low"],
                    "close_difference": diff_map["close"],
                    "comparison_status": comparison_status,
                    "calendar_event_type": event[0] if event else "no_calendar_event",
                    "calendar_event_name": event[1] if event else "",
                })
            per_instrument[instrument] = {
                "source_rows": len(records),
                "unique_dates": len(by_date),
                "invalid_rows": invalid_source_rows,
                "duplicate_groups": duplicate_groups,
                "overlap_ohlc": overlap_ohlc,
                "overlap_close_only": overlap_close_only,
                "overlap_matches": overlap_match,
                "overlap_mismatches": overlap_mismatch,
                "new_dates": new_dates,
                "weekend_unregistered": sorted(set(weekend_unregistered)),
                "holiday_conflicts": sorted(set(holiday_conflicts)),
                "mismatch_samples": mismatch_samples[:10],
            }

        print("\nCANONICAL SNAPSHOT OVERLAP AND CALENDAR SUMMARY")
        print("-" * 104)
        print(f"{'INSTRUMENT':<13} {'ROWS':>6} {'DATES':>6} {'OHLC OVLP':>10} {'CLOSE ONLY':>11} {'MATCH':>7} {'MISMATCH':>9} {'NEW':>7} {'DUP':>5} {'INVALID':>8}")
        for instrument, values in per_instrument.items():
            print(f"{instrument:<13} {values['source_rows']:>6,} {values['unique_dates']:>6,} {values['overlap_ohlc']:>10,} {values['overlap_close_only']:>11,} {values['overlap_matches']:>7,} {values['overlap_mismatches']:>9,} {values['new_dates']:>7,} {values['duplicate_groups']:>5,} {values['invalid_rows']:>8,}")
            if values["mismatch_samples"]:
                print("  Mismatch examples (date, field, source-minus-snapshot):", values["mismatch_samples"][:5])
            if values["weekend_unregistered"]:
                print("  REVIEW: weekend dates without registered special session:", values["weekend_unregistered"])
            if values["holiday_conflicts"]:
                print("  HOLIDAY CONFLICTS:", values["holiday_conflicts"])

        combined_rows = sum(v["source_rows"] for v in per_instrument.values())
        combined_dates = sum(v["unique_dates"] for v in per_instrument.values())
        combined_invalid = sum(v["invalid_rows"] for v in per_instrument.values())
        combined_duplicates = sum(v["duplicate_groups"] for v in per_instrument.values())
        combined_overlaps = sum(v["overlap_ohlc"] + v["overlap_close_only"] for v in per_instrument.values())
        combined_matches = sum(v["overlap_matches"] for v in per_instrument.values())
        combined_mismatches = sum(v["overlap_mismatches"] for v in per_instrument.values())
        combined_new = sum(v["new_dates"] for v in per_instrument.values())
        combined_weekends = sum(len(v["weekend_unregistered"]) for v in per_instrument.values())
        combined_holidays = sum(len(v["holiday_conflicts"]) for v in per_instrument.values())

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "instrument_code", "source_date", "source_file", "source_line_numbers", "source_rows_for_date",
            "index_name", "open", "high", "low", "close", "ohlc_issue", "duplicate_status",
            "existing_snapshot_type", "existing_open", "existing_high", "existing_low", "existing_close",
            "open_difference", "high_difference", "low_difference", "close_difference", "comparison_status",
            "calendar_event_type", "calendar_event_name",
        ]
        with REPORT.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report_rows)

        print("\nCOMBINED VALIDATION SUMMARY")
        print("-" * 104)
        print(f"Files validated: {len(file_infos)}")
        print(f"Source rows parsed: {combined_rows:,}")
        print(f"Instrument-date groups: {combined_dates:,}")
        print(f"Invalid OHLC rows: {combined_invalid:,}")
        print(f"Duplicate instrument-date groups: {combined_duplicates:,}")
        print(f"Existing snapshot overlaps (full OHLC + close-only): {combined_overlaps:,}")
        print(f"Overlap groups within {TOLERANCE:.2f} tolerance: {combined_matches:,}")
        print(f"Overlap groups exceeding tolerance: {combined_mismatches:,}")
        print(f"New dates absent from current close series: {combined_new:,}")
        print(f"Unregistered weekend date groups: {combined_weekends:,}")
        print(f"Source date groups on registered NSE holidays: {combined_holidays:,}")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        print("\nDATABASE CHECKS")
        print("-" * 104)
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print(f"Validation report: {REPORT}")
        print("Database mode: read-only; no records modified.")
        print("Daily candles created or modified: 0")

        all_file_issues = any(
            info["rows"] == 0 or info["invalid_ohlc_rows"] or info["wrong_index_name_rows"]
            or info["wrong_year_rows"] or info["outside_window_rows"] or info["duplicate_date_groups"]
            for info in file_infos
        )
        calendar_issue = combined_weekends > 0 or combined_holidays > 0
        print("\nVALIDATION RESULT")
        print("-" * 104)
        if integrity != "ok" or fk_errors:
            print("FAILED — database integrity/foreign-key check did not pass.")
            return 2
        if all_file_issues or calendar_issue or combined_mismatches:
            print("REVIEW_REQUIRED — inspect file issues, calendar exceptions and overlap differences before staging.")
            return 2
        print("STRUCTURAL CHECKS PASSED — review row counts, source coverage and comparison report before staging.")
        print("Note: this validates the downloaded CSVs; it does not assert complete exchange-calendar coverage.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nVALIDATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
