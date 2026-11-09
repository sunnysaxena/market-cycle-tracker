from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"


@dataclass(frozen=True)
class SessionEvent:
    session_date: str
    event_name: str
    source_title: str
    source_reference: str
    source_url: str
    verification_level: str
    notes: str


# These are selected, corroborated weekend trading dates found in the
# historical source audit. This list is an exception register, NOT a complete
# annual trading calendar. Event records are added for both NSE and BSE where
# the sources confirm both exchanges were open.
EVENTS = [
    SessionEvent(
        "2005-06-04",
        "Special live trading session - backup-site test",
        "BSE and NSE special trading on Saturday - PTI report",
        "PTI report dated 03-Jun-2005",
        "https://www.rediff.com/business/report/bse/20050603.htm",
        "secondary_reference",
        "Both exchanges announced a Saturday live session to test NSE backup facilities at Chennai. Event-level historical evidence; annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2005-11-26",
        "Special live trading session - backup-site readiness test",
        "BSE and NSE open on November 26 - PTI report",
        "PTI report dated 25-Nov-2005",
        "https://www.rediff.com/business/report/bse/20051125.htm",
        "secondary_reference",
        "Both exchanges announced live Saturday trading to test/upgrade the Chennai backup site. Event-level historical evidence; annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2006-04-29",
        "Special live trading session - disaster-recovery and backup-site test",
        "NSE/BSE special trading circular references listed by ISE Securities",
        "BSE 06-07/SPL-Trdg/34502/GC; NSE 06-07/SPL-Trdg/34503/GC; 26-Apr-2006",
        "https://www.isesec.com/Content/InternalCirculars",
        "secondary_reference",
        "Circular index records a BSE Disaster Recovery Site session and an NSE Chennai backup-site session on this Saturday. A contemporaneous report records the special live market session. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2006-06-25",
        "Special Sunday live trading session",
        "NSE/BSE special live trading circular references listed by ISE Securities",
        "NSE 06-07/SPL-Trdg/36306/GC; BSE 06-07/SPL-Trdg/36307/GC; Jun-2006",
        "https://www.isesec.com/Content/InternalCirculars",
        "secondary_reference",
        "Separate NSE and BSE circular references announce a Sunday live session; contemporaneous reporting confirms Sensex and Nifty trading. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2006-10-21",
        "Diwali Muhurat trading",
        "BSE and NSE Muhurat trading on October 21 - PTI report",
        "PTI report dated 10-Oct-2006",
        "https://www.rediff.com/money/report/bse/20061010.htm",
        "secondary_reference",
        "Both exchanges announced a Saturday Muhurat session. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2009-10-17",
        "Diwali Muhurat trading",
        "BSE and NSE Muhurat trading session report",
        "NSE/CMO/048/2009; NSE/CMTR/13174; BSE Notice 20091001-22",
        "https://www.business-standard.com/article/markets/muhurat-trading-from-1815-hrs-on-bse-nse-109101700101_1.html",
        "secondary_reference",
        "NSE circular confirms the Saturday Muhurat session; BSE event is corroborated by BSE-specific Muhurat reporting. Session was 18:15-19:15 IST. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2010-02-06",
        "Special 90-minute live trading session - trading-system upgrade test",
        "NSE and BSE special trading session on Saturday - PTI report",
        "PTI report dated 04-Feb-2010; separate exchange circulars referenced",
        "https://www.rediff.com/business/report/nse-bse-special-trading-session-on-saturday/20100204.htm",
        "secondary_reference",
        "Both exchanges announced a 90-minute Saturday session for testing/upgrading NSE trading-system facilities. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2012-01-07",
        "Special live trading session - trading-system upgrade",
        "NSE/BSE special-session circular copies",
        "NSE/CMTR/19734; BSE Notice 20120104-1 (Cash Market)",
        "https://www.isesec.com/Admin/Circular/20121170.pdf",
        "official_primary_copy",
        "Circular copies identify NSE live trading and a corresponding BSE cash-market session. Session timing reported as 11:15-12:45 IST. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2012-03-03",
        "Special live trading session - disaster-recovery test",
        "BSE/NSE special live trading session - exchange circular references and PTI report",
        "ISE Securities circular index: 11-12/ISS/1326/KS and 11-12/ISS/1315/KS; PTI report dated 03-Mar-2012",
        "https://www.isesec.com/Content/InternalCirculars",
        "secondary_reference",
        "BSE and NSE held a Saturday special session; BSE tested its Disaster Recovery Site. Reported trading window 11:15-12:45 IST. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2012-04-28",
        "Special live trading session - disaster-recovery test",
        "BSE notice and exchange-referenced CSE notice for NSE/BSE session",
        "BSE Notice 20120418-18; CSE notice dated 26-Apr-2012",
        "https://www.cse-india.com/upload/CSE%20Notices%20%26%20Circulars/2012/Notice260412.htm",
        "secondary_reference",
        "Notice confirms the Saturday special session for both BSE and NSE. Reported continuous trading window 11:15-12:45 IST. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2012-09-08",
        "Special live trading session - disaster-recovery test",
        "NSE and BSE special trading session - PTI report",
        "Separate exchange announcements reported 27-Aug-2012",
        "https://economictimes.indiatimes.com/nse-bse-to-hold-special-trading-session-on-september-8/articleshow/15837680.cms",
        "secondary_reference",
        "Both exchanges held Saturday sessions; BSE tested disaster-recovery software and NSE opened the capital-market and derivatives segments. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2013-05-11",
        "Special live trading session - disaster-recovery and software test",
        "NSE/BSE special-session reporting",
        "Special trading session reported 11-May-2013; NSE Annual Report FY2013-14 also lists the date",
        "https://indianexpress.com/article/news-archive/web/special-trading-nse-nifty-hits-28-months-high/",
        "secondary_reference",
        "NSE annual report identifies the special trading date; BSE cash/derivatives session is corroborated by contemporaneous reporting. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2013-11-03",
        "Diwali Muhurat trading",
        "NSE/BSE Muhurat trading session circular copy",
        "ISE Securities circular dated 21-Oct-2013; NSE and BSE circulars attached",
        "https://www.isesec.com/Admin/Circular/2013CIR0142913.pdf",
        "official_primary_copy",
        "Circular copy confirms the Sunday Muhurat session for NSE and BSE. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2014-03-22",
        "Special live trading session - business-continuity/disaster-recovery test",
        "NSE/BSE special live trading session notice",
        "CSE notice dated 20-Mar-2014 referencing NSE BCP and BSE DR sessions",
        "https://www.cse-india.com/upload/CSE%20Notices%20%26%20Circulars/2014/Notice200314_4.htm",
        "secondary_reference",
        "Notice confirms Saturday special sessions for both NSE and BSE. Reported trading window 11:15-12:45 IST. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2015-02-28",
        "Union Budget trading session - regular market hours",
        "Stock exchanges open on Union Budget day - SEBI/exchange reporting",
        "SEBI communication to BSE and NSE; BSE notice reference 20150220-23",
        "https://www.business-standard.com/article/markets/markets-will-stay-open-on-budget-day-hints-sebi-115022001010_1.html",
        "secondary_reference",
        "Both BSE and NSE operated on Saturday for the Union Budget presentation. Regular equity market hours; an NSE event already exists in the calendar. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2016-10-30",
        "Diwali Laxmi Pujan Muhurat trading",
        "NSE/BSE Muhurat trading notice",
        "CSE notice dated 26-Oct-2016; NSE and BSE cash settlement numbers listed",
        "https://www.cse-india.com/upload/CSE%20Notices%20%26%20Circulars/2016/Notice261016_2.htm",
        "secondary_reference",
        "Notice confirms the Sunday Muhurat session for both NSE and BSE. An NSE event already exists in the calendar. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2019-10-27",
        "Diwali Muhurat trading",
        "NSE/BSE Muhurat trading notice",
        "CSE notice dated 22-Oct-2019 referencing both exchanges",
        "https://www.cse-india.com/upload/cse_notice/Muhurat_Trading.pdf",
        "secondary_reference",
        "Sunday Muhurat session for both NSE and BSE. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2020-02-01",
        "Union Budget trading session - regular market hours",
        "Markets open on Saturday for Union Budget 2020",
        "BSE and NSE separate circulars; reported 22-Jan-2020",
        "https://indianexpress.com/article/business/markets/domestic-stock-markets-to-be-open-on-budget-day-6230684/lite/",
        "secondary_reference",
        "Both exchanges operated regular equity and derivatives trading on Saturday for the Union Budget. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2020-11-14",
        "Diwali Muhurat trading",
        "BSE/NSE Muhurat trading session - PTI report",
        "Separate exchange circulars reported 04-Nov-2020",
        "https://indianexpress.com/article/business/market/bse-nse-to-hold-1-hour-special-diwali-muhurat-trading-session-on-nov-14-6943756/",
        "secondary_reference",
        "Saturday Muhurat session for BSE and NSE. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2023-11-12",
        "Diwali Muhurat trading",
        "NSE/BSE Muhurat trading schedule",
        "Muhurat session notice dated 06-Nov-2023",
        "https://zerodha.com/marketintel/bulletin/363312/muhurat-trading-session-on-account-of-diwali-7",
        "secondary_reference",
        "Sunday Muhurat trading session. All six instrument datasets contain a date-level observation. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2024-01-20",
        "Saturday equity trading session - regular full-day schedule",
        "NSE/BSE final revised Saturday trading schedule - PTI report",
        "Final exchange update dated 19-Jan-2024; previously planned DR switchover was withdrawn",
        "https://economictimes.indiatimes.com/markets/stocks/news/nse-bse-to-have-normal-trading-today-but-monday-to-be-a-holiday/articleshow/107001174.cms",
        "secondary_reference",
        "Important correction: the originally planned short DR-switched special session was revised/withdrawn. NSE and BSE conducted regular full-day equity/equity-derivatives trading on 20-Jan-2024, with 22-Jan a holiday. Treat this as an exceptional Saturday trading date, not as a DR test.",
    ),
    SessionEvent(
        "2024-03-02",
        "Special live trading session - primary to disaster-recovery switchover",
        "NSE/BSE special live trading session notices",
        "Exchange notices for 02-Mar-2024; DR switchover sessions",
        "https://notifications.geojit.com/geojit-circulars/general-information",
        "secondary_reference",
        "Both exchanges held two live trading windows with an intraday switch from the primary site to the DR site. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2024-05-18",
        "Special live trading session - primary to disaster-recovery switchover",
        "NSE/BSE special live trading session reporting",
        "NSE/BSE circulars for 18-May-2024",
        "https://indianexpress.com/article/business/market/national-stock-exchange-nse-special-trading-session-derivatives-sebi-9314078/",
        "secondary_reference",
        "Both exchanges held a Saturday special session with two trading windows and an intraday DR-site switchover. Annual calendar coverage is not implied.",
    ),
    SessionEvent(
        "2025-02-01",
        "Union Budget trading session - regular market hours",
        "BSE/NSE live trading for Union Budget presentation",
        "NSE/FAOP/65730 and NSE/CMTR/65729 dated 23-Dec-2024; BSE/ICCL notices also issued",
        "https://newsonair.gov.in/indian-stock-markets-open-today-for-union-budget-presentation/",
        "secondary_reference",
        "NSE official circular confirms live trading for the Union Budget on Saturday, 01-Feb-2025, at regular market timings; BSE session also confirmed in exchange/settlement notices. Annual calendar coverage is not implied.",
    ),
]

EXCHANGES = ("NSE", "BSE")
MARKET_SEGMENT = "EQUITY"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_read_only() -> sqlite3.Connection:
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)
    return sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)


def inspect_plan() -> dict:
    con = connect_read_only()
    try:
        existing_years = {
            (row[0], row[1], row[2])
            for row in con.execute(
                "SELECT exchange, market_segment, calendar_year "
                "FROM exchange_calendar_years"
            )
        }
        existing_events = {
            (row[0], row[1], row[2]): row[3]
            for row in con.execute(
                "SELECT exchange, market_segment, session_date, event_type "
                "FROM exchange_calendar_events"
            )
        }
        target_years = {
            (exchange, MARKET_SEGMENT, int(event.session_date[:4]))
            for event in EVENTS
            for exchange in EXCHANGES
        }
        target_events = {
            (exchange, MARKET_SEGMENT, event.session_date)
            for event in EVENTS
            for exchange in EXCHANGES
        }
        years_to_add = sorted(target_years - existing_years)
        events_to_add = sorted(target_events - set(existing_events))
        conflicts = [
            (key, event_type)
            for key, event_type in existing_events.items()
            if key in target_events and event_type != "special_session_open"
        ]
        already_present = sorted(target_events & set(existing_events))
        return {
            "years_to_add": years_to_add,
            "events_to_add": events_to_add,
            "already_present": already_present,
            "conflicts": conflicts,
            "existing_years": existing_years,
            "existing_events": existing_events,
        }
    finally:
        con.close()


def print_plan(plan: dict, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN (read-only)"
    print("\nHISTORICAL WEEKEND SESSION CALENDAR REGISTRATION")
    print("=" * 82)
    print(f"Database: {DATABASE}")
    print(f"Mode: {mode}")
    print(f"Unique corroborated weekend dates: {len(EVENTS)}")
    print(f"Exchanges: {', '.join(EXCHANGES)}")
    print("\nPROPOSED CHANGES")
    print("-" * 82)
    print(f"Event records already present and preserved: {len(plan['already_present'])}")
    print(f"New exchange event records: {len(plan['events_to_add'])}")
    print(f"New exchange_calendar_years rows: {len(plan['years_to_add'])}")
    print("Year-row coverage_status: event_exceptions_only")
    print("Existing exchange-year rows: unchanged")
    print("Historical price/quality/aggregate tables: unchanged")
    print("\nDATES TO REGISTER")
    for event in EVENTS:
        print(f"  {event.session_date} | {event.event_name}")
    print("\nIMPORTANT CLASSIFICATION")
    print("  2024-01-20: regular full-day Saturday session; planned DR switchover withdrawn.")
    print("  All inserted event rows use special_session_open to represent an exceptional")
    print("  weekend market opening; notes retain the actual session type and evidence.")
    print("  Calendar-year parent rows represent selected exceptions only, not complete")
    print("  annual holiday calendars.")
    if plan["conflicts"]:
        print("\nEVENT TYPE CONFLICTS (apply will stop):")
        for item in plan["conflicts"]:
            print(" ", item)


def verify_backup(path: Path) -> None:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"Backup verification failed: integrity={integrity}, fk_errors={len(fk_errors)}"
            )
    finally:
        con.close()


def create_verified_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"historical_staging_before_weekend_calendar_{stamp}.db"

    source = sqlite3.connect(DATABASE, timeout=60)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    verify_backup(backup_path)
    return backup_path


def apply_plan(plan: dict) -> None:
    if plan["conflicts"]:
        raise RuntimeError("Calendar conflicts found. No changes applied.")

    backup_path = create_verified_backup()
    print(f"\nVerified database backup: {backup_path}")

    con = sqlite3.connect(DATABASE, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")
        now = utc_now()

        years_added = 0
        for exchange, segment, year in plan["years_to_add"]:
            con.execute(
                """
                INSERT INTO exchange_calendar_years (
                    exchange, market_segment, calendar_year,
                    source_title, source_reference, source_url,
                    verification_level, coverage_status,
                    notes, loaded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exchange,
                    segment,
                    year,
                    f"Selected weekend-session exceptions - {exchange} {year}",
                    "See event-level source references in exchange_calendar_events",
                    None,
                    "mixed_event_level_sources",
                    "event_exceptions_only",
                    (
                        "Partial exception register only. This row does not represent a complete "
                        "annual trading-holiday calendar. Individual event evidence and its "
                        "verification level are stored on exchange_calendar_events."
                    ),
                    now,
                ),
            )
            years_added += 1

        events_added = 0
        events_preserved = 0
        for event in EVENTS:
            for exchange in EXCHANGES:
                existing = con.execute(
                    """
                    SELECT event_type
                    FROM exchange_calendar_events
                    WHERE exchange = ? AND market_segment = ? AND session_date = ?
                    """,
                    (exchange, MARKET_SEGMENT, event.session_date),
                ).fetchone()

                if existing:
                    if existing["event_type"] != "special_session_open":
                        raise RuntimeError(
                            f"Conflicting event type for {exchange} {event.session_date}: "
                            f"{existing['event_type']}"
                        )
                    events_preserved += 1
                    continue

                con.execute(
                    """
                    INSERT INTO exchange_calendar_events (
                        exchange, market_segment, session_date, calendar_year,
                        event_type, event_name,
                        market_open_time, market_close_time,
                        source_title, source_reference, source_url,
                        verification_level, notes, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exchange,
                        MARKET_SEGMENT,
                        event.session_date,
                        int(event.session_date[:4]),
                        "special_session_open",
                        event.event_name,
                        None,
                        None,
                        event.source_title,
                        event.source_reference,
                        event.source_url,
                        event.verification_level,
                        event.notes,
                        now,
                    ),
                )
                events_added += 1

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"Pre-commit validation failed: integrity={integrity}, "
                f"foreign_key_errors={len(fk_errors)}"
            )

        con.commit()

        print("\nCALENDAR REGISTRATION COMMITTED")
        print("=" * 82)
        print("Exchange-year exception rows added:", years_added)
        print("Weekend event rows added:", events_added)
        print("Existing session events preserved:", events_preserved)
        print("Unique event dates registered:", len(EVENTS))
        print("SQLite integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
        print("Foreign-key errors:", len(con.execute("PRAGMA foreign_key_check").fetchall()))
        print("Backup:", backup_path)
        print("Historical price, quality and aggregate tables: not modified")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register corroborated historical weekend trading sessions for NSE and BSE."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a verified backup and insert calendar exception records.",
    )
    args = parser.parse_args()

    plan = inspect_plan()
    print_plan(plan, args.apply)

    if plan["conflicts"]:
        print("\nERROR: Conflicting calendar event types found. No changes made.")
        return 2

    if not args.apply:
        print("\nDry run completed. No database changes were made.")
        print("Review the plan, then rerun with --apply to register the events.")
        return 0

    apply_plan(plan)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
