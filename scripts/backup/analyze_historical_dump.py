
import re
import math
from datetime import datetime
from pathlib import Path
from collections import defaultdict


EXPECTED_TABLES = [
    "finnifty_1d",
    "indiavix_1d",
    "midnifty_1d",
    "nifty50_1d",
    "niftybank_1d",
    "sensex_1d",
]

INSERT_PATTERN = re.compile(
    r"INSERT\s+INTO\s+`([^`]+)`\s+VALUES\s*",
    re.IGNORECASE,
)


def new_stats():
    return {
        "rows": 0,
        "min_id": None,
        "max_id": None,
        "seen_ids": set(),
        "duplicate_ids": 0,
        "first_timestamp": None,
        "last_timestamp": None,
        "previous_timestamp": None,
        "seen_timestamps": set(),
        "duplicate_timestamps": 0,
        "out_of_order": 0,
        "unique_dates": set(),
        "invalid_timestamps": 0,
        "malformed_rows": 0,
        "null_values": 0,
        "invalid_ohlc": 0,
        "zero_volume": 0,
        "negative_volume": 0,
        "invalid_volume": 0,
        "flat_candles": 0,
    }


def decode_sql_value(value):
    value = value.strip()

    if value.upper() == "NULL":
        return None

    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
        value = value.replace("\\'", "'")
        value = value.replace("\\\\", "\\")
        value = value.replace("''", "'")
        return value

    return value


def parse_insert_rows(statement, start_position):
    """Read individual SQL value tuples without splitting the whole statement."""

    position = start_position
    length = len(statement)

    while position < length:
        while position < length and statement[position] in " \t\r\n,":
            position += 1

        if position >= length or statement[position] == ";":
            return

        if statement[position] != "(":
            position += 1
            continue

        position += 1
        field_start = position
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
                    # Handle doubled SQL single quotes.
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
                    fields.append(
                        statement[field_start:position].strip()
                    )
                    field_start = position + 1

                elif char == ")":
                    fields.append(
                        statement[field_start:position].strip()
                    )

                    yield fields
                    position += 1
                    break

            position += 1

        else:
            raise ValueError("Incomplete SQL value tuple encountered.")


def update_stats(stats, raw_fields):
    stats["rows"] += 1

    if len(raw_fields) != 7:
        stats["malformed_rows"] += 1
        return

    fields = [decode_sql_value(value) for value in raw_fields]

    if any(value is None for value in fields):
        stats["null_values"] += 1

    try:
        record_id = int(fields[0])

        if record_id in stats["seen_ids"]:
            stats["duplicate_ids"] += 1
        else:
            stats["seen_ids"].add(record_id)

        stats["min_id"] = (
            record_id if stats["min_id"] is None
            else min(stats["min_id"], record_id)
        )
        stats["max_id"] = (
            record_id if stats["max_id"] is None
            else max(stats["max_id"], record_id)
        )

    except (TypeError, ValueError):
        stats["malformed_rows"] += 1
        return

    try:
        timestamp = datetime.fromisoformat(fields[1])

        if timestamp in stats["seen_timestamps"]:
            stats["duplicate_timestamps"] += 1
        else:
            stats["seen_timestamps"].add(timestamp)

        if (
            stats["previous_timestamp"] is not None
            and timestamp < stats["previous_timestamp"]
        ):
            stats["out_of_order"] += 1

        stats["previous_timestamp"] = timestamp

        if (
            stats["first_timestamp"] is None
            or timestamp < stats["first_timestamp"]
        ):
            stats["first_timestamp"] = timestamp

        if (
            stats["last_timestamp"] is None
            or timestamp > stats["last_timestamp"]
        ):
            stats["last_timestamp"] = timestamp

        stats["unique_dates"].add(timestamp.date())

    except (TypeError, ValueError):
        stats["invalid_timestamps"] += 1

    try:
        open_price = float(fields[2])
        high_price = float(fields[3])
        low_price = float(fields[4])
        close_price = float(fields[5])

        prices = [
            open_price,
            high_price,
            low_price,
            close_price,
        ]

        if not all(math.isfinite(price) for price in prices):
            raise ValueError("Non-finite OHLC value.")

        if (
            low_price <= 0
            or high_price < low_price
            or high_price < max(open_price, close_price)
            or low_price > min(open_price, close_price)
        ):
            stats["invalid_ohlc"] += 1

        if (
            open_price == high_price
            == low_price == close_price
        ):
            stats["flat_candles"] += 1

    except (TypeError, ValueError):
        stats["invalid_ohlc"] += 1

    try:
        volume = int(fields[6])

        if volume == 0:
            stats["zero_volume"] += 1
        elif volume < 0:
            stats["negative_volume"] += 1

    except (TypeError, ValueError):
        stats["invalid_volume"] += 1


def analyze_dump(file_path):
    if not file_path.is_file():
        raise FileNotFoundError(
            f"SQL dump not found: {file_path}"
        )

    stats_by_table = defaultdict(new_stats)

    print("\nStarting historical data analysis...")
    print(f"File: {file_path}")
    print(f"Size: {file_path.stat().st_size / (1024 * 1024):.2f} MB")

    current_table = None
    statement_parts = []
    total_statements = 0

    def process_statement(statement):
        nonlocal total_statements

        match = INSERT_PATTERN.search(statement)

        if not match:
            return

        table_name = match.group(1)
        table_stats = stats_by_table[table_name]

        for row in parse_insert_rows(statement, match.end()):
            update_stats(table_stats, row)

        total_statements += 1

        print(
            f"Processed INSERT {total_statements}: "
            f"{table_name}"
        )

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as sql_file:

        for line in sql_file:
            if current_table is None:
                match = INSERT_PATTERN.search(line)

                if not match:
                    continue

                current_table = match.group(1)
                statement_parts = [line]

            else:
                statement_parts.append(line)

            if line.rstrip().endswith(";"):
                process_statement("".join(statement_parts))
                current_table = None
                statement_parts = []

    incomplete_statement = current_table is not None

    report = [
        "MARKET CYCLE TRACKER - HISTORICAL DATA AUDIT",
        "=" * 65,
        f"Source file: {file_path.name}",
        f"Source size: {file_path.stat().st_size / (1024 * 1024):.2f} MB",
        f"INSERT statements processed: {total_statements}",
        "",
    ]

    for table_name in EXPECTED_TABLES:
        stats = stats_by_table.get(table_name)

        report.append("-" * 65)
        report.append(f"TABLE: {table_name}")

        if not stats or stats["rows"] == 0:
            report.append("No records found.")
            continue

        report.extend([
            f"Total records: {stats['rows']:,}",
            f"ID range: {stats['min_id']} to {stats['max_id']}",
            f"First timestamp: {stats['first_timestamp']}",
            f"Last timestamp: {stats['last_timestamp']}",
            f"Distinct dates: {len(stats['unique_dates']):,}",
            f"Duplicate IDs: {stats['duplicate_ids']:,}",
            f"Duplicate timestamps: {stats['duplicate_timestamps']:,}",
            f"Out-of-order records: {stats['out_of_order']:,}",
            f"Invalid timestamps: {stats['invalid_timestamps']:,}",
            f"Malformed records: {stats['malformed_rows']:,}",
            f"Rows containing NULL: {stats['null_values']:,}",
            f"Invalid OHLC records: {stats['invalid_ohlc']:,}",
            f"Flat candles: {stats['flat_candles']:,}",
            f"Zero volume records: {stats['zero_volume']:,}",
            f"Negative volume records: {stats['negative_volume']:,}",
            f"Invalid volume records: {stats['invalid_volume']:,}",
        ])

    report.extend([
        "",
        "=" * 65,
        "TABLES FOUND IN DUMP",
        ", ".join(sorted(stats_by_table.keys())),
        "",
        f"Incomplete final INSERT statement: {incomplete_statement}",
        "Original SQL dump was only read; it was not modified.",
    ])

    output_file = (
        Path("E:/market-cycle-tracker/docs")
        / "historical_data_audit.txt"
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print("\n".join(report))
    print(f"\nAudit report saved to: {output_file}")


if __name__ == "__main__":
    source = input(
        "\nEnter full path to Dump20260308.sql: "
    ).strip().strip('"')

    analyze_dump(Path(source))
