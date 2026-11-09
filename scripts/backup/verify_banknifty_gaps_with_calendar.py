"""Calendar-aware verification of BANKNIFTY daily data gaps for 2015-2016.

Reads backend/data/historical_staging.db and writes a CSV report. It does not
modify the database or historical price records.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
OUTPUT = ROOT / "backend" / "data" / "banknifty_calendar_gap_verification_2015_2016.csv"
YEARS = (2015, 2016)
TARGET = "BANKNIFTY"
PEER_INDICES = ("NIFTY50", "FINNIFTY", "INDIA_VIX")


def fetch_dates(connection: sqlite3.Connection, instrument_code: str) -> set[date]:
    rows = connection.execute(
        """
        SELECT candle_date
        FROM daily_close_series
        WHERE instrument_code = ?
          AND candle_date >= '2015-01-01'
          AND candle_date <= '2016-12-31'
        """,
        (instrument_code,),
    ).fetchall()

    result: set[date] = set()
    for (value,) in rows:
        result.add(date.fromisoformat(str(value)[:10]))
    return result


def load_calendar(connection: sqlite3.Connection):
    years = {
        int(row[0]): {
            "source_title": row[1],
            "verification_level": row[2],
            "coverage_status": row[3],
        }
        for row in connection.execute(
            """
            SELECT calendar_year, source_title, verification_level, coverage_status
            FROM exchange_calendar_years
            WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
              AND calendar_year IN (2015, 2016)
            """
        )
    }

    events = {}
    for row in connection.execute(
        """
        SELECT session_date, event_type, event_name,
               verification_level, source_title, source_reference
        FROM exchange_calendar_events
        WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
          AND calendar_year IN (2015, 2016)
        """
    ):
        session_date = date.fromisoformat(str(row[0])[:10])
        events[session_date] = {
            "event_type": row[1],
            "event_name": row[2],
            "verification_level": row[3],
            "source_title": row[4],
            "source_reference": row[5] or "",
        }

    missing_years = sorted(set(YEARS) - set(years))
    if missing_years:
        raise RuntimeError(
            "Calendar metadata missing for year(s): "
            + ", ".join(map(str, missing_years))
        )

    return years, events


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    connection = sqlite3.connect(DATABASE)
    try:
        banknifty_dates = fetch_dates(connection, TARGET)
        peer_dates = {code: fetch_dates(connection, code) for code in PEER_INDICES}
        calendar_years, calendar_events = load_calendar(connection)

        if not banknifty_dates:
            raise RuntimeError("No BANKNIFTY close-series records found for 2015-2016.")

        report_rows = []
        counters = Counter()
        special_session_checks = []

        for year in YEARS:
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            year_meta = calendar_years[year]
            counters[f"{year}_calendar_verification"] = year_meta["verification_level"]

            for current in daterange(year_start, year_end):
                event = calendar_events.get(current)
                is_weekend = current.weekday() >= 5
                has_banknifty = current in banknifty_dates
                present_peers = [code for code in PEER_INDICES if current in peer_dates[code]]

                # Weekends are normally closed. Only explicit special sessions
                # are assessed as possible missing BANKNIFTY records.
                if is_weekend and not (event and event["event_type"] == "special_session_open"):
                    continue

                if has_banknifty:
                    if event and event["event_type"] == "special_session_open":
                        special_session_checks.append({
                            "date": current.isoformat(),
                            "event_name": event["event_name"],
                            "banknifty_record": "present",
                            "peer_count": len(present_peers),
                            "peer_indices": ";".join(present_peers),
                            "calendar_verification": event["verification_level"],
                        })
                    continue

                if event and event["event_type"] == "holiday_closed":
                    counters[f"{year}_holiday_dates_excluded"] += 1
                    continue

                if event and event["event_type"] == "special_session_open":
                    classification = "special_session_without_BANKNIFTY_record"
                    evidence = (
                        "peer_indices_also_have_data" if present_peers
                        else "no_peer_data_found"
                    )
                    next_action = (
                        "Strong evidence a market session occurred; verify BANKNIFTY "
                        "coverage against an independent NSE index source."
                        if present_peers else
                        "Verify whether BANKNIFTY was published for this special session."
                    )
                    special_session_checks.append({
                        "date": current.isoformat(),
                        "event_name": event["event_name"],
                        "banknifty_record": "missing",
                        "peer_count": len(present_peers),
                        "peer_indices": ";".join(present_peers),
                        "calendar_verification": event["verification_level"],
                    })
                else:
                    classification = "weekday_without_BANKNIFTY_record"
                    if len(present_peers) == len(PEER_INDICES):
                        evidence = "strong_all_3_NSE_peer_indices_present"
                        next_action = (
                            "Strong NSE-session evidence; verify BANKNIFTY candle against "
                            "an independent NSE index source."
                        )
                    elif present_peers:
                        evidence = "partial_NSE_peer_support"
                        next_action = (
                            "Some NSE peer indices have data; verify date and BANKNIFTY "
                            "publication independently."
                        )
                    else:
                        evidence = "no_NSE_peer_data_found"
                        next_action = (
                            "Unverified candidate; check official exchange session records "
                            "and source coverage."
                        )

                row = {
                    "date": current.isoformat(),
                    "weekday": current.strftime("%A"),
                    "year": year,
                    "classification": classification,
                    "calendar_year_verification": year_meta["verification_level"],
                    "calendar_source": year_meta["source_title"],
                    "calendar_event": event["event_name"] if event else "",
                    "event_verification": event["verification_level"] if event else "",
                    "banknifty_record": "missing",
                    "peer_count": len(present_peers),
                    "peer_indices": ";".join(present_peers),
                    "evidence_level": evidence,
                    "recommended_follow_up": next_action,
                }
                report_rows.append(row)
                counters[f"{year}_candidate_dates"] += 1
                counters[f"{year}_peer_support_{len(present_peers)}"] += 1
                counters[f"{year}_{classification}"] += 1

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "date", "weekday", "year", "classification",
            "calendar_year_verification", "calendar_source", "calendar_event",
            "event_verification", "banknifty_record", "peer_count",
            "peer_indices", "evidence_level", "recommended_follow_up",
        ]
        with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

        print("\nBANKNIFTY CALENDAR-AWARE GAP VERIFICATION")
        print("=" * 68)
        for year in YEARS:
            meta = calendar_years[year]
            observed = sum(1 for d in banknifty_dates if d.year == year)
            print(
                f"{year}: BANKNIFTY close records={observed} | "
                f"calendar={meta['verification_level']} | "
                f"source={meta['source_title']}"
            )
            print(f"  Holiday dates excluded: {counters[f'{year}_holiday_dates_excluded']}")
            print(f"  Missing weekday/special-session candidates: {counters[f'{year}_candidate_dates']}")
            for peer_count in range(4):
                print(
                    f"  Candidates supported by {peer_count}/3 NSE peer indices: "
                    f"{counters[f'{year}_peer_support_{peer_count}']}"
                )

        strong_count = sum(
            1 for row in report_rows
            if row["evidence_level"] == "strong_all_3_NSE_peer_indices_present"
        )
        partial_count = sum(
            1 for row in report_rows
            if row["evidence_level"] == "partial_NSE_peer_support"
        )
        no_peer_count = sum(
            1 for row in report_rows
            if row["evidence_level"] == "no_NSE_peer_data_found"
        )
        print("\nCOMBINED SUMMARY")
        print(f"Candidate dates: {len(report_rows)}")
        print(f"All 3 peers present: {strong_count}")
        print(f"1 or 2 peers present: {partial_count}")
        print(f"No peers present: {no_peer_count}")

        print("\nSPECIAL SESSION CHECKS")
        if special_session_checks:
            for item in special_session_checks:
                print(
                    f"{item['date']} | {item['event_name']} | "
                    f"BANKNIFTY={item['banknifty_record']} | "
                    f"peers={item['peer_count']}/3 ({item['peer_indices'] or 'none'}) | "
                    f"calendar={item['calendar_verification']}"
                )
        else:
            print("No special-session records found in the loaded calendar.")

        print(f"\nCSV report: {OUTPUT}")
        print("Database changes: none (read-only analysis).")
        print("Important: peer data supports that a market session occurred; it does not by itself prove the BANKNIFTY source record is recoverable or missing from NSE's official archive.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
