#!/usr/bin/env python3
"""Read-only validator for NIFTY 50 NSE daily OHLC CSVs for 2025 and 2026.

Expected files:
  backend/data/incoming/nifty50_nse_2025.csv
  backend/data/incoming/nifty50_nse_2026.csv

Expected download windows:
  2025: 2025-03-04 through 2025-12-31
  2026: 2026-01-01 through 2026-10-30

No database writes are performed. A date-level CSV report is written to
backend/data/nifty50_nse_2025_2026_validation.csv.
"""

from __future__ import annotations

import csv
import hashlib
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "backend" / "data" / "incoming"
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
REPORT = ROOT / "backend" / "data" / "nifty50_nse_2025_2026_validation.csv"
BATCH_ID = 3

FILES = {
    2025: {
        "path": INCOMING / "nifty50_nse_2025.csv",
        "expected_start": date(2025, 3, 4),
        "expected_end": date(2025, 12, 31),
    },
    2026: {
        "path": INCOMING / "nifty50_nse_2026.csv",
        "expected_start": date(2026, 1, 1),
        "expected_end": date(2026, 10, 30),
    },
}
REQUIRED_HEADERS = {"Index Name", "Date", "Open", "High", "Low", "Close"}
EXPECTED_INDEX_NAME = "NIFTY 50"
OHLC_FIELDS = ("Open", "High", "Low", "Close")


def parse_date(value: str) -> date:
    value = (value or "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value!r}")


def parse_number(value: str) -> float:
    cleaned = (value or "").strip().replace(",", "")
    if cleaned == "":
        raise ValueError("blank numeric value")
    number = float(cleaned)
    if not math.isfinite(number):
        raise ValueError("non-finite numeric value")
    return number


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def get_conn() -> sqlite3.Connection:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")
    conn = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def load_existing(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    ohlc_rows = conn.execute("""
        SELECT candle_date, open, high, low, close
        FROM daily_ohlcv_analytical
        WHERE import_batch_id = ? AND instrument_code = 'NIFTY50'
    """, (BATCH_ID,)).fetchall()
    close_rows = conn.execute("""
        SELECT candle_date, close
        FROM daily_close_series
        WHERE import_batch_id = ? AND instrument_code = 'NIFTY50'
    """, (BATCH_ID,)).fetchall()
    ohlc = {
        row["candle_date"]: {
            "Open": float(row["open"]), "High": float(row["high"]),
            "Low": float(row["low"]), "Close": float(row["close"]),
        }
        for row in ohlc_rows
    }
    closes = {row["candle_date"]: float(row["close"]) for row in close_rows}
    return ohlc, closes


def load_calendar(conn: sqlite3.Connection) -> tuple[set[str], set[str], dict[str, list[str]]]:
    events = conn.execute("""
        SELECT session_date, event_type, event_name
        FROM exchange_calendar_events
        WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
          AND session_date BETWEEN '2025-01-01' AND '2026-12-31'
    """).fetchall()
    special_dates: set[str] = set()
    holiday_dates: set[str] = set()
    details: dict[str, list[str]] = defaultdict(list)
    for row in events:
        d = row["session_date"]
        details[d].append(f"{row['event_type']}: {row['event_name']}")
        if row["event_type"] == "special_session_open":
            special_dates.add(d)
        elif row["event_type"] == "holiday_closed":
            holiday_dates.add(d)
    return special_dates, holiday_dates, details


def validate_file(year: int, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path: Path = cfg["path"]
    if not path.is_file():
        raise FileNotFoundError(f"Expected file not found: {path}")

    file_hash, file_size = sha256_file(path)
    parsed: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    blank_rows = 0
    wrong_index_names: Counter[str] = Counter()
    wrong_year_rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        # csv.Sniffer can misread small files; the observed NSE export is comma-separated.
        reader = csv.DictReader(f, delimiter=",")
        headers = set(reader.fieldnames or [])
        if not REQUIRED_HEADERS.issubset(headers):
            missing = sorted(REQUIRED_HEADERS - headers)
            raise ValueError(f"{path.name}: missing required CSV columns: {missing}; found={reader.fieldnames}")

        for line_number, row in enumerate(reader, start=2):
            if not row or not any((value or "").strip() for value in row.values()):
                blank_rows += 1
                continue
            try:
                idx = (row.get("Index Name") or "").strip()
                if idx != EXPECTED_INDEX_NAME:
                    wrong_index_names[idx] += 1
                d = parse_date(row.get("Date", ""))
                values = {field: parse_number(row.get(field, "")) for field in OHLC_FIELDS}
                valid_ohlc = (
                    all(values[field] > 0 for field in OHLC_FIELDS)
                    and values["High"] >= max(values["Open"], values["Close"], values["Low"])
                    and values["Low"] <= min(values["Open"], values["Close"], values["High"])
                    and values["High"] >= values["Low"]
                )
                if d.year != year:
                    wrong_year_rows += 1
                parsed.append({
                    "source_file": path.name,
                    "source_line": line_number,
                    "instrument_name": idx,
                    "date": d.isoformat(),
                    "year": d.year,
                    **values,
                    "ohlc_status": "valid_ohlc" if valid_ohlc else "invalid_ohlc_relationship",
                    "parse_status": "parsed",
                })
            except Exception as exc:
                parse_errors.append(f"line {line_number}: {exc}")

    dates = [row["date"] for row in parsed]
    duplicate_counts = Counter(dates)
    duplicate_dates = {d for d, count in duplicate_counts.items() if count > 1}
    valid_rows = [r for r in parsed if r["ohlc_status"] == "valid_ohlc"]
    valid_dates = {r["date"] for r in valid_rows if r["year"] == year}

    info = {
        "year": year,
        "file": path.name,
        "sha256": file_hash,
        "size_bytes": file_size,
        "parsed_rows": len(parsed),
        "blank_rows": blank_rows,
        "parse_errors": len(parse_errors),
        "parse_error_examples": parse_errors[:10],
        "wrong_index_name_rows": sum(wrong_index_names.values()),
        "wrong_index_names": dict(wrong_index_names),
        "wrong_year_rows": wrong_year_rows,
        "valid_ohlc_rows": len(valid_rows),
        "unique_dates": len(set(dates)),
        "unique_valid_dates_in_year": len(valid_dates),
        "duplicate_dates": sorted(duplicate_dates),
        "duplicate_date_groups": len(duplicate_dates),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "expected_start": cfg["expected_start"].isoformat(),
        "expected_end": cfg["expected_end"].isoformat(),
        "outside_expected_window": sorted(
            d for d in set(dates)
            if d < cfg["expected_start"].isoformat() or d > cfg["expected_end"].isoformat()
        ),
        "records": parsed,
    }
    return parsed, info


def main() -> int:
    print("\nNIFTY 50 NSE HISTORICAL CSV VALIDATION")
    print("=" * 88)
    print(f"Input folder : {INCOMING}")
    print(f"Database     : {DATABASE}")
    print(f"Snapshot     : batch {BATCH_ID}")
    print("Mode         : CSV read + SQLite read-only; no import or database changes")

    conn = get_conn()
    try:
        batch = conn.execute("SELECT id, status FROM import_batches WHERE id = ?", (BATCH_ID,)).fetchone()
        if batch is None or batch["status"] != "completed":
            raise RuntimeError(f"Snapshot batch {BATCH_ID} is missing or not completed")
        existing_ohlc, existing_closes = load_existing(conn)
        special_dates, holiday_dates, calendar_details = load_calendar(conn)

        all_records: list[dict[str, Any]] = []
        file_infos: list[dict[str, Any]] = []
        for year, cfg in FILES.items():
            records, info = validate_file(year, cfg)
            all_records.extend(records)
            file_infos.append(info)

        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in all_records:
            by_date[record["date"]].append(record)

        print("\nFILE VALIDATION")
        print("-" * 88)
        for info in file_infos:
            print(f"\n{info['file']} | expected window={info['expected_start']} to {info['expected_end']}")
            print(f"  SHA-256: {info['sha256']}")
            print(f"  File size: {info['size_bytes']:,} bytes")
            print(f"  Parsed rows: {info['parsed_rows']}")
            print(f"  Valid OHLC rows: {info['valid_ohlc_rows']}")
            print(f"  Unique dates: {info['unique_dates']}")
            print(f"  Date range: {info['date_min']} to {info['date_max']}")
            print(f"  Blank rows: {info['blank_rows']} | Parse errors: {info['parse_errors']}")
            print(f"  Wrong index-name rows: {info['wrong_index_name_rows']} | Wrong-year rows: {info['wrong_year_rows']}")
            print(f"  Duplicate date groups: {info['duplicate_date_groups']}")
            print(f"  Dates outside expected window: {len(info['outside_expected_window'])}")
            if info["duplicate_dates"]:
                print("  Duplicate dates:", ", ".join(info["duplicate_dates"][:20]))
            if info["outside_expected_window"]:
                print("  Outside-window dates:", ", ".join(info["outside_expected_window"][:20]))
            if info["parse_error_examples"]:
                print("  Parse error examples:", " | ".join(info["parse_error_examples"]))

        combined_unique = len(by_date)
        duplicate_groups = {d for d, rows in by_date.items() if len(rows) > 1}
        invalid_rows = [r for r in all_records if r["ohlc_status"] != "valid_ohlc"]
        wrong_index_rows = [r for r in all_records if r["instrument_name"] != EXPECTED_INDEX_NAME]
        wrong_year_rows = [r for r in all_records if r["year"] not in FILES]
        outside_window_dates = set()
        for r in all_records:
            cfg = FILES.get(r["year"])
            if cfg is None:
                outside_window_dates.add(r["date"])
                continue
            if (
                r["date"] < cfg["expected_start"].isoformat()
                or r["date"] > cfg["expected_end"].isoformat()
            ):
                outside_window_dates.add(r["date"])

        overlap_ohlc_dates = set(by_date) & set(existing_ohlc)
        overlap_close_dates = set(by_date) & set(existing_closes)
        delta_values = {field: [] for field in OHLC_FIELDS}
        overlap_rows: list[dict[str, Any]] = []
        for d in sorted(overlap_ohlc_dates):
            csv_row = by_date[d][0]
            existing = existing_ohlc[d]
            deltas = {field: csv_row[field] - existing[field] for field in OHLC_FIELDS}
            for field, value in deltas.items():
                delta_values[field].append(value)
            overlap_rows.append({
                "date": d,
                "csv_open": csv_row["Open"], "csv_high": csv_row["High"],
                "csv_low": csv_row["Low"], "csv_close": csv_row["Close"],
                "snapshot_open": existing["Open"], "snapshot_high": existing["High"],
                "snapshot_low": existing["Low"], "snapshot_close": existing["Close"],
                "open_difference": deltas["Open"], "high_difference": deltas["High"],
                "low_difference": deltas["Low"], "close_difference": deltas["Close"],
            })

        print("\nCOMBINED VALIDATION SUMMARY")
        print("-" * 88)
        print(f"Parsed source rows: {len(all_records)}")
        print(f"Unique source dates: {combined_unique}")
        print(f"Invalid OHLC rows: {len(invalid_rows)}")
        print(f"Wrong index-name rows: {len(wrong_index_rows)}")
        print(f"Wrong-year rows: {len(wrong_year_rows)}")
        print(f"Duplicate date groups across both files: {len(duplicate_groups)}")
        print(f"Existing snapshot OHLC overlaps: {len(overlap_ohlc_dates)}")
        print(f"Existing snapshot close overlaps: {len(overlap_close_dates)}")
        new_dates = set(by_date) - set(existing_closes)
        print(f"Source dates absent from snapshot close series: {len(new_dates)}")

        print("\nOHLC OVERLAP DIFFERENCES (CSV minus snapshot batch 3)")
        print("-" * 88)
        for field, values in delta_values.items():
            if values:
                print(
                    f"{field:<6} count={len(values):>4} mean={mean(values):+.5f} "
                    f"median={median(values):+.5f} min={min(values):+.5f} "
                    f"max={max(values):+.5f} mean_abs={mean(abs(v) for v in values):.5f}"
                )
            else:
                print(f"{field:<6} no overlapping full-OHLC dates")

        weekend_records = [r for r in all_records if date.fromisoformat(r["date"]).weekday() >= 5]
        weekend_dates = sorted({r["date"] for r in weekend_records})
        weekend_unregistered = [d for d in weekend_dates if d not in special_dates]
        holiday_rows = sorted({r["date"] for r in all_records if r["date"] in holiday_dates})
        registered_weekend_rows = sorted({r["date"] for r in weekend_records if r["date"] in special_dates})

        print("\nNSE CALENDAR CROSS-CHECK")
        print("-" * 88)
        print(f"Weekend source rows: {len(weekend_records)}")
        print(f"Unique weekend source dates: {len(weekend_dates)}")
        print(f"Weekend dates with registered NSE special event: {len(registered_weekend_rows)}")
        print(f"Weekend dates without registered NSE special event: {len(weekend_unregistered)}")
        for d in weekend_unregistered:
            print(f"  REVIEW: {d}")
        print(f"Source rows on registered NSE holiday dates: {len(holiday_rows)}")
        for d in holiday_rows:
            print(f"  HOLIDAY CONFLICT: {d}")

        report_rows: list[dict[str, Any]] = []
        for d in sorted(by_date):
            records = by_date[d]
            r = records[0]
            is_weekend = date.fromisoformat(d).weekday() >= 5
            calendar_status = (
                "holiday_conflict" if d in holiday_dates else
                "registered_special_session" if d in special_dates else
                "weekend_event_unregistered" if is_weekend else
                "weekday_calendar_not_fully_verified"
            )
            old = existing_ohlc.get(d)
            report_rows.append({
                "date": d,
                "source_file": r["source_file"],
                "index_name": r["instrument_name"],
                "open": r["Open"], "high": r["High"], "low": r["Low"], "close": r["Close"],
                "ohlc_status": r["ohlc_status"],
                "duplicate_in_source_files": len(records) > 1,
                "snapshot_overlap": d in existing_closes,
                "snapshot_full_ohlc_overlap": d in existing_ohlc,
                "open_difference": (r["Open"] - old["Open"]) if old else None,
                "high_difference": (r["High"] - old["High"]) if old else None,
                "low_difference": (r["Low"] - old["Low"]) if old else None,
                "close_difference": (r["Close"] - old["Close"]) if old else None,
                "calendar_status": calendar_status,
                "calendar_event_detail": " | ".join(calendar_details.get(d, [])),
            })

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "date", "source_file", "index_name", "open", "high", "low", "close",
            "ohlc_status", "duplicate_in_source_files", "snapshot_overlap",
            "snapshot_full_ohlc_overlap", "open_difference", "high_difference",
            "low_difference", "close_difference", "calendar_status", "calendar_event_detail",
        ]
        with REPORT.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

        print("\nDATABASE CHECKS")
        print("-" * 88)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print(f"\nValidation report: {REPORT}")
        print("Database mode: read-only; no records modified.")

        blocking = (
            len(invalid_rows) > 0 or len(wrong_index_rows) > 0 or
            len(wrong_year_rows) > 0 or len(duplicate_groups) > 0 or
            bool(outside_window_dates) or bool(holiday_rows) or bool(weekend_unregistered)
        )
        print("\nVALIDATION STATUS:", "REVIEW_REQUIRED" if blocking else "STRUCTURAL_CHECKS_PASSED")
        print("Note: weekday date gaps are not declared missing sessions; annual NSE calendars may be incomplete.")
        return 2 if blocking else 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
