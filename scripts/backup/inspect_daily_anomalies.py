
import re
from pathlib import Path
from collections import defaultdict

TARGET_TABLES = {
    "indiavix_1d",
    "finnifty_1d",
    "niftybank_1d",
}

INSERT_PATTERN = re.compile(
    r"INSERT\s+INTO\s+`([^`]+)`\s+VALUES\s*",
    re.IGNORECASE,
)


def decode(value):
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
    match = INSERT_PATTERN.search(statement)

    if not match:
        return

    pos = match.end()
    fields = []
    start = pos
    quoted = False
    escaped = False

    while pos < len(statement):
        char = statement[pos]

        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                if pos + 1 < len(statement) and statement[pos + 1] == "'":
                    pos += 1
                else:
                    quoted = False
        else:
            if char == "'":
                quoted = True
            elif char == ",":
                fields.append(statement[start:pos].strip())
                start = pos + 1
            elif char == ")" and fields:
                fields.append(statement[start:pos].strip())
                yield [decode(v) for v in fields]
                fields = []
                pos += 1

                while pos < len(statement) and statement[pos] in " \r\n\t,":
                    pos += 1

                if pos < len(statement) and statement[pos] == "(":
                    start = pos + 1
                    pos = start
                    continue

                return
            elif char == "(":
                start = pos + 1

        pos += 1


def invalid_ohlc(row):
    try:
        o, h, l, c = map(float, row[2:6])

        if min(o, h, l, c) <= 0:
            return "Non-positive price"

        if h < l:
            return "High below Low"

        if h < max(o, c):
            return "High below Open/Close"

        if l > min(o, c):
            return "Low above Open/Close"

    except (ValueError, TypeError, IndexError):
        return "Unparseable OHLC"

    return None


def main(dump_path):
    if not dump_path.is_file():
        raise FileNotFoundError(dump_path)

    output = [
        "DAILY DATA ANOMALY INSPECTION",
        "=" * 65,
    ]

    india_vix_seen = {}
    india_vix_duplicates = []
    india_vix_invalid = []

    flat_by_table = defaultdict(list)

    print("Scanning targeted Daily tables...")

    current_table = None
    statement_lines = []

    def process_statement():
        if current_table not in TARGET_TABLES:
            return

        statement = "".join(statement_lines)

        for row in extract_rows(statement):
            if len(row) != 7:
                continue

            record = {
                "id": row[0],
                "timestamp": row[1],
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
                "volume": row[6],
            }

            reason = invalid_ohlc(row)

            if current_table == "indiavix_1d":
                timestamp = row[1]

                if timestamp in india_vix_seen:
                    india_vix_duplicates.append({
                        "previous": india_vix_seen[timestamp],
                        "duplicate": record,
                    })
                else:
                    india_vix_seen[timestamp] = record

                if reason:
                    india_vix_invalid.append({
                        "record": record,
                        "reason": reason,
                    })

            if not reason:
                try:
                    prices = list(map(float, row[2:6]))

                    if prices[0] == prices[1] == prices[2] == prices[3]:
                        flat_by_table[current_table].append(record)
                except ValueError:
                    pass

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

                if table not in TARGET_TABLES:
                    continue

                current_table = table
                statement_lines = [line]

            else:
                statement_lines.append(line)

            if line.rstrip().endswith(";"):
                process_statement()
                current_table = None
                statement_lines = []

    output.extend([
        "",
        "INDIA VIX DUPLICATE TIMESTAMPS",
        "-" * 65,
        f"Duplicate records: {len(india_vix_duplicates)}",
    ])

    for item in india_vix_duplicates:
        output.append(f"\nTimestamp: {item['duplicate']['timestamp']}")
        output.append(f"Original: {item['previous']}")
        output.append(f"Duplicate: {item['duplicate']}")

    output.extend([
        "",
        "INDIA VIX INVALID OHLC",
        "-" * 65,
        f"Invalid records: {len(india_vix_invalid)}",
    ])

    for item in india_vix_invalid:
        output.append(f"\nReason: {item['reason']}")
        output.append(str(item["record"]))

    for table in ("finnifty_1d", "niftybank_1d"):
        records = flat_by_table[table]
        by_year = defaultdict(int)

        for record in records:
            by_year[record["timestamp"][:4]] += 1

        output.extend([
            "",
            f"{table.upper()} FLAT CANDLES",
            "-" * 65,
            f"Total: {len(records)}",
            f"By year: {dict(sorted(by_year.items()))}",
        ])

        for record in records[:30]:
            output.append(str(record))

        if len(records) > 30:
            output.append(
                f"... {len(records) - 30} additional records not displayed."
            )

    report_path = (
        Path("E:/market-cycle-tracker/docs")
        / "daily_anomaly_details.txt"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(output), encoding="utf-8")

    print("\n".join(output))
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    path = input(
        "Enter full path to Dump20260308.sql: "
    ).strip().strip('"')

    main(Path(path))
