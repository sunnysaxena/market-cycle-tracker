
import json
import sqlite3

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATABASE = (
    PROJECT_ROOT
    / "backend"
    / "data"
    / "historical_staging.db"
)

EXPECTED_COUNTS = {
    "FINNIFTY": 3313,
    "INDIA_VIX": 3819,
    "MIDCPNIFTY": 649,
    "NIFTY50": 3728,
    "BANKNIFTY": 3462,
    "SENSEX": 4904,
}


def to_decimal(value):
    if value is None:
        return None

    try:
        result = Decimal(str(value))

        if not result.is_finite():
            return None

        return result

    except InvalidOperation:
        return None


def evaluate_record(row):
    issues = []

    close = to_decimal(row["close_raw"])
    open_price = to_decimal(row["open_raw"])
    high = to_decimal(row["high_raw"])
    low = to_decimal(row["low_raw"])

    try:
        timestamp = datetime.fromisoformat(
            row["source_timestamp"]
        )
        timestamp_valid = True
    except (ValueError, TypeError):
        timestamp_valid = False

    close_eligible = (
        timestamp_valid
        and close is not None
        and close > 0
    )

    valid_prices = all(
        value is not None and value > 0
        for value in (open_price, high, low, close)
    )

    valid_ohlc = (
        valid_prices
        and high >= low
        and high >= max(open_price, close)
        and low <= min(open_price, close)
    )

    if not timestamp_valid:
        issues.append("invalid_timestamp")

    if not valid_ohlc:
        issues.append("invalid_ohlc")

    flat_candle = (
        valid_ohlc
        and open_price == high == low == close
    )

    if flat_candle:
        issues.append("flat_ohlc")

    if not timestamp_valid:
        record_status = "quarantined"

    elif not valid_ohlc:
        record_status = "quarantined"

    elif flat_candle:
        record_status = "review_required"

    else:
        record_status = "accepted"

    return {
        "id": row["id"],
        "import_batch_id": row["import_batch_id"],
        "instrument_code": row["instrument_code"],
        "source_table": row["source_table"],
        "source_timestamp": row["source_timestamp"],
        "source_row_number": row["source_row_number"],
        "record_status": record_status,
        "close_eligible": close_eligible,
        "full_ohlc_eligible": valid_ohlc and not flat_candle,
        "volume_eligible": False,
        "issues": issues,
        "signature": (
            open_price,
            high,
            low,
            close,
            to_decimal(row["volume_raw"]),
        ),
        "close_value": close,
    }


def apply_duplicate_rules(assessments):
    groups = defaultdict(list)

    for item in assessments:
        key = (
            item["instrument_code"],
            item["source_timestamp"],
        )
        groups[key].append(item)

    duplicate_groups = 0
    exact_duplicate_groups = 0
    conflicting_duplicate_groups = 0

    for group in groups.values():
        if len(group) < 2:
            continue

        duplicate_groups += 1
        group.sort(key=lambda item: item["source_row_number"])

        signatures = {
            item["signature"]
            for item in group
        }

        if len(signatures) == 1:
            exact_duplicate_groups += 1

            # Keep the first source occurrence as the
            # deterministic analytical candidate.
            canonical = group[0]

            canonical["issues"].append(
                "exact_duplicate_canonical"
            )

            for duplicate in group[1:]:
                duplicate["record_status"] = "quarantined"
                duplicate["close_eligible"] = False
                duplicate["full_ohlc_eligible"] = False

                duplicate["issues"].append(
                    "exact_duplicate_extra"
                )

        else:
            conflicting_duplicate_groups += 1

            for item in group:
                if item["record_status"] != "quarantined":
                    item["record_status"] = "review_required"

                item["full_ohlc_eligible"] = False
                item["issues"].append(
                    "conflicting_duplicate_timestamp"
                )

            # If every duplicate has the same valid close,
            # retain one observation for close-based analysis.
            closes = {
                item["close_value"]
                for item in group
            }

            close_values_agree = (
                len(closes) == 1
                and None not in closes
            )

            for item in group:
                item["close_eligible"] = False

            if close_values_agree:
                canonical = next(
                    (
                        item for item in group
                        if item["close_value"] is not None
                        and item["close_value"] > 0
                    ),
                    None,
                )

                if canonical:
                    canonical["close_eligible"] = True
                    canonical["issues"].append(
                        "duplicate_close_canonical"
                    )

    return (
        duplicate_groups,
        exact_duplicate_groups,
        conflicting_duplicate_groups,
    )


def create_assessment_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS daily_quality_assessments (
            raw_record_id INTEGER PRIMARY KEY,

            import_batch_id INTEGER NOT NULL,
            instrument_code TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_timestamp TEXT,

            record_status TEXT NOT NULL
                CHECK (
                    record_status IN (
                        'accepted',
                        'review_required',
                        'quarantined'
                    )
                ),

            close_eligible INTEGER NOT NULL,
            full_ohlc_eligible INTEGER NOT NULL,
            volume_eligible INTEGER NOT NULL DEFAULT 0,

            issue_codes TEXT NOT NULL,

            assessed_at_utc TEXT NOT NULL,

            FOREIGN KEY (raw_record_id)
                REFERENCES raw_daily_records(id),

            FOREIGN KEY (import_batch_id)
                REFERENCES import_batches(id)
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_quality_instrument_status
        ON daily_quality_assessments (
            instrument_code,
            record_status
        )
    """)


def run_assessment():
    if not DATABASE.is_file():
        raise FileNotFoundError(
            f"Staging database not found: {DATABASE}"
        )

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        create_assessment_table(connection)

        batch = connection.execute("""
            SELECT id, imported_rows, status
            FROM import_batches
            WHERE status = 'completed'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if not batch:
            raise RuntimeError(
                "No completed historical import batch found."
            )

        batch_id = batch["id"]

        raw_rows = connection.execute("""
            SELECT *
            FROM raw_daily_records
            WHERE import_batch_id = ?
            ORDER BY instrument_code, source_row_number
        """, (batch_id,)).fetchall()

        print(f"Import batch: {batch_id}")
        print(f"Raw records loaded: {len(raw_rows):,}")

        counts = defaultdict(int)
        assessments = []

        for row in raw_rows:
            item = evaluate_record(row)
            assessments.append(item)
            counts[item["instrument_code"]] += 1

        duplicate_results = apply_duplicate_rules(
            assessments
        )

        now = datetime.now(timezone.utc).isoformat()

        connection.execute("BEGIN")

        # Reassessment is repeatable. Raw records are untouched.
        connection.execute("""
            DELETE FROM daily_quality_assessments
            WHERE import_batch_id = ?
        """, (batch_id,))

        insert_sql = """
            INSERT INTO daily_quality_assessments (
                raw_record_id,
                import_batch_id,
                instrument_code,
                source_table,
                source_timestamp,
                record_status,
                close_eligible,
                full_ohlc_eligible,
                volume_eligible,
                issue_codes,
                assessed_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        values = []

        for item in assessments:
            values.append((
                item["id"],
                item["import_batch_id"],
                item["instrument_code"],
                item["source_table"],
                item["source_timestamp"],
                item["record_status"],
                int(item["close_eligible"]),
                int(item["full_ohlc_eligible"]),
                0,
                json.dumps(sorted(set(item["issues"]))),
                now,
            ))

        connection.executemany(insert_sql, values)
        connection.commit()

        report = [
            "HISTORICAL DAILY QUALITY ASSESSMENT",
            "=" * 70,
            f"Database: {DATABASE.name}",
            f"Import batch: {batch_id}",
            f"Raw records: {len(raw_rows):,}",
            "",
            "INSTRUMENT SUMMARY",
            "-" * 70,
        ]

        for instrument in EXPECTED_COUNTS:
            subset = [
                item for item in assessments
                if item["instrument_code"] == instrument
            ]

            accepted = sum(
                item["record_status"] == "accepted"
                for item in subset
            )

            review = sum(
                item["record_status"] == "review_required"
                for item in subset
            )

            quarantined = sum(
                item["record_status"] == "quarantined"
                for item in subset
            )

            close_eligible = sum(
                item["close_eligible"]
                for item in subset
            )

            ohlc_eligible = sum(
                item["full_ohlc_eligible"]
                for item in subset
            )

            report.extend([
                f"\n{instrument}",
                f"  Raw records: {len(subset):,}",
                f"  Accepted: {accepted:,}",
                f"  Review required: {review:,}",
                f"  Quarantined: {quarantined:,}",
                f"  Close eligible: {close_eligible:,}",
                f"  Full OHLC eligible: {ohlc_eligible:,}",
                "  Volume eligible: 0",
            ])

            if len(subset) != EXPECTED_COUNTS[instrument]:
                report.append(
                    "  WARNING: Record count differs from original audit."
                )

        (
            duplicate_groups,
            exact_groups,
            conflicting_groups,
        ) = duplicate_results

        report.extend([
            "",
            "DUPLICATE ANALYSIS",
            "-" * 70,
            f"Duplicate timestamp groups: {duplicate_groups}",
            f"Exact duplicate groups: {exact_groups}",
            f"Conflicting duplicate groups: {conflicting_groups}",
            "",
            "FLAGGED RECORDS",
            "-" * 70,
        ])

        for item in assessments:
            if item["issues"]:
                report.append(
                    f"ID {item['id']} | "
                    f"{item['instrument_code']} | "
                    f"{item['source_timestamp']} | "
                    f"{item['record_status']} | "
                    f"close={item['close_eligible']} | "
                    f"OHLC={item['full_ohlc_eligible']} | "
                    f"issues={','.join(sorted(set(item['issues'])))}"
                )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        report.extend([
            "",
            f"SQLite integrity: {integrity}",
            "Raw historical records were not modified.",
        ])

        output = (
            PROJECT_ROOT
            / "docs"
            / "daily_quality_assessment.txt"
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(report), encoding="utf-8")

        print("\n".join(report))
        print(f"\nReport saved to: {output}")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    run_assessment()
