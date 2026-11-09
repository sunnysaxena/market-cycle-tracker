
import csv
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "data" / "historical_staging.db"

EXCHANGES = {
    "NIFTY50": "NSE",
    "BANKNIFTY": "NSE",
    "FINNIFTY": "NSE",
    "MIDCPNIFTY": "NSE",
    "INDIA_VIX": "NSE",
    "SENSEX": "BSE",
}


def main():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    batch = connection.execute("""
        SELECT id FROM import_batches
        WHERE status = 'completed'
        ORDER BY id DESC LIMIT 1
    """).fetchone()

    if not batch:
        raise RuntimeError("No completed import batch found.")

    batch_id = batch["id"]
    output_rows = []
    report = []

    for instrument, exchange in EXCHANGES.items():
        rows = connection.execute("""
            SELECT DISTINCT candle_date
            FROM daily_close_series
            WHERE import_batch_id = ?
              AND instrument_code = ?
            ORDER BY candle_date
        """, (batch_id, instrument)).fetchall()

        dates = {
            date.fromisoformat(row["candle_date"])
            for row in rows
        }

        if not dates:
            report.append(f"{instrument}: NO DATA")
            continue

        first = min(dates)
        last = max(dates)
        candidates = []

        current = first

        while current <= last:
            if current.weekday() < 5 and current not in dates:
                candidates.append(current)

                output_rows.append({
                    "instrument": instrument,
                    "exchange": exchange,
                    "candidate_missing_date": current.isoformat(),
                    "classification": "unverified_weekday_gap",
                })

            current += timedelta(days=1)

        weekend_sessions = sorted(
            d for d in dates if d.weekday() >= 5
        )

        report.extend([
            "",
            f"{instrument} ({exchange})",
            f"First date: {first}",
            f"Last date: {last}",
            f"Observed sessions: {len(dates):,}",
            f"Candidate weekday gaps: {len(candidates):,}",
            f"Weekend/special sessions: {len(weekend_sessions):,}",
        ])

    output = ROOT / "docs" / "candidate_session_gaps.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "instrument",
                "exchange",
                "candidate_missing_date",
                "classification",
            ],
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print("\nDAILY SESSION GAP AUDIT")
    print("=" * 55)
    print("\n".join(report))
    print(f"\nTotal candidate gaps: {len(output_rows):,}")
    print(f"CSV report: {output}")

    print(
        "\nIMPORTANT: These are weekday gaps, not confirmed "
        "missing exchange sessions. Holidays require calendar validation."
    )

    connection.close()


if __name__ == "__main__":
    main()
