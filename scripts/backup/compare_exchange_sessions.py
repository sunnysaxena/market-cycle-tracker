
import csv
import sqlite3

from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DB = ROOT / "backend" / "data" / "historical_staging.db"
REPORT_DIR = ROOT / "docs"

EXCHANGE_GROUPS = {
    "NSE": [
        "NIFTY50",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "INDIA_VIX",
    ],
    "BSE": [
        "SENSEX",
    ],
}


def load_trading_dates(connection, batch_id):
    rows = connection.execute("""
        SELECT instrument_code, candle_date
        FROM daily_close_series
        WHERE import_batch_id = ?
        ORDER BY instrument_code, candle_date
    """, (batch_id,)).fetchall()

    dates = defaultdict(set)

    for row in rows:
        dates[row["instrument_code"]].add(
            date.fromisoformat(row["candle_date"])
        )

    return dates


def main():
    if not DB.is_file():
        raise FileNotFoundError(DB)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    try:
        batch = connection.execute("""
            SELECT id
            FROM import_batches
            WHERE status = 'completed'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if not batch:
            raise RuntimeError("No completed import batch found.")

        dates_by_instrument = load_trading_dates(
            connection,
            batch["id"],
        )

        gap_rows = []
        weekend_rows = []
        report = [
            "CROSS-INDEX TRADING SESSION COMPARISON",
            "=" * 70,
            f"Import batch: {batch['id']}",
            "",
            "Note: Results are unverified candidates, not confirmed gaps.",
            "",
        ]

        for exchange, instruments in EXCHANGE_GROUPS.items():

            report.extend([
                "",
                f"EXCHANGE: {exchange}",
                "-" * 70,
            ])

            for instrument in instruments:
                dates = dates_by_instrument.get(
                    instrument,
                    set(),
                )

                if not dates:
                    report.append(f"{instrument}: NO DATA")
                    continue

                first_date = min(dates)
                last_date = max(dates)

                peers = [
                    other for other in instruments
                    if other != instrument
                    and dates_by_instrument.get(other)
                ]

                peer_union = set()

                for peer in peers:
                    peer_union.update(
                        dates_by_instrument[peer]
                    )

                # Compare only within this instrument's
                # own available historical date range.
                peer_union = {
                    d for d in peer_union
                    if first_date <= d <= last_date
                }

                candidate_gaps = sorted(
                    peer_union - dates
                )

                weekends = sorted(
                    d for d in dates
                    if d.weekday() >= 5
                )

                peer_weekends = []

                for weekend_date in weekends:
                    matching_peers = [
                        peer
                        for peer in peers
                        if weekend_date
                        in dates_by_instrument[peer]
                    ]

                    peer_weekends.append((
                        weekend_date,
                        matching_peers,
                    ))

                    weekend_rows.append({
                        "exchange": exchange,
                        "instrument": instrument,
                        "date": weekend_date.isoformat(),
                        "weekday": weekend_date.strftime("%A"),
                        "matching_peer_count": len(matching_peers),
                        "matching_peers": ",".join(matching_peers),
                        "classification": "unverified_weekend_session",
                    })

                for gap_date in candidate_gaps:
                    matching_peers = [
                        peer
                        for peer in peers
                        if gap_date in dates_by_instrument[peer]
                    ]

                    gap_rows.append({
                        "exchange": exchange,
                        "instrument": instrument,
                        "candidate_missing_date": gap_date.isoformat(),
                        "matching_peer_count": len(matching_peers),
                        "matching_peers": ",".join(matching_peers),
                        "classification": "peer_supported_candidate_gap",
                    })

                report.extend([
                    "",
                    f"Instrument: {instrument}",
                    f"First date: {first_date}",
                    f"Last date: {last_date}",
                    f"Observed unique dates: {len(dates):,}",
                    f"Same-exchange peers: {len(peers)}",
                    f"Peer-supported candidate gaps: {len(candidate_gaps):,}",
                    f"Weekend-dated records: {len(weekends):,}",
                ])

                if not peers:
                    report.append(
                        "Peer comparison unavailable; "
                        "official exchange calendar required."
                    )

                if weekend_rows:
                    current_weekends = [
                        item for item in weekend_rows
                        if item["instrument"] == instrument
                    ]

                    supported = sum(
                        item["matching_peer_count"] > 0
                        for item in current_weekends
                    )

                    report.append(
                        f"Weekend dates also present in peers: {supported}"
                    )

        # Save peer-supported weekday gaps.
        gap_file = REPORT_DIR / "peer_supported_gaps.csv"

        with gap_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            fields = [
                "exchange",
                "instrument",
                "candidate_missing_date",
                "matching_peer_count",
                "matching_peers",
                "classification",
            ]

            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(gap_rows)

        # Save all observed weekend dates.
        weekend_file = REPORT_DIR / "weekend_sessions.csv"

        with weekend_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            fields = [
                "exchange",
                "instrument",
                "date",
                "weekday",
                "matching_peer_count",
                "matching_peers",
                "classification",
            ]

            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(weekend_rows)

        report.extend([
            "",
            "=" * 70,
            f"Total peer-supported candidate gaps: {len(gap_rows):,}",
            f"Total weekend-dated records: {len(weekend_rows):,}",
            "",
            "No missing records were deleted or modified.",
            "No candidate gap has been declared an actual missing session.",
            "",
            f"Gap report: {gap_file}",
            f"Weekend report: {weekend_file}",
        ])

        text = "\n".join(report)

        report_file = REPORT_DIR / "exchange_session_comparison.txt"
        report_file.write_text(text, encoding="utf-8")

        print(text)
        print(f"\nReport saved: {report_file}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
