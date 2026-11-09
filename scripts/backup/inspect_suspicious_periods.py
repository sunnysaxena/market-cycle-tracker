
import csv
import sqlite3

from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB = ROOT / "backend" / "data" / "historical_staging.db"
GAP_FILE = ROOT / "docs" / "peer_supported_gaps.csv"


def inspect_banknifty_gaps(connection):
    print("\nBANK NIFTY — MAJOR GAP PERIODS")
    print("=" * 70)

    candidates = []

    with GAP_FILE.open(
        newline="",
        encoding="utf-8",
    ) as file:
        for row in csv.DictReader(file):
            if row["instrument"] != "BANKNIFTY":
                continue

            if int(row["matching_peer_count"]) < 3:
                continue

            gap_date = date.fromisoformat(
                row["candidate_missing_date"]
            )

            # Exclude weekend dates from this weekday-gap report.
            if gap_date.weekday() < 5:
                candidates.append(gap_date)

    candidates = sorted(set(candidates))

    if not candidates:
        print("No candidate dates found.")
        return

    # Group candidate dates separated by no more than
    # four calendar days, allowing ordinary weekends.
    groups = []
    current = [candidates[0]]

    for gap_date in candidates[1:]:
        difference = (
            gap_date - current[-1]
        ).days

        if difference <= 4:
            current.append(gap_date)
        else:
            groups.append(current)
            current = [gap_date]

    groups.append(current)

    rows = connection.execute("""
        SELECT DISTINCT substr(source_timestamp, 1, 10) AS candle_date
        FROM raw_daily_records
        WHERE import_batch_id = 1
          AND instrument_code = 'BANKNIFTY'
        ORDER BY candle_date
    """).fetchall()

    actual_dates = sorted(
        date.fromisoformat(row["candle_date"])
        for row in rows
    )

    print(f"Candidate gap dates: {len(candidates)}")
    print(f"Gap clusters: {len(groups)}")

    for number, group in enumerate(groups, start=1):
        start = group[0]
        end = group[-1]

        previous_dates = [
            d for d in actual_dates if d < start
        ]

        next_dates = [
            d for d in actual_dates if d > end
        ]

        previous_date = (
            max(previous_dates) if previous_dates else None
        )

        next_date = (
            min(next_dates) if next_dates else None
        )

        print(f"\nGap cluster {number}")
        print(f"Start: {start}")
        print(f"End: {end}")
        print(f"Candidate dates: {len(group)}")
        print(f"Previous BANKNIFTY record: {previous_date}")
        print(f"Next BANKNIFTY record: {next_date}")


def inspect_vix_sunday_runs(connection):
    print("\nINDIA VIX — REPEATED SUNDAY SEQUENCES")
    print("=" * 70)

    rows = connection.execute("""
        SELECT DISTINCT substr(source_timestamp, 1, 10) AS candle_date
        FROM raw_daily_records
        WHERE import_batch_id = 1
          AND instrument_code = 'INDIA_VIX'
        ORDER BY candle_date
    """).fetchall()

    sunday_dates = sorted(
        date.fromisoformat(row["candle_date"])
        for row in rows
        if date.fromisoformat(
            row["candle_date"]
        ).weekday() == 6
    )

    if not sunday_dates:
        print("No Sunday records found.")
        return

    groups = []
    current = [sunday_dates[0]]

    for current_date in sunday_dates[1:]:
        difference = (
            current_date - current[-1]
        ).days

        # Allow a missing week in an otherwise weekly sequence.
        if difference <= 14:
            current.append(current_date)
        else:
            groups.append(current)
            current = [current_date]

    groups.append(current)

    for number, group in enumerate(groups, start=1):
        if len(group) < 3:
            continue

        print(f"\nSequence {number}")
        print(f"First Sunday: {group[0]}")
        print(f"Last Sunday: {group[-1]}")
        print(f"Number of Sunday records: {len(group)}")

        intervals = [
            (group[i] - group[i - 1]).days
            for i in range(1, len(group))
        ]

        print(f"Date intervals: {sorted(set(intervals))}")


def main():
    if not DB.is_file():
        raise FileNotFoundError(DB)

    if not GAP_FILE.is_file():
        raise FileNotFoundError(GAP_FILE)

    connection = sqlite3.connect(DB)

    # Allow database rows to be accessed by column name.
    connection.row_factory = sqlite3.Row

    try:
        inspect_banknifty_gaps(connection)
        inspect_vix_sunday_runs(connection)

    finally:
        connection.close()


if __name__ == "__main__":
    main()
