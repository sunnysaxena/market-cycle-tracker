from __future__ import annotations

import csv
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
INPUT = ROOT / "backend" / "data" / "incoming" / "sensex_bse_2025_to_latest.csv"
REPORT = ROOT / "backend" / "data" / "sensex_bse_2025_to_latest_validation.csv"
SNAPSHOT_BATCH_ID = 2
INSTRUMENT_CODE = "SENSEX"
EXPECTED_START = date(2025, 1, 1)

DATE_FORMATS = (
    "%d-%B-%Y",  # 1-January-2025 (current BSE file format)
    "%d-%b-%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)
OHLC_FIELDS = ("Open", "High", "Low", "Close")


def parse_date(value: str) -> date:
    value = (value or "").strip().strip('"')
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date format: {value!r}")


def parse_number(value: str | None) -> float:
    if value is None:
        raise ValueError("Missing numeric value")
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        raise ValueError("Blank numeric value")
    number = float(cleaned)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("Non-finite numeric value")
    return number


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "mean_abs": None}
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "mean_abs": statistics.mean(abs(v) for v in values),
    }


def fmt_stats(label: str, values: list[float]) -> None:
    s = stats(values)
    if not s["count"]:
        print(f"{label:<10} count=0")
        return
    print(
        f"{label:<10} count={s['count']:>4} "
        f"mean={s['mean']:+.5f} median={s['median']:+.5f} "
        f"min={s['min']:+.5f} max={s['max']:+.5f} "
        f"mean_abs={s['mean_abs']:.5f}"
    )


def main() -> int:
    print("\nSENSEX BSE HISTORICAL CSV VALIDATION")
    print("=" * 88)
    print(f"Input file       : {INPUT}")
    print(f"Database         : {DATABASE}")
    print(f"Snapshot batch   : {SNAPSHOT_BATCH_ID}")
    print("Mode             : CSV read + SQLite read-only; no import or database changes")

    if not INPUT.is_file():
        raise FileNotFoundError(f"SENSEX CSV not found: {INPUT}")
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    parsed: list[dict[str, Any]] = []
    skipped_blank = 0
    parse_errors: list[dict[str, Any]] = []
    expected_header = {"Date", "Open", "High", "Low", "Close"}

    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        print(f"CSV headers       : {', '.join(headers)}")
        missing = expected_header.difference(headers)
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        for line_number, row in enumerate(reader, start=2):
            if not row or not any((v or "").strip() for v in row.values()):
                skipped_blank += 1
                continue
            try:
                d = parse_date(row.get("Date", ""))
                values = {field: parse_number(row.get(field)) for field in OHLC_FIELDS}
                parsed.append({
                    "source_row_number": line_number,
                    "candle_date": d.isoformat(),
                    "raw_date": (row.get("Date") or "").strip(),
                    **values,
                    "volume_cr_raw": (row.get("Volume(Cr.)") or "").strip(),
                    "turnover_cr_raw": (row.get("Turnover (Rs.Cr.)") or "").strip(),
                })
            except Exception as exc:
                parse_errors.append({
                    "source_row_number": line_number,
                    "raw_date": (row.get("Date") or "").strip(),
                    "issue": str(exc),
                })

    if not parsed:
        raise ValueError("No valid data rows were parsed from the CSV")

    # Build per-date groups and validate source rows without modifying the source file.
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed:
        by_date[row["candle_date"]].append(row)

    duplicate_dates = {d: group for d, group in by_date.items() if len(group) > 1}
    valid_rows: list[dict[str, Any]] = []
    for row in parsed:
        issues: list[str] = []
        d = date.fromisoformat(row["candle_date"])
        o, h, low, c = (row[field] for field in OHLC_FIELDS)
        if d < EXPECTED_START:
            issues.append("date_before_expected_start")
        if d > date.today():
            issues.append("future_dated_record")
        if any(row[field] <= 0 for field in OHLC_FIELDS):
            issues.append("non_positive_ohlc")
        if h < low:
            issues.append("high_below_low")
        if h < max(o, c):
            issues.append("high_below_open_or_close")
        if low > min(o, c):
            issues.append("low_above_open_or_close")
        if len(by_date[row["candle_date"]]) > 1:
            issues.append("duplicate_date_requires_review")
        row["source_quality"] = "valid_ohlc" if not issues else "review_required"
        row["source_issue_codes"] = ";".join(issues)
        if not issues:
            valid_rows.append(row)

    # Open staging DB in read-only mode.
    db_uri = f"file:{DATABASE.as_posix()}?mode=ro"
    con = sqlite3.connect(db_uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()

        legacy_rows = con.execute("""
            SELECT candle_date, open, high, low, close
            FROM daily_ohlcv_analytical
            WHERE import_batch_id = ?
              AND instrument_code = ?
            ORDER BY candle_date
        """, (SNAPSHOT_BATCH_ID, INSTRUMENT_CODE)).fetchall()
        legacy = {r["candle_date"]: dict(r) for r in legacy_rows}

        legacy_close_rows = con.execute("""
            SELECT candle_date, close
            FROM daily_close_series
            WHERE import_batch_id = ?
              AND instrument_code = ?
            ORDER BY candle_date
        """, (SNAPSHOT_BATCH_ID, INSTRUMENT_CODE)).fetchall()
        legacy_close = {r["candle_date"]: r["close"] for r in legacy_close_rows}

        calendar_events = con.execute("""
            SELECT session_date, exchange, event_type, event_name, verification_level
            FROM exchange_calendar_events
            WHERE exchange = 'BSE'
              AND market_segment = 'EQUITY'
        """).fetchall()
        bse_events: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for event in calendar_events:
            bse_events[event["session_date"]].append(event)

        # Assess all source rows against the existing canonical snapshot.
        field_deltas: dict[str, list[float]] = {field.lower(): [] for field in OHLC_FIELDS}
        close_abs_deltas: list[float] = []
        overlap_rows = 0
        close_matches_002 = 0
        close_diff_gt_002 = 0
        overlap_report: list[dict[str, Any]] = []
        source_valid_by_date = {r["candle_date"]: r for r in valid_rows}
        shared_dates = sorted(set(source_valid_by_date).intersection(legacy))

        for d in shared_dates:
            src = source_valid_by_date[d]
            old = legacy[d]
            deltas = {field.lower(): src[field] - old[field.lower()] for field in OHLC_FIELDS}
            overlap_rows += 1
            close_delta = deltas["close"]
            close_abs_deltas.append(abs(close_delta))
            if abs(close_delta) <= 0.02:
                close_matches_002 += 1
            else:
                close_diff_gt_002 += 1
            for field, delta in deltas.items():
                field_deltas[field].append(delta)
            overlap_report.append({
                "candidate_date": d,
                "source_open": src["Open"], "source_high": src["High"],
                "source_low": src["Low"], "source_close": src["Close"],
                "snapshot_open": old["open"], "snapshot_high": old["high"],
                "snapshot_low": old["low"], "snapshot_close": old["close"],
                "open_delta_source_minus_snapshot": deltas["open"],
                "high_delta_source_minus_snapshot": deltas["high"],
                "low_delta_source_minus_snapshot": deltas["low"],
                "close_delta_source_minus_snapshot": deltas["close"],
                "close_match_within_0_02": int(abs(close_delta) <= 0.02),
            })

        # Compare daily returns on consecutive dates shared by both sources.
        return_differences_pp: list[float] = []
        shared_order = sorted(shared_dates)
        for previous_date, current_date in zip(shared_order, shared_order[1:]):
            prev_src = source_valid_by_date[previous_date]["Close"]
            curr_src = source_valid_by_date[current_date]["Close"]
            prev_old = legacy[previous_date]["close"]
            curr_old = legacy[current_date]["close"]
            if prev_src > 0 and prev_old > 0:
                source_return = (curr_src / prev_src - 1.0) * 100.0
                old_return = (curr_old / prev_old - 1.0) * 100.0
                return_differences_pp.append(source_return - old_return)

        date_counts = Counter(row["candle_date"] for row in parsed)
        unique_dates = sorted(date_counts)
        weekend_rows = [r for r in parsed if date.fromisoformat(r["candle_date"]).weekday() >= 5]
        weekend_dates = sorted({r["candle_date"] for r in weekend_rows})
        weekend_without_bse_event = [d for d in weekend_dates if d not in bse_events]
        calendar_holiday_conflicts = [
            r["candle_date"] for r in parsed
            if any(event["event_type"] == "holiday_closed" for event in bse_events.get(r["candle_date"], []))
        ]

        source_only_dates = sorted(set(source_valid_by_date) - set(legacy_close))
        legacy_only_dates = sorted(set(legacy_close) - set(source_valid_by_date))

        # Write a date-level comparison report. Rows that are invalid or duplicated remain visible.
        report_rows: list[dict[str, Any]] = []
        overlap_lookup = {r["candidate_date"]: r for r in overlap_report}
        for row in parsed:
            extra = overlap_lookup.get(row["candle_date"], {})
            report_rows.append({
                "source_row_number": row["source_row_number"],
                "candidate_date": row["candle_date"],
                "raw_date": row["raw_date"],
                "open": row["Open"], "high": row["High"],
                "low": row["Low"], "close": row["Close"],
                "source_quality": row["source_quality"],
                "source_issue_codes": row["source_issue_codes"],
                "duplicate_date_count": date_counts[row["candle_date"]],
                "snapshot_close": extra.get("snapshot_close"),
                "open_delta_source_minus_snapshot": extra.get("open_delta_source_minus_snapshot"),
                "high_delta_source_minus_snapshot": extra.get("high_delta_source_minus_snapshot"),
                "low_delta_source_minus_snapshot": extra.get("low_delta_source_minus_snapshot"),
                "close_delta_source_minus_snapshot": extra.get("close_delta_source_minus_snapshot"),
                "close_match_within_0_02": extra.get("close_match_within_0_02"),
                "volume_cr_raw_not_treated_as_index_volume": row["volume_cr_raw"],
                "turnover_cr_raw": row["turnover_cr_raw"],
                "registered_bse_events": " | ".join(e["event_name"] for e in bse_events.get(row["candle_date"], [])),
            })

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        report_fields = list(report_rows[0].keys()) if report_rows else []
        with REPORT.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=report_fields)
            writer.writeheader()
            writer.writerows(report_rows)

        print("\nFILE VALIDATION")
        print("-" * 88)
        print(f"Parsed data rows                   : {len(parsed)}")
        print(f"Blank rows skipped                 : {skipped_blank}")
        print(f"Rows with parse errors             : {len(parse_errors)}")
        print(f"Unique source dates                : {len(unique_dates)}")
        print(f"Date range                         : {unique_dates[0]} to {unique_dates[-1]}")
        print(f"Rows before {EXPECTED_START}             : {sum(date.fromisoformat(r['candle_date']) < EXPECTED_START for r in parsed)}")
        print(f"Valid OHLC rows                    : {len(valid_rows)}")
        print(f"Invalid/review OHLC rows           : {len(parsed) - len(valid_rows)}")
        print(f"Duplicate date groups              : {len(duplicate_dates)}")
        print(f"Rows in duplicate groups           : {sum(len(v) for v in duplicate_dates.values())}")

        if parse_errors:
            print("\nPARSE ERRORS (first 10)")
            for item in parse_errors[:10]:
                print(item)

        if duplicate_dates:
            print("\nDUPLICATE DATE GROUPS")
            for d, group in sorted(duplicate_dates.items()):
                print(d, "rows=", len(group), "OHLC=", [tuple(r[k] for k in OHLC_FIELDS) for r in group])

        print("\nOHLC OVERLAP WITH EXISTING SNAPSHOT")
        print("-" * 88)
        print(f"Valid date overlaps                : {overlap_rows}")
        print(f"Close matches within 0.02 points   : {close_matches_002}")
        print(f"Close differs by more than 0.02    : {close_diff_gt_002}")
        for field in ("open", "high", "low", "close"):
            fmt_stats(field.upper(), field_deltas[field])
        fmt_stats("RET_DIFF_PP", return_differences_pp)
        print(f"Valid source dates absent in snapshot close series: {len(source_only_dates)}")
        print(f"Snapshot close dates absent in valid source CSV  : {len(legacy_only_dates)}")

        print("\nBSE CALENDAR CROSS-CHECK")
        print("-" * 88)
        print(f"Weekend rows                       : {len(weekend_rows)}")
        print(f"Unique weekend dates                : {len(weekend_dates)}")
        print(f"Weekend dates without registered BSE event: {len(weekend_without_bse_event)}")
        if weekend_without_bse_event:
            print("  ", ", ".join(weekend_without_bse_event[:30]))
        print(f"Source rows on registered BSE holiday dates: {len(calendar_holiday_conflicts)}")
        if calendar_holiday_conflicts:
            print("  ", ", ".join(sorted(set(calendar_holiday_conflicts))))

        print("\nDATABASE CHECKS")
        print("-" * 88)
        print("SQLite integrity:", integrity)
        print("Foreign-key errors:", len(fk_errors))
        print("\nVALIDATION REPORT:", REPORT)
        print("Database mode: read-only; no records modified.")
        print("No import, source registration, or candle promotion performed.")
        print("Note: Volume(Cr.) is retained as source metadata and is NOT treated as index traded volume.")

        # A hard pass is deliberately not asserted: this is an inspection report.
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
