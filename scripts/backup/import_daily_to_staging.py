
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

STAGING_DB = (
    PROJECT_ROOT
    / "backend"
    / "data"
    / "historical_staging.db"
)

TABLE_MAPPING = {
    "finnifty_1d": "FINNIFTY",
    "indiavix_1d": "INDIA_VIX",
    "midnifty_1d": "MIDCPNIFTY",
    "nifty50_1d": "NIFTY50",
    "niftybank_1d": "BANKNIFTY",
    "sensex_1d": "SENSEX",
}

INSERT_PATTERN = re.compile(
    r"INSERT\s+INTO\s+`([^`]+)`\s+VALUES\s*",
    re.IGNORECASE,
)


def calculate_sha256(file_path: Path) -> str:
    """Calculate a fingerprint without loading the file into memory."""

    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        while True:
            chunk = file.read(4 * 1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def decode_sql_value(value: str):
    value = value.strip()

    if value.upper() == "NULL":
        return None

    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
        value = value.replace("\\'", "'")
        value = value.replace("\\\\", "\\")
        value = value.replace("''", "'")

    return value


def iter_insert_rows(statement: str):
    """Parse individual tuples from one MySQL INSERT statement."""

    match = INSERT_PATTERN.search(statement)

    if not match:
        return

    position = match.end()
    length = len(statement)

    while position < length:

        while (
            position < length
            and statement[position] in " \r\n\t,"
        ):
            position += 1

        if position >= length or statement[position] == ";":
            return

        if statement[position] != "(":
            raise ValueError(
                f"Unexpected SQL content at position {position}"
            )

        position += 1
        field_start = position
        fields = []

        in_quote = False
        escaped = False
        tuple_complete = False

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
                    fields.append(
                        statement[field_start:position].strip()
                    )
                    field_start = position + 1

                elif char == ")":
                    fields.append(
                        statement[field_start:position].strip()
                    )

                    position += 1
                    tuple_complete = True

                    yield [
                        decode_sql_value(value)
                        for value in fields
                    ]

                    break

            position += 1

        if not tuple_complete:
            raise ValueError(
                "Incomplete or malformed SQL value tuple."
            )


def iter_daily_insert_statements(file_path: Path):
    """
    Read only the six Daily INSERT statements.

    One SQL INSERT statement is buffered at a time.
    The one-minute datasets are skipped.
    """

    current_table = None
    statement_lines = []

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as file:

        for line in file:

            if current_table is None:
                match = INSERT_PATTERN.search(line)

                if not match:
                    continue

                table_name = match.group(1)

                if table_name not in TABLE_MAPPING:
                    continue

                current_table = table_name
                statement_lines = [line]

            else:
                statement_lines.append(line)

            if line.rstrip().endswith(";"):

                yield (
                    current_table,
                    "".join(statement_lines),
                )

                current_table = None
                statement_lines = []

    if current_table is not None:
        raise ValueError(
            f"Incomplete INSERT statement for {current_table}"
        )


def create_staging_schema(connection: sqlite3.Connection):

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL UNIQUE,
            source_size_bytes INTEGER NOT NULL,
            status TEXT NOT NULL,
            imported_rows INTEGER NOT NULL DEFAULT 0,
            imported_at_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS raw_daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            import_batch_id INTEGER NOT NULL,

            instrument_code TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_row_number INTEGER NOT NULL,

            source_id TEXT,
            source_timestamp TEXT,

            open_raw TEXT,
            high_raw TEXT,
            low_raw TEXT,
            close_raw TEXT,
            volume_raw TEXT,

            FOREIGN KEY (import_batch_id)
                REFERENCES import_batches(id),

            UNIQUE (
                import_batch_id,
                source_table,
                source_row_number
            )
        );

        CREATE INDEX IF NOT EXISTS
            idx_raw_daily_instrument_timestamp
        ON raw_daily_records (
            instrument_code,
            source_timestamp
        );

        CREATE INDEX IF NOT EXISTS
            idx_raw_daily_source_table
        ON raw_daily_records (source_table);
    """)


def import_daily_dump(source_path: Path):

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    STAGING_DB.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_size = source_path.stat().st_size
    file_hash = calculate_sha256(source_path)

    print("\n========== DAILY HISTORICAL IMPORT ==========")
    print(f"Source: {source_path}")
    print(f"Size: {file_size / (1024 * 1024):.2f} MB")
    print(f"SHA-256: {file_hash}")

    connection = sqlite3.connect(
        STAGING_DB,
        timeout=60,
    )

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")

    create_staging_schema(connection)

    existing = connection.execute(
        """
        SELECT id, status, imported_rows
        FROM import_batches
        WHERE source_sha256 = ?
        """,
        (file_hash,),
    ).fetchone()

    if existing:
        print("\nThis exact SQL dump has already been imported.")
        print(f"Batch ID: {existing[0]}")
        print(f"Status: {existing[1]}")
        print(f"Rows: {existing[2]:,}")

        connection.close()
        return

    counts = {
        table: 0
        for table in TABLE_MAPPING
    }

    table_statements = {
        table: 0
        for table in TABLE_MAPPING
    }

    batch_id = None
    total_rows = 0
    pending_rows = []

    insert_sql = """
        INSERT INTO raw_daily_records (
            import_batch_id,
            instrument_code,
            source_table,
            source_row_number,
            source_id,
            source_timestamp,
            open_raw,
            high_raw,
            low_raw,
            close_raw,
            volume_raw
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    try:
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.execute(
            """
            INSERT INTO import_batches (
                source_path,
                source_sha256,
                source_size_bytes,
                status,
                imported_rows
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(source_path.resolve()),
                file_hash,
                file_size,
                "importing",
                0,
            ),
        )

        batch_id = cursor.lastrowid

        for table_name, statement in iter_daily_insert_statements(
            source_path
        ):

            instrument_code = TABLE_MAPPING[table_name]
            table_statements[table_name] += 1

            for fields in iter_insert_rows(statement):

                row_number = counts[table_name] + 1

                if len(fields) != 7:
                    raise ValueError(
                        f"{table_name}, row {row_number}: "
                        f"Expected 7 fields, got {len(fields)}"
                    )

                pending_rows.append((
                    batch_id,
                    instrument_code,
                    table_name,
                    row_number,
                    fields[0],
                    fields[1],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                    fields[6],
                ))

                counts[table_name] += 1
                total_rows += 1

                if len(pending_rows) >= 1000:
                    connection.executemany(
                        insert_sql,
                        pending_rows,
                    )
                    pending_rows.clear()

            print(
                f"Processed {table_name}: "
                f"{counts[table_name]:,} records"
            )

        if pending_rows:
            connection.executemany(
                insert_sql,
                pending_rows,
            )

        missing_tables = [
            table
            for table, count in counts.items()
            if count == 0
        ]

        if missing_tables:
            raise ValueError(
                "Missing Daily datasets: "
                + ", ".join(missing_tables)
            )

        connection.execute(
            """
            UPDATE import_batches
            SET status = ?,
                imported_rows = ?,
                imported_at_utc = ?
            WHERE id = ?
            """,
            (
                "completed",
                total_rows,
                datetime.now(timezone.utc).isoformat(),
                batch_id,
            ),
        )

        connection.commit()

        print("\n========== IMPORT SUMMARY ==========")

        for table, count in counts.items():
            print(f"{table}: {count:,}")

        print(f"\nTotal Daily records: {total_rows:,}")
        print(f"Import batch ID: {batch_id}")
        print("Status: COMPLETED")
        print(f"Staging database: {STAGING_DB}")

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        print(f"SQLite integrity check: {integrity}")

    except Exception:
        connection.rollback()
        print("\nIMPORT FAILED. Transaction rolled back.")
        raise

    finally:
        connection.close()


if __name__ == "__main__":

    source = input(
        "\nEnter full path to Dump20260308.sql: "
    ).strip().strip('"')

    import_daily_dump(Path(source))
