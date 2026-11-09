"""Build a read-only BANKNIFTY historical gap register for 2015-2016.

The script reads curated daily close dates and the loaded NSE equity calendar.
It does not modify the SQLite database or create/fill price candles.

Classifications:
- exchange_holiday_excluded: regular closed holiday; not a missing-session candidate.
- special_session_requires_review: calendar says a special session was open,
  but BANKNIFTY has no daily close record for that date.
- special_session_record_present: BANKNIFTY record exists on a special session.
- peer_confirmed_candidate: BANKNIFTY absent; both NIFTY50 and FINNIFTY have records.
- partial_peer_evidence: BANKNIFTY absent; one of the two equity peers has a record.
- unconfirmed_candidate: BANKNIFTY absent; neither equity peer has a record.

Peer confirmation corroborates a likely market session, not BANKNIFTY publication,
its value, or recoverability.
"""
from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
OUTPUT = ROOT / "backend" / "data" / "banknifty_historical_gap_register_2015_2016.csv"
YEARS = (2015, 2016)
TARGET = "BANKNIFTY"
EQUITY_PEERS = ("NIFTY50", "FINNIFTY")
VOLATILITY_REFERENCE = "INDIA_VIX"


def fetch_dates(connection: sqlite3.Connection, instrument_code: str) -> set[date]:
    rows = connection.execute(
        """SELECT candle_date
           FROM daily_close_series
           WHERE instrument_code = ?
             AND candle_date >= '2015-01-01'
             AND candle_date <= '2016-12-31'""",
        (instrument_code,),
    ).fetchall()
    return {date.fromisoformat(str(row[0])[:10]) for row in rows}


def load_calendar(connection: sqlite3.Connection):
    years = {
        int(row[0]): {
            "source_title": row[1],
            "source_reference": row[2] or "",
            "source_url": row[3] or "",
            "verification_level": row[4],
            "coverage_status": row[5],
        }
        for row in connection.execute(
            """SELECT calendar_year, source_title, source_reference, source_url,
                      verification_level, coverage_status
               FROM exchange_calendar_years
               WHERE exchange='NSE' AND market_segment='EQUITY'
                 AND calendar_year IN (2015, 2016)"""
        )
    }

    events = {}
    for row in connection.execute(
        """SELECT session_date, event_type, event_name, verification_level,
                  source_title, source_reference, source_url
           FROM exchange_calendar_events
           WHERE exchange='NSE' AND market_segment='EQUITY'
             AND calendar_year IN (2015, 2016)"""
    ):
        events[date.fromisoformat(str(row[0])[:10])] = {
            "event_type": row[1],
            "event_name": row[2],
            "verification_level": row[3],
            "source_title": row[4],
            "source_reference": row[5] or "",
            "source_url": row[6] or "",
        }

    missing = sorted(set(YEARS) - set(years))
    if missing:
        raise RuntimeError(f"Missing NSE calendar metadata for years: {missing}")

    # Avoid silently treating an incomplete annual calendar as authoritative.
    for year in YEARS:
        status = years[year]["coverage_status"]
        if status != "annual_list_loaded":
            raise RuntimeError(
                f"Unexpected calendar coverage_status for {year}: {status!r}"
            )
    return years, events


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def make_row(
    current: date,
    classification: str,
    context: str,
    bank_present: bool,
    calendar_meta: dict,
    event: dict | None,
    peer_dates: dict[str, set[date]],
    vix_dates: set[date],
) -> dict:
    peers_present = [code for code in EQUITY_PEERS if current in peer_dates[code]]
    peer_count = len(peers_present)
    vix_present = current in vix_dates

    if classification == "exchange_holiday_excluded":
        evidence = "regular_holiday_in_loaded_exchange_calendar"
        action = "Exclude from normal missing-session counts; retain as holiday audit evidence."
    elif classification.startswith("special_session"):
        evidence = "special_session_listed_in_loaded_exchange_calendar"
        action = (
            "Check whether BANKNIFTY was eligible and published for this special session. "
            "Do not infer or fabricate a BANKNIFTY value from other instruments."
        )
    elif peer_count == 2:
        evidence = "both_equity_peer_series_present"
        action = (
            "Prioritise independent verification of BANKNIFTY session publication and "
            "source coverage; peer data does not prove a BANKNIFTY value."
        )
    elif peer_count == 1:
        evidence = "one_equity_peer_series_present"
        action = "Check official session and BANKNIFTY publication/source coverage."
    else:
        evidence = "no_equity_peer_series_present"
        action = "Verify exchange session and source coverage before treating as a gap."

    if event:
        calendar_source = event["source_title"]
        calendar_reference = event["source_reference"]
        calendar_url = event["source_url"]
        event_name = event["event_name"]
        event_verification = event["verification_level"]
    else:
        calendar_source = calendar_meta["source_title"]
        calendar_reference = calendar_meta["source_reference"]
        calendar_url = calendar_meta["source_url"]
        event_name = ""
        event_verification = calendar_meta["verification_level"]

    return {
        "date": current.isoformat(),
        "weekday": current.strftime("%A"),
        "calendar_year": current.year,
        "classification": classification,
        "exchange_session_context": context,
        "banknifty_record_present": "yes" if bank_present else "no",
        "calendar_event": event_name,
        "calendar_verification_level": event_verification,
        "calendar_source_title": calendar_source,
        "calendar_source_reference": calendar_reference,
        "calendar_source_url": calendar_url,
        "equity_peer_count": peer_count,
        "equity_peer_indices": ";".join(peers_present),
        "india_vix_record_present": "yes" if vix_present else "no",
        "evidence_level": evidence,
        "recommended_follow_up": action,
    }


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    con = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        bank_dates = fetch_dates(con, TARGET)
        peer_dates = {code: fetch_dates(con, code) for code in EQUITY_PEERS}
        vix_dates = fetch_dates(con, VOLATILITY_REFERENCE)
        calendar_years, calendar_events = load_calendar(con)

        rows: list[dict] = []
        candidate_counts: dict[int, Counter] = {year: Counter() for year in YEARS}
        holiday_rows = 0
        special_rows = 0

        for year in YEARS:
            for current in date_range(date(year, 1, 1), date(year, 12, 31)):
                event = calendar_events.get(current)
                event_type = event["event_type"] if event else None
                bank_present = current in bank_dates
                calendar_meta = calendar_years[year]

                # Keep all loaded regular holidays as audit rows, not as gaps.
                if event_type == "holiday_closed":
                    rows.append(make_row(
                        current,
                        "exchange_holiday_excluded",
                        "regular_exchange_holiday",
                        bank_present,
                        calendar_meta,
                        event,
                        peer_dates,
                        vix_dates,
                    ))
                    holiday_rows += 1
                    continue

                # Special sessions are included whether or not BANKNIFTY has a row.
                if event_type == "special_session_open":
                    classification = (
                        "special_session_record_present"
                        if bank_present
                        else "special_session_requires_review"
                    )
                    rows.append(make_row(
                        current,
                        classification,
                        "calendar_listed_special_session",
                        bank_present,
                        calendar_meta,
                        event,
                        peer_dates,
                        vix_dates,
                    ))
                    special_rows += 1
                    if not bank_present:
                        candidate_counts[year]["special_session_requires_review"] += 1
                    continue

                # Ordinary Saturday/Sunday dates are not candidate sessions.
                if current.weekday() >= 5:
                    continue

                # Only absent BANKNIFTY weekday records become gap candidates.
                if bank_present:
                    continue

                peers_present = [code for code in EQUITY_PEERS if current in peer_dates[code]]
                peer_count = len(peers_present)
                if peer_count == 2:
                    classification = "peer_confirmed_candidate"
                elif peer_count == 1:
                    classification = "partial_peer_evidence"
                else:
                    classification = "unconfirmed_candidate"

                rows.append(make_row(
                    current,
                    classification,
                    "weekday_not_listed_as_regular_holiday",
                    bank_present,
                    calendar_meta,
                    event,
                    peer_dates,
                    vix_dates,
                ))
                candidate_counts[year][classification] += 1

        fields = [
            "date", "weekday", "calendar_year", "classification",
            "exchange_session_context", "banknifty_record_present", "calendar_event",
            "calendar_verification_level", "calendar_source_title",
            "calendar_source_reference", "calendar_source_url", "equity_peer_count",
            "equity_peer_indices", "india_vix_record_present", "evidence_level",
            "recommended_follow_up",
        ]
        rows.sort(key=lambda row: row["date"])
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        total_candidates = sum(sum(counts.values()) for counts in candidate_counts.values())
        print("\nBANKNIFTY HISTORICAL DATA GAP REGISTER")
        print("=" * 72)
        print("Period: 2015-01-01 to 2016-12-31")
        print("Equity comparison series: NIFTY50 + FINNIFTY")
        print("INDIA VIX: separate volatility reference only")

        for year in YEARS:
            counts = candidate_counts[year]
            total = sum(counts.values())
            bank_count = sum(d.year == year for d in bank_dates)
            print(f"\n{year} | BANKNIFTY close records={bank_count}")
            print(f"  Peer-confirmed candidates: {counts['peer_confirmed_candidate']}")
            print(f"  Partial peer evidence: {counts['partial_peer_evidence']}")
            print(f"  Unconfirmed candidates: {counts['unconfirmed_candidate']}")
            print(f"  Special sessions requiring review: {counts['special_session_requires_review']}")
            print(f"  Total candidate dates: {total}")
            print(f"  Calendar verification: {calendar_years[year]['verification_level']}")

        print("\nREGISTER SUMMARY")
        print(f"  Candidate dates (excluding regular holidays): {total_candidates}")
        print(f"  Regular holiday audit rows: {holiday_rows}")
        print(f"  Special-session audit rows: {special_rows}")
        print(f"  Total CSV rows: {len(rows)}")
        print(f"\nCSV register: {OUTPUT}")
        print("Database mode: read-only; no database changes made.")
        print("Important: peer data corroborates session dates, not BANKNIFTY values or recoverability.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
