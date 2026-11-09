
import json
import sqlite3

from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB = (
    ROOT
    / "backend"
    / "data"
    / "historical_staging.db"
)

START_DATE = date(2020, 8, 16)
END_DATE = date(2021, 8, 15)

EXPECTED_RECORDS = 50

ISSUE_CODE = "suspected_wrong_timeframe_weekly_sunday_series"


def main():
    if not DB.is_file():
        raise FileNotFoundError(DB)

    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        rows = connection.execute("""
            SELECT
                r.id AS raw_record_id,
                r.source_id,
                r.source_timestamp,
                q.record_status,
                q.close_eligible,
                q.full_ohlc_eligible,
                q.issue_codes

            FROM raw_daily_records r

            JOIN daily_quality_assessments q
                ON q.raw_record_id = r.id

            WHERE r.import_batch_id = 1
              AND r.instrument_code = 'INDIA_VIX'
              AND r.source_table = 'indiavix_1d'

            ORDER BY r.source_timestamp
        """).fetchall()

        targets = []

        for row in rows:
            session_date = date.fromisoformat(
                row["source_timestamp"][:10]
            )

            if (
                START_DATE <= session_date <= END_DATE
                and session_date.weekday() == 6
            ):
                targets.append(row)

        unique_dates = {
            row["source_timestamp"][:10]
            for row in targets
        }

        if len(targets) != EXPECTED_RECORDS:
            raise RuntimeError(
                f"Expected {EXPECTED_RECORDS} Sunday records, "
                f"found {len(targets)}. No records updated."
            )

        if len(unique_dates) != EXPECTED_RECORDS:
            raise RuntimeError(
                "Duplicate Sunday timestamps found. "
                "No records updated."
            )

        now = datetime.now(timezone.utc).isoformat()

        print("Records selected:", len(targets))
        print("Date range:", START_DATE, "to", END_DATE)

        connection.execute("BEGIN IMMEDIATE")

        update_sql = """
            UPDATE daily_quality_assessments
            SET record_status = 'review_required',
                close_eligible = 0,
                full_ohlc_eligible = 0,
                issue_codes = ?,
                assessed_at_utc = ?
            WHERE raw_record_id = ?
              AND import_batch_id = 1
        """

        updated = 0

        for row in targets:
            issues = json.loads(row["issue_codes"])

            if ISSUE_CODE not in issues:
                issues.append(ISSUE_CODE)

            connection.execute(
                update_sql,
                (
                    json.dumps(sorted(set(issues))),
                    now,
                    row["raw_record_id"],
                ),
            )

            updated += 1

        connection.commit()

        print("\n========== RECLASSIFICATION ==========")
        print("Updated records:", updated)
        print("New status: review_required")
        print("Close eligible: false")
        print("Full OHLC eligible: false")
        print("Raw records modified: 0")

        flagged = connection.execute("""
            SELECT COUNT(*)
            FROM daily_quality_assessments
            WHERE import_batch_id = 1
              AND issue_codes LIKE ?
        """, (f"%{ISSUE_CODE}%",)).fetchone()[0]

        print("Total records carrying flag:", flagged)

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        print("SQLite integrity:", integrity)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
