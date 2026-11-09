"""Revised BANKNIFTY 2015-2016 gap analysis.

Uses NIFTY50 and FINNIFTY as equity-index comparison series. INDIA VIX is
reported separately as a volatility-data corroboration field, not as a peer
index. Read-only with respect to the staging database.
"""
from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
OUTPUT = ROOT / "backend" / "data" / "banknifty_calendar_gap_verification_v2_2015_2016.csv"
YEARS = (2015, 2016)
TARGET = "BANKNIFTY"
EQUITY_PEERS = ("NIFTY50", "FINNIFTY")
VOLATILITY_REFERENCE = "INDIA_VIX"


def fetch_dates(connection: sqlite3.Connection, instrument_code: str) -> set[date]:
    rows = connection.execute(
        """SELECT candle_date FROM daily_close_series
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
            "verification_level": row[2],
            "coverage_status": row[3],
        }
        for row in connection.execute(
            """SELECT calendar_year, source_title, verification_level, coverage_status
               FROM exchange_calendar_years
               WHERE exchange='NSE' AND market_segment='EQUITY'
                 AND calendar_year IN (2015, 2016)"""
        )
    }
    events = {}
    for row in connection.execute(
        """SELECT session_date, event_type, event_name, verification_level,
                  source_title, source_reference
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
        }
    missing = sorted(set(YEARS) - set(years))
    if missing:
        raise RuntimeError(f"Missing NSE calendar metadata for: {missing}")
    return years, events


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_clusters(rows: list[dict]) -> list[dict]:
    """Group missing candidate sessions; allow weekends/short holidays between."""
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: row["date"])
    groups: list[list[dict]] = [[ordered[0]]]
    for row in ordered[1:]:
        previous = date.fromisoformat(groups[-1][-1]["date"])
        current = date.fromisoformat(row["date"])
        if (current - previous).days <= 4:
            groups[-1].append(row)
        else:
            groups.append([row])

    result = []
    for group in groups:
        counts = Counter(row["equity_peer_count"] for row in group)
        result.append({
            "start_date": group[0]["date"],
            "end_date": group[-1]["date"],
            "candidate_sessions": len(group),
            "two_of_two_equity_peers": counts[2],
            "one_of_two_equity_peers": counts[1],
            "zero_of_two_equity_peers": counts[0],
            "india_vix_present": sum(row["india_vix_record"] == "yes" for row in group),
        })
    return result


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    con = sqlite3.connect(DATABASE)
    try:
        bank_dates = fetch_dates(con, TARGET)
        peer_dates = {code: fetch_dates(con, code) for code in EQUITY_PEERS}
        vix_dates = fetch_dates(con, VOLATILITY_REFERENCE)
        calendar_years, calendar_events = load_calendar(con)

        rows: list[dict] = []
        year_counts: dict[int, Counter] = {year: Counter() for year in YEARS}
        month_counts: Counter = Counter()

        for year in YEARS:
            year_counts[year]["banknifty_records"] = sum(d.year == year for d in bank_dates)
            year_counts[year]["holiday_dates_excluded"] = 0
            for current in date_range(date(year, 1, 1), date(year, 12, 31)):
                event = calendar_events.get(current)
                is_weekend = current.weekday() >= 5
                special_open = bool(event and event["event_type"] == "special_session_open")
                if is_weekend and not special_open:
                    continue
                if event and event["event_type"] == "holiday_closed":
                    year_counts[year]["holiday_dates_excluded"] += 1
                    continue
                if current in bank_dates:
                    continue

                present_equity_peers = [code for code in EQUITY_PEERS if current in peer_dates[code]]
                vix_present = current in vix_dates
                peer_count = len(present_equity_peers)
                if special_open:
                    classification = "special_session_without_BANKNIFTY_record"
                    evidence = "special_session_confirmed_by_calendar"
                    follow_up = (
                        "The calendar identifies an open special session. Check whether BANKNIFTY "
                        "was published for that session; do not infer a missing value from peer data."
                    )
                else:
                    classification = "weekday_without_BANKNIFTY_record"
                    if peer_count == 2:
                        evidence = "both_equity_peer_series_present"
                        follow_up = "Strong session-day corroboration; independently verify BANKNIFTY publication/source coverage."
                    elif peer_count == 1:
                        evidence = "one_equity_peer_series_present"
                        follow_up = "Partial session-day corroboration; check official session and index publication records."
                    else:
                        evidence = "no_equity_peer_series_present"
                        follow_up = "Uncorroborated candidate; verify exchange session and source coverage."

                row = {
                    "date": current.isoformat(),
                    "weekday": current.strftime("%A"),
                    "year": year,
                    "classification": classification,
                    "calendar_verification": calendar_years[year]["verification_level"],
                    "calendar_source": calendar_years[year]["source_title"],
                    "calendar_event": event["event_name"] if event else "",
                    "equity_peer_count": peer_count,
                    "equity_peer_indices": ";".join(present_equity_peers),
                    "india_vix_record": "yes" if vix_present else "no",
                    "evidence_level": evidence,
                    "recommended_follow_up": follow_up,
                }
                rows.append(row)
                year_counts[year]["candidate_dates"] += 1
                year_counts[year][f"equity_peer_support_{peer_count}"] += 1
                year_counts[year]["india_vix_present"] += int(vix_present)
                month_counts[current.strftime("%Y-%m") ] += 1

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "date", "weekday", "year", "classification", "calendar_verification",
            "calendar_source", "calendar_event", "equity_peer_count",
            "equity_peer_indices", "india_vix_record", "evidence_level",
            "recommended_follow_up",
        ]
        with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        print("\nBANKNIFTY CALENDAR-AWARE GAP VERIFICATION V2")
        print("=" * 72)
        print("Equity comparisons: NIFTY50 + FINNIFTY | INDIA VIX reported separately")
        for year in YEARS:
            c = year_counts[year]
            print(f"\n{year} | BANKNIFTY close records={c['banknifty_records']} | calendar={calendar_years[year]['verification_level']}")
            print(f"  Regular holidays excluded: {c['holiday_dates_excluded']}")
            print(f"  Missing weekday/special-session candidates: {c['candidate_dates']}")
            print(f"  Both equity peers present (2/2): {c[ 'equity_peer_support_2']}")
            print(f"  One equity peer present (1/2): {c['equity_peer_support_1']}")
            print(f"  No equity peer present (0/2): {c['equity_peer_support_0']}")
            print(f"  INDIA VIX present (separate reference): {c['india_vix_present']}")

        print("\nMONTHLY CANDIDATE COUNTS")
        for month, count in sorted(month_counts.items()):
            print(f"  {month}: {count}")

        print("\nCONTIGUOUS CANDIDATE CLUSTERS (candidate dates within 4 calendar days)")
        clusters = build_clusters(rows)
        for item in clusters:
            print(
                f"  {item['start_date']} to {item['end_date']} | "
                f"dates={item['candidate_sessions']} | both peers={item['two_of_two_equity_peers']} | "
                f"one peer={item['one_of_two_equity_peers']} | no peers={item['zero_of_two_equity_peers']} | "
                f"VIX={item['india_vix_present']}"
            )

        print(f"\nTOTAL CANDIDATES: {len(rows)}")
        print(f"CSV report: {OUTPUT}")
        print("Database changes: none (read-only analysis).")
        print("Interpretation: peer records corroborate session dates; they do not prove a BANKNIFTY value or its recoverability.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
