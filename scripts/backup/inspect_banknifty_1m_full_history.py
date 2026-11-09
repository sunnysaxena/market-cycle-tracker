import csv
import re
from collections import defaultdict
from pathlib import Path

DUMP_PATH = Path(r"E:\databases\Database\mysql\Dump20260308.sql")
OUTPUT_CSV = Path(
    r"E:\market-cycle-tracker\backend\data\banknifty_1m_full_history_coverage.csv"
)
TARGET_TABLE = "niftybank_1m"

INSERT_START_RE = re.compile(
    rf"INSERT\s+INTO\s+`?{re.escape(TARGET_TABLE)}`?(?=\s|\()",
    re.IGNORECASE,
)
DATETIME_RE = re.compile(
    r"'(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)'"
)


def scan_dump():
    if not DUMP_PATH.is_file():
        raise FileNotFoundError(f"MySQL dump not found: {DUMP_PATH}")

    stats_by_date = defaultdict(lambda: {"rows": 0, "first": None, "last": None})
    statements = 0
    total_timestamps = 0
    in_target_statement = False

    with DUMP_PATH.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            remainder = line
            while remainder:
                if not in_target_statement:
                    marker = INSERT_START_RE.search(remainder)
                    if marker is None:
                        break
                    statements += 1
                    in_target_statement = True
                    remainder = remainder[marker.end():]

                semicolon = remainder.find(";")
                if semicolon >= 0:
                    statement_part = remainder[:semicolon]
                    remainder = remainder[semicolon + 1:]
                    in_target_statement = False
                else:
                    statement_part = remainder
                    remainder = ""

                for match in DATETIME_RE.finditer(statement_part):
                    timestamp_text = match.group("timestamp")
                    date_text = timestamp_text[:10]
                    entry = stats_by_date[date_text]
                    entry["rows"] += 1
                    total_timestamps += 1
                    if entry["first"] is None or timestamp_text < entry["first"]:
                        entry["first"] = timestamp_text
                    if entry["last"] is None or timestamp_text > entry["last"]:
                        entry["last"] = timestamp_text

    if statements == 0:
        raise RuntimeError(
            f"No INSERT INTO `{TARGET_TABLE}` statements found. "
            "Check the dump's table naming or INSERT format."
        )

    return statements, total_timestamps, stats_by_date


def main():
    print("\nBANKNIFTY 1-MINUTE FULL-HISTORY COVERAGE INSPECTION")
    print("=" * 78)
    print(f"Source dump: {DUMP_PATH}")
    print(f"Target table: {TARGET_TABLE}")
    print("Read-only source scan; no database import or candle reconstruction.")

    statements, total_rows, stats = scan_dump()
    dates = sorted(stats)

    print(f"\nTarget INSERT statements found: {statements:,}")
    print(f"Timestamp values parsed across all years: {total_rows:,}")
    print(f"Unique dates with 1-minute timestamps: {len(dates):,}")
    print(f"First timestamp: {stats[dates[0]]['first'] if dates else 'N/A'}")
    print(f"Last timestamp:  {stats[dates[-1]]['last'] if dates else 'N/A'}")

    period_rows = sum(
        value["rows"] for date_text, value in stats.items()
        if "2015-01-01" <= date_text <= "2016-12-31"
    )
    print(f"Timestamp values in 2015–2016: {period_rows:,}")

    by_year = defaultdict(lambda: {"rows": 0, "days": 0})
    for date_text, value in stats.items():
        year = date_text[:4]
        by_year[year]["rows"] += value["rows"]
        by_year[year]["days"] += 1

    print("\nYEARLY COVERAGE")
    print("-" * 50)
    print(f"{'YEAR':<10}{'1M ROWS':>15}{'UNIQUE DAYS':>18}")
    for year in sorted(by_year):
        print(
            f"{year:<10}{by_year[year]['rows']:>15,}"
            f"{by_year[year]['days']:>18,}"
        )

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.writer(target)
        writer.writerow([
            "candle_date", "minute_rows", "first_minute_timestamp",
            "last_minute_timestamp"
        ])
        for date_text in dates:
            entry = stats[date_text]
            writer.writerow([
                date_text, entry["rows"], entry["first"], entry["last"]
            ])

    print(f"\nCSV report: {OUTPUT_CSV}")
    print("Source dump unchanged: yes")
    print("Historical daily candles created or modified: 0")
    print(
        "Note: parsed timestamp counts depend on the dump's INSERT format; "
        "review the sample/schema if the results look unexpected."
    )


if __name__ == "__main__":
    main()
