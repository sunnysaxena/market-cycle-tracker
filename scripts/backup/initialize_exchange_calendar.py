import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"

NSE_2015_HOLIDAYS = [
    ("2015-01-26", "Republic Day"),
    ("2015-02-17", "Mahashivratri"),
    ("2015-03-06", "Holi"),
    ("2015-04-02", "Mahavir Jayanti"),
    ("2015-04-03", "Good Friday"),
    ("2015-04-14", "Dr. Babasaheb Ambedkar Jayanti"),
    ("2015-05-01", "Maharashtra Day"),
    ("2015-09-17", "Ganesh Chaturthi"),
    ("2015-09-25", "Bakri ID"),
    ("2015-10-02", "Mahatma Gandhi Jayanti"),
    ("2015-10-22", "Dussehra"),
    ("2015-11-12", "Diwali Balipratipada"),
    ("2015-11-25", "Guru Nanak Jayanti"),
    ("2015-12-25", "Christmas"),
]

NSE_2016_HOLIDAYS = [
    ("2016-01-26", "Republic Day"),
    ("2016-03-07", "Mahashivratri"),
    ("2016-03-24", "Holi"),
    ("2016-03-25", "Good Friday"),
    ("2016-04-14", "Dr. Babasaheb Ambedkar Jayanti"),
    ("2016-04-15", "Ram Navami"),
    ("2016-04-19", "Mahavir Jayanti"),
    ("2016-07-06", "Id-Ul-Fitr"),
    ("2016-08-15", "Independence Day"),
    ("2016-09-05", "Ganesh Chaturthi"),
    ("2016-09-13", "Bakri ID"),
    ("2016-10-11", "Dussehra"),
    ("2016-10-12", "Muharram"),
    ("2016-10-31", "Diwali Balipratipada"),
    ("2016-11-14", "Guru Nanak Jayanti"),
]

# Special sessions are OPEN sessions, not regular holidays.
NSE_SPECIAL_SESSIONS = [
    ("2015-11-11", "Diwali Laxmi Pujan - Muhurat Trading", 2015),
    ("2016-10-30", "Diwali Laxmi Pujan - Muhurat Trading", 2016),
]

SOURCE_2015 = {
    "title": "NSE Trading Holidays 2015",
    "reference": "NSE/CMTR/28337 dated 12-Dec-2014",
    "url": "https://nsearchives.nseindia.com/content/circulars/CMTR28337.pdf",
    "verification": "official_primary",
}

SOURCE_2016 = {
    "title": "Historical NSE Holiday Table 2016",
    "reference": "Historical NSE holiday table, Table A2",
    "url": (
        "https://www.cafral.org.in/sfControl/content/Speech/"
        "819202521457PMUPI_and_Stock_Market_Trading%20%2826%29.pdf"
    ),
    "verification": "secondary_reference",
}


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS exchange_calendar_years (
            exchange TEXT NOT NULL,
            market_segment TEXT NOT NULL,
            calendar_year INTEGER NOT NULL,
            source_title TEXT NOT NULL,
            source_reference TEXT,
            source_url TEXT,
            verification_level TEXT NOT NULL,
            coverage_status TEXT NOT NULL,
            notes TEXT,
            loaded_at_utc TEXT NOT NULL,
            PRIMARY KEY (exchange, market_segment, calendar_year)
        );

        CREATE TABLE IF NOT EXISTS exchange_calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            market_segment TEXT NOT NULL,
            session_date TEXT NOT NULL,
            calendar_year INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'holiday_closed',
                    'special_session_open',
                    'unscheduled_closure',
                    'shortened_session'
                )
            ),
            event_name TEXT NOT NULL,
            market_open_time TEXT,
            market_close_time TEXT,
            source_title TEXT NOT NULL,
            source_reference TEXT,
            source_url TEXT,
            verification_level TEXT NOT NULL,
            notes TEXT,
            created_at_utc TEXT NOT NULL,
            UNIQUE (exchange, market_segment, session_date),
            FOREIGN KEY (exchange, market_segment, calendar_year)
                REFERENCES exchange_calendar_years (
                    exchange,
                    market_segment,
                    calendar_year
                )
        );
        """
    )


def load_year(
    connection: sqlite3.Connection,
    year: int,
    holidays: list[tuple[str, str]],
    source: dict[str, str],
    notes: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()

    connection.execute(
        """
        INSERT INTO exchange_calendar_years (
            exchange, market_segment, calendar_year,
            source_title, source_reference, source_url,
            verification_level, coverage_status, notes, loaded_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (exchange, market_segment, calendar_year)
        DO UPDATE SET
            source_title = excluded.source_title,
            source_reference = excluded.source_reference,
            source_url = excluded.source_url,
            verification_level = excluded.verification_level,
            coverage_status = excluded.coverage_status,
            notes = excluded.notes,
            loaded_at_utc = excluded.loaded_at_utc
        """,
        (
            "NSE",
            "EQUITY",
            year,
            source["title"],
            source["reference"],
            source["url"],
            source["verification"],
            "annual_list_loaded",
            notes,
            now,
        ),
    )

    for session_date, event_name in holidays:
        connection.execute(
            """
            INSERT INTO exchange_calendar_events (
                exchange, market_segment, session_date, calendar_year,
                event_type, event_name, source_title, source_reference,
                source_url, verification_level, notes, created_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (exchange, market_segment, session_date)
            DO UPDATE SET
                calendar_year = excluded.calendar_year,
                event_type = excluded.event_type,
                event_name = excluded.event_name,
                source_title = excluded.source_title,
                source_reference = excluded.source_reference,
                source_url = excluded.source_url,
                verification_level = excluded.verification_level,
                notes = excluded.notes
            """,
            (
                "NSE",
                "EQUITY",
                session_date,
                int(session_date[:4]),
                "holiday_closed",
                event_name,
                source["title"],
                source["reference"],
                source["url"],
                source["verification"],
                "Regular equity trading holiday.",
                now,
            ),
        )


def load_special_sessions(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()

    for session_date, event_name, year in NSE_SPECIAL_SESSIONS:
        source = SOURCE_2015 if year == 2015 else SOURCE_2016

        connection.execute(
            """
            INSERT INTO exchange_calendar_events (
                exchange, market_segment, session_date, calendar_year,
                event_type, event_name, source_title, source_reference,
                source_url, verification_level, notes, created_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (exchange, market_segment, session_date)
            DO UPDATE SET
                calendar_year = excluded.calendar_year,
                event_type = excluded.event_type,
                event_name = excluded.event_name,
                source_title = excluded.source_title,
                source_reference = excluded.source_reference,
                source_url = excluded.source_url,
                verification_level = excluded.verification_level,
                notes = excluded.notes
            """,
            (
                "NSE",
                "EQUITY",
                session_date,
                year,
                "special_session_open",
                event_name,
                source["title"],
                source["reference"],
                source["url"],
                source["verification"],
                "Special session. Confirm actual instrument coverage.",
                now,
            ),
        )


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        create_schema(connection)
        connection.execute("BEGIN IMMEDIATE")

        load_year(
            connection,
            2015,
            NSE_2015_HOLIDAYS,
            SOURCE_2015,
            "Official NSE annual circular loaded. "
            "Supplemental circular review remains necessary.",
        )
        load_year(
            connection,
            2016,
            NSE_2016_HOLIDAYS,
            SOURCE_2016,
            "Historical holiday table loaded; secondary source. "
            "Cross-check against MSEI is not primary NSE verification; "
            "NSE primary circular verification remains pending.",
        )
        load_special_sessions(connection)
        connection.commit()

        print("\nEXCHANGE CALENDAR INITIALIZATION")
        print("=" * 60)

        years = connection.execute(
            """
            SELECT exchange, calendar_year, source_title,
                   verification_level, coverage_status
            FROM exchange_calendar_years
            ORDER BY calendar_year
            """
        ).fetchall()

        for row in years:
            print(
                f"{row[0]} {row[1]} | {row[2]} | "
                f"{row[3]} | {row[4]}"
            )

        events = connection.execute(
            """
            SELECT event_type, COUNT(*)
            FROM exchange_calendar_events
            WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
            GROUP BY event_type
            ORDER BY event_type
            """
        ).fetchall()

        print("\nEVENT COUNTS")
        for event_type, count in events:
            print(f"{event_type}: {count}")

        total_events = connection.execute(
            """
            SELECT COUNT(*)
            FROM exchange_calendar_events
            WHERE exchange = 'NSE' AND market_segment = 'EQUITY'
            """
        ).fetchone()[0]
        print(f"Total NSE equity calendar events: {total_events}")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        print(f"\nSQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        if fk_errors:
            for error in fk_errors:
                print(f"Foreign-key detail: {error}")

        print("\nBSE calendar: Not loaded yet.")
        print("Other years: Not loaded yet.")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
