
import csv
import sqlite3

from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB = ROOT / "backend" / "data" / "historical_staging.db"
GAP_FILE = ROOT / "docs" / "peer_supported_gaps.csv"
WEEKEND_FILE = ROOT / "docs" / "weekend_sessions.csv"


def inspect_banknifty_gaps():
    grouped = defaultdict(list)

    with GAP_FILE.open(
        newline="",
        encoding="utf-8",
    ) as file:
        for row in csv.DictReader(file):
            if row["instrument"] == "BANKNIFTY":
                grouped[row["candidate_missing_date"][:7]].append(
                    row["candidate_missing_date"]
                )

    print("\nBANK NIFTY CANDIDATE GAPS BY MONTH")
    print("=" * 65)

    for month in sorted(grouped):
        dates = sorted(grouped[month])

        print(
            f"{month}: {len(dates):3} dates | "
            f"First: {dates[0]} | Last: {dates[-1]}"
        )


def inspect_india_vix_weekends():
    peer_matches = {}

    with WEEKEND_FILE.open(
        newline="",
        encoding="utf-8",
    ) as file:
        for row in csv.DictReader(file):
            if row["instrument"] == "INDIA_VIX":
                peer_matches[row["date"]] = row["matching_peers"]

    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    rows = connection.execute("""
        SELECT
            source_id,
            source_timestamp,
            open_raw,
            high_raw,
            low_raw,
            close_raw,
            volume_raw
        FROM raw_daily_records
        WHERE import_batch_id = 1
          AND instrument_code = 'INDIA_VIX'
        ORDER BY source_timestamp, source_row_number
    """).fetchall()

    connection.close()

    print("\nINDIA VIX WEEKEND RECORD DETAILS")
    print("=" * 100)

    for row in rows:
        timestamp = date.fromisoformat(
            row["source_timestamp"][:10]
        )

        if timestamp.weekday() < 5:
            continue

        print(
            f"ID={row['source_id']} | "
            f"Date={timestamp} | "
            f"Day={timestamp.strftime('%A')} | "
            f"O={row['open_raw']} | "
            f"H={row['high_raw']} | "
            f"L={row['low_raw']} | "
            f"C={row['close_raw']} | "
            f"V={row['volume_raw']} | "
            f"Peer matches={peer_matches.get(timestamp.isoformat(), 'Unknown')}"
        )


def main():
    if not DB.is_file():
        raise FileNotFoundError(DB)

    if not GAP_FILE.is_file() or not WEEKEND_FILE.is_file():
        raise FileNotFoundError("Required comparison CSV files missing.")

    inspect_banknifty_gaps()
    inspect_india_vix_weekends()


if __name__ == "__main__":
    main()
