
import re
import sys
import math
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.engines.ohlcv_aggregator import aggregate_all_timeframes


DAILY_TABLES = {
    "finnifty_1d",
    "indiavix_1d",
    "midnifty_1d",
    "nifty50_1d",
    "niftybank_1d",
    "sensex_1d",
}

INSERT_PATTERN = re.compile(
    r"INSERT\s+INTO\s+`([^`]+)`\s+VALUES\s*",
    re.IGNORECASE,
)

INDIA_TZ = ZoneInfo("Asia/Kolkata")


def parse_sql_value(value):
    value = value.strip()

    if value.upper() == "NULL":
        return None

    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
        value = value.replace("\\'", "'")
        value = value.replace("\\\\", "\\")
        value = value.replace("''", "'")

    return value


def extract_rows(statement):
    """Yield individual rows from a MySQL INSERT statement."""

    match = INSERT_PATTERN.search(statement)

    if not match:
        return

    position = match.end()
    length = len(statement)

    while position < length:
        while position < length and statement[position] in " \r\n\t,":
            position += 1

        if position >= length or statement[position] == ";":
            return

        if statement[position] != "(":
            position += 1
            continue

        position += 1
        start = position
        fields = []
        in_quote = False
        escaped = False

        while position < length:
            char = statement[position]

            if in_quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "'":
                    if (
                        position + 1 < length
                        and statement[position + 1] == "'"
                    ):
                        position += 1
                    else:
                        in_quote = False

            else:
                if char == "'":
                    in_quote = True
                elif char == ",":
                    fields.append(statement[start:position].strip())
                    start = position + 1
                elif char == ")":
                    fields.append(statement[start:position].strip())
                    yield [parse_sql_value(v) for v in fields]
                    position += 1
                    break

            position += 1


def new_stats():
    return {
        "rows": 0,
        "ids": set(),
        "timestamps": set(),
        "first_date": None,
        "last_date": None,
        "duplicate_ids": 0,
        "duplicate_timestamps": 0,
        "invalid_timestamp": 0,
        "invalid_ohlc": 0,
        "invalid_volume": 0,
        "zero_volume": 0,
        "missing_volume": 0,
        "flat_candles": 0,
    }


def inspect_row(fields, stats, valid_records):
    stats["rows"] += 1

    if len(fields) != 7:
        return

    try:
        record_id = int(fields[0])

        if record_id in stats["ids"]:
            stats["duplicate_ids"] += 1
        stats["ids"].add(record_id)

    except (TypeError, ValueError):
        return

    try:
        timestamp = datetime.fromisoformat(fields[1])
        session_date = timestamp.date()

        if timestamp in stats["timestamps"]:
            stats["duplicate_timestamps"] += 1
            return

        stats["timestamps"].add(timestamp)

        stats["first_date"] = (
            session_date if stats["first_date"] is None
            else min(stats["first_date"], session_date)
        )
        stats["last_date"] = (
            session_date if stats["last_date"] is None
            else max(stats["last_date"], session_date)
        )

    except (TypeError, ValueError):
        stats["invalid_timestamp"] += 1
        return

    try:
        o, h, l, c = map(float, fields[2:6])

        if not all(map(math.isfinite, [o, h, l, c])):
            raise ValueError()

        if (
            min(o, h, l, c) <= 0
            or h < l
            or h < max(o, c)
            or l > min(o, c)
        ):
            raise ValueError()

        if o == h == l == c:
            stats["flat_candles"] += 1

    except (TypeError, ValueError):
        stats["invalid_ohlc"] += 1
        return

    try:
        if fields[6] is None:
            volume = None
            stats["missing_volume"] += 1
        else:
            volume_float = float(fields[6])

            if (
                not math.isfinite(volume_float)
                or volume_float < 0
                or not volume_float.is_integer()
            ):
                raise ValueError()

            volume = int(volume_float)

            if volume == 0:
                stats["zero_volume"] += 1

    except (TypeError, ValueError):
        stats["invalid_volume"] += 1
        return

    valid_records.append({
        "timestamp": timestamp,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": volume,
    })


def run_audit(dump_path):
    if not dump_path.is_file():
        raise FileNotFoundError(dump_path)

    results = {
        table: {
            "stats": new_stats(),
            "records": [],
        }
        for table in DAILY_TABLES
    }

    current_table = None
    statement_parts = []
    incomplete = False

    print("\nReading Daily historical data...")
    print(f"Source: {dump_path}")
    print(f"File size: {dump_path.stat().st_size / 1048576:.2f} MB")

    def finish_statement():
        table_stats = results[current_table]["stats"]
        valid_records = results[current_table]["records"]

        for row in extract_rows("".join(statement_parts)):
            inspect_row(row, table_stats, valid_records)

    with dump_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as file:

        for line in file:
            if current_table is None:
                match = INSERT_PATTERN.search(line)

                if not match:
                    continue

                table = match.group(1)

                if table not in DAILY_TABLES:
                    # Ignore 1-minute and unrelated tables.
                    continue

                current_table = table
                statement_parts = [line]

            else:
                statement_parts.append(line)

            if line.rstrip().endswith(";"):
                finish_statement()

                print(
                    f"Processed {current_table}: "
                    f"{results[current_table]['stats']['rows']:,} rows"
                )

                current_table = None
                statement_parts = []

    if current_table is not None:
        incomplete = True

    reference_date = datetime.now(INDIA_TZ).date()

    report = [
        "MARKET CYCLE TRACKER - DAILY HISTORICAL AUDIT",
        "=" * 65,
        f"Source: {dump_path.name}",
        f"Reference date: {reference_date}",
        "",
    ]

    for table in sorted(DAILY_TABLES):
        data = results[table]
        stats = data["stats"]
        records = data["records"]

        report.extend([
            "-" * 65,
            f"TABLE: {table}",
            f"Total rows: {stats['rows']:,}",
            f"Valid Daily candles: {len(records):,}",
            f"First date: {stats['first_date']}",
            f"Last date: {stats['last_date']}",
            f"Duplicate IDs: {stats['duplicate_ids']:,}",
            f"Duplicate timestamps: {stats['duplicate_timestamps']:,}",
            f"Invalid timestamps: {stats['invalid_timestamp']:,}",
            f"Invalid OHLC: {stats['invalid_ohlc']:,}",
            f"Invalid volume: {stats['invalid_volume']:,}",
            f"Zero volume: {stats['zero_volume']:,}",
            f"Missing volume: {stats['missing_volume']:,}",
            f"Flat candles: {stats['flat_candles']:,}",
        ])

        if records:
            try:
                aggregated = aggregate_all_timeframes(
                    records,
                    as_of_date=reference_date,
                )

                report.append(
                    f"Weekly candles generated: {len(aggregated['1W']):,}"
                )
                report.append(
                    f"Monthly candles generated: {len(aggregated['1M']):,}"
                )
                report.append(
                    f"Yearly candles generated: {len(aggregated['1Y']):,}"
                )

            except Exception as exc:
                report.append(f"AGGREGATION ERROR: {exc}")

    report.extend([
        "",
        f"Incomplete final SQL statement: {incomplete}",
        "Original SQL dump was not modified.",
    ])

    output = PROJECT_ROOT / "docs" / "daily_data_audit.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(report), encoding="utf-8")

    print("\n".join(report))
    print(f"\nReport saved to: {output}")


if __name__ == "__main__":
    path = input(
        "\nEnter full path to Dump20260308.sql: "
    ).strip().strip('"')

    run_audit(Path(path))
