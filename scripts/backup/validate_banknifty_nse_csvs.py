import csv
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "backend" / "data" / "incoming"
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
FILES = [
    (INCOMING / "banknifty_nse_2015.csv", 2015),
    (INCOMING / "banknifty_nse_2016.csv", 2016),
]
REPORT = ROOT / "backend" / "data" / "banknifty_nse_2015_2016_validation.csv"

DATE_ALIASES = {"date", "index date", "trading date", "timestamp", "trade date"}
OPEN_ALIASES = {"open", "open index value", "open value", "open price"}
HIGH_ALIASES = {"high", "high index value", "high value", "high price"}
LOW_ALIASES = {"low", "low index value", "low value", "low price"}
CLOSE_ALIASES = {
    "close", "close index value", "closing index value", "closing value",
    "close price", "closing price"
}


def normalize_header(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower())).strip()


def parse_date(value):
    value = (value or "").strip().strip('"').strip()
    if not value:
        raise ValueError("empty date")
    # NSE exports are normally day-first; deliberately do not interpret ambiguous dates month-first.
    formats = (
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
        "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
        "%Y%m%d", "%d.%m.%Y", "%d-%b-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        raise ValueError(f"unrecognized date format: {value!r}")


def parse_number(value, field):
    raw = (value or "").strip().strip('"').strip()
    if raw in {"", "-", "—", "NA", "N/A", "null", "None"}:
        raise ValueError(f"missing {field}")
    raw = raw.replace(",", "").replace("₹", "").strip()
    try:
        number = float(raw)
    except ValueError:
        raise ValueError(f"invalid {field}: {value!r}")
    if not (number == number and abs(number) != float("inf")):
        raise ValueError(f"non-finite {field}")
    return number


def read_text(path):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Could not decode {path}")


def find_header(rows):
    aliases = {
        "date": DATE_ALIASES, "open": OPEN_ALIASES, "high": HIGH_ALIASES,
        "low": LOW_ALIASES, "close": CLOSE_ALIASES,
    }
    for idx, row in enumerate(rows[:20]):
        normalized = [normalize_header(cell) for cell in row]
        positions = {}
        for key, options in aliases.items():
            for col_idx, heading in enumerate(normalized):
                if heading in options:
                    positions[key] = col_idx
                    break
        if len(positions) == 5:
            return idx, positions, row
    return None, None, None


def valid_ohlc(candle):
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    if min(o, h, l, c) <= 0:
        return "OHLC values must all be positive"
    if h < l:
        return "high is below low"
    if h + 1e-9 < max(o, c):
        return "high is below open or close"
    if l - 1e-9 > min(o, c):
        return "low is above open or close"
    return None


def load_csv(path, expected_year):
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing file: {path}\n"
            "Check that both NSE CSV files are saved in backend\\data\\incoming."
        )
    text, encoding = read_text(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(text.splitlines(), dialect))
    header_idx, positions, header = find_header(rows)
    if header_idx is None:
        sample_lines = "\n".join(text.splitlines()[:8])
        raise ValueError(
            f"Could not identify Date/Open/High/Low/Close columns in {path.name}.\n"
            f"First lines:\n{sample_lines}"
        )

    records = []
    non_data_lines = 0
    row_errors = []
    for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or not any((cell or "").strip() for cell in row):
            continue
        # A footer or metadata line generally has no parseable date.
        if max(positions.values()) >= len(row):
            non_data_lines += 1
            continue
        try:
            d = parse_date(row[positions["date"]])
        except ValueError:
            non_data_lines += 1
            continue

        values = {}
        row_issues = []
        for key in ("open", "high", "low", "close"):
            try:
                values[key] = parse_number(row[positions[key]], key)
            except ValueError as exc:
                values[key] = None
                row_issues.append(str(exc))

        if not row_issues:
            ohlc_issue = valid_ohlc(values)
            if ohlc_issue:
                row_issues.append(ohlc_issue)
        if d.year != expected_year:
            row_issues.append(f"date outside expected year {expected_year}")

        candle = {
            "date": d, **values, "source_file": path.name,
            "source_line": row_idx,
            "row_issue": "; ".join(row_issues),
        }
        records.append(candle)
        if row_issues and len(row_errors) < 10:
            row_errors.append((row_idx, "; ".join(row_issues), row[:6]))

    return {
        "path": path, "encoding": encoding, "delimiter": repr(dialect.delimiter),
        "header": header, "records": records, "non_data_lines": non_data_lines,
        "row_errors": row_errors,
    }


def main():
    print("\nBANKNIFTY NSE CSV VALIDATION")
    print("=" * 76)
    print(f"Project: {ROOT}")
    print(f"Input folder: {INCOMING}")
    print("Mode: CSV read + SQLite read-only; no import or database changes")

    loaded = [load_csv(path, year) for path, year in FILES]

    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")
    db_uri = f"file:{DATABASE.as_posix()}?mode=ro"
    con = sqlite3.connect(db_uri, uri=True)
    try:
        existing = {
            row[0]: float(row[1])
            for row in con.execute("""
                SELECT candle_date, close
                FROM daily_close_series
                WHERE instrument_code = 'BANKNIFTY'
                  AND candle_date >= '2015-01-01'
                  AND candle_date <= '2016-12-31'
            """)
        }
        calendar = {
            row[0]: (row[1], row[2])
            for row in con.execute("""
                SELECT session_date, event_type, event_name
                FROM exchange_calendar_events
                WHERE exchange = 'NSE'
                  AND market_segment = 'EQUITY'
                  AND session_date BETWEEN '2015-01-01' AND '2016-12-31'
            """)
        }
    finally:
        con.close()

    all_records = [record for item in loaded for record in item["records"]]
    by_date = defaultdict(list)
    for record in all_records:
        by_date[record["date"].isoformat()].append(record)

    valid_dates = set()
    output_rows = []
    overlap_match = overlap_mismatch = new_dates = duplicate_exact = duplicate_conflict = 0
    invalid_rows = 0

    for date_text in sorted(by_date):
        group = by_date[date_text]
        valid_group = [r for r in group if not r["row_issue"]]
        issues = sorted({r["row_issue"] for r in group if r["row_issue"]})
        unique_candle_values = {
            (round(r["open"], 4), round(r["high"], 4), round(r["low"], 4), round(r["close"], 4))
            for r in valid_group
        }
        if len(group) > 1:
            if len(unique_candle_values) <= 1 and len(valid_group) == len(group):
                duplicate_status = "exact_duplicate"
                duplicate_exact += 1
            else:
                duplicate_status = "conflicting_or_invalid_duplicate"
                duplicate_conflict += 1
        else:
            duplicate_status = "none"

        if len(valid_group) == 0:
            representative = group[0]
        elif len(unique_candle_values) == 1:
            representative = valid_group[0]
        else:
            representative = valid_group[0]

        old_close = existing.get(date_text)
        source_close = representative["close"]
        difference = None
        source_is_usable = (
            len(valid_group) == len(group)
            and len(unique_candle_values) == 1
            and duplicate_status != "conflicting_or_invalid_duplicate"
        )
        if not source_is_usable:
            comparison = "not_compared_source_duplicate_or_row_issue"
        elif source_close is None:
            comparison = "not_compared_missing_source_close"
        elif old_close is None:
            comparison = "new_date_not_in_current_db"
            new_dates += 1
        else:
            difference = round(source_close - old_close, 6)
            if abs(difference) <= 0.02:
                comparison = "existing_close_match"
                overlap_match += 1
            else:
                comparison = "existing_close_mismatch"
                overlap_mismatch += 1

        if issues:
            invalid_rows += len([r for r in group if r["row_issue"]])
        event = calendar.get(date_text)
        calendar_status = event[0] if event else "no_calendar_event"
        calendar_name = event[1] if event else ""
        if event and event[0] == "holiday_closed":
            issues.append("date_is_marked_regular_exchange_holiday")
        elif event and event[0] == "special_session_open":
            issues.append("special_session_date")

        output_rows.append({
            "date": date_text,
            "open": representative.get("open"),
            "high": representative.get("high"),
            "low": representative.get("low"),
            "close": representative.get("close"),
            "source_file": ";".join(sorted({r["source_file"] for r in group})),
            "source_line_numbers": ";".join(str(r["source_line"]) for r in group),
            "source_rows_for_date": len(group),
            "duplicate_status": duplicate_status,
            "source_row_issues": ";".join(issues),
            "existing_daily_close": old_close,
            "source_minus_existing_close": difference,
            "comparison_status": comparison,
            "calendar_event_type": calendar_status,
            "calendar_event_name": calendar_name,
        })
        if len(valid_group) == len(group) and duplicate_status != "conflicting_or_invalid_duplicate":
            valid_dates.add(date_text)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(output_rows[0].keys()) if output_rows else [
        "date", "open", "high", "low", "close", "source_file", "source_line_numbers",
        "source_rows_for_date", "duplicate_status", "source_row_issues", "existing_daily_close",
        "source_minus_existing_close", "comparison_status", "calendar_event_type", "calendar_event_name"
    ]
    with REPORT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print("\nFILE VALIDATION")
    print("-" * 76)
    for item, (_, year) in zip(loaded, FILES):
        recs = item["records"]
        dates = sorted(r["date"] for r in recs)
        year_recs = [r for r in recs if r["date"].year == year]
        valid_year_recs = [r for r in year_recs if not r["row_issue"]]
        unique_year_dates = sorted({r["date"] for r in valid_year_recs})
        print(f"\n{item['path'].name} | expected year={year}")
        print(f"  Encoding/delimiter: {item['encoding']} / {item['delimiter']}")
        print(f"  Header: {', '.join(str(x) for x in item['header'])}")
        print(f"  Parsed data rows: {len(recs)}")
        print(f"  Rows in expected year: {len(year_recs)}")
        print(f"  Valid OHLC rows in expected year: {len(valid_year_recs)}")
        print(f"  Unique valid dates in expected year: {len(unique_year_dates)}")
        print(f"  Date range in file: {min(dates) if dates else '-'} to {max(dates) if dates else '-'}")
        print(f"  Non-data/footer/unparsed lines skipped: {item['non_data_lines']}")
        if item["row_errors"]:
            print("  Sample skipped lines:")
            for line_no, error, values in item["row_errors"][:5]:
                print(f"    line {line_no}: {error}; values={values}")

    print("\nCOMBINED VALIDATION SUMMARY")
    print("-" * 76)
    print(f"Parsed source rows: {len(all_records)}")
    print(f"Unique source dates: {len(by_date)}")
    print(f"Valid unique source dates: {len(valid_dates)}")
    print(f"Invalid/out-of-year rows: {invalid_rows}")
    print(f"Dates with exact duplicate rows: {duplicate_exact}")
    print(f"Dates with conflicting/invalid duplicates: {duplicate_conflict}")
    print(f"Overlap with existing BANKNIFTY daily close dates: {overlap_match + overlap_mismatch}")
    print(f"  Existing closes matching within 0.02: {overlap_match}")
    print(f"  Existing closes differing by more than 0.02: {overlap_mismatch}")
    print(f"New dates absent from current daily close series: {new_dates}")

    if overlap_mismatch:
        print("\nWARNING: Some overlapping close values differ. Review the CSV before import.")
    if duplicate_conflict:
        print("WARNING: Conflicting or invalid duplicate dates require manual review.")
    holiday_dates = [d for d in by_date if d in calendar and calendar[d][0] == "holiday_closed"]
    special_dates = [d for d in by_date if d in calendar and calendar[d][0] == "special_session_open"]
    print(f"Source dates marked as regular NSE holidays: {len(holiday_dates)}")
    if holiday_dates:
        print("  " + ", ".join(holiday_dates[:20]))
    print(f"Source dates marked as special sessions: {len(special_dates)}")
    if special_dates:
        print("  " + ", ".join(special_dates))

    print(f"\nValidation CSV: {REPORT}")
    print("Database changes: none (SQLite opened read-only).")
    print("Daily candles created or modified: 0")
    print("Tolerance for matching existing closes: 0.02 index points.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nVALIDATION FAILED: {exc}", file=sys.stderr)
        raise
