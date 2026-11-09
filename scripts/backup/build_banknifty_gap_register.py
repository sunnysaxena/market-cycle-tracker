
import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE = ROOT / "docs" / "peer_supported_gaps.csv"
OUTPUT = ROOT / "docs" / "banknifty_gap_register.csv"

# NSE equity-market holidays from the published annual calendars.
NSE_HOLIDAYS = {
    2015: {
        "2015-01-26", "2015-02-17", "2015-03-06",
        "2015-04-02", "2015-04-03", "2015-04-14",
        "2015-05-01", "2015-09-17", "2015-09-25",
        "2015-10-02", "2015-10-22", "2015-11-12",
        "2015-11-25", "2015-12-25",
    },
    2016: {
        "2016-01-26", "2016-03-07", "2016-03-24",
        "2016-03-25", "2016-04-14", "2016-04-15",
        "2016-04-19", "2016-07-06", "2016-08-15",
        "2016-09-05", "2016-09-13", "2016-10-11",
        "2016-10-12", "2016-10-31", "2016-11-14",
    },
}

# Special sessions require individual treatment.
NSE_SPECIAL_SESSIONS = {
    "2015-11-11": "Diwali Muhurat trading",
    "2016-10-30": "Diwali Muhurat trading",
}

SOURCES = {
    2015: "NSE Circular NSE/CMTR/28337, 12-Dec-2014",
    2016: "NSE Circular NSE/CMTR/31297, 07-Dec-2015",
}


def classify(date_text):
    session_date = date.fromisoformat(date_text)
    year = session_date.year

    if date_text in NSE_SPECIAL_SESSIONS:
        return (
            "special_session_candidate",
            "Special session; verify instrument record",
            SOURCES.get(year, "NSE special session reference"),
        )

    if session_date.weekday() >= 5:
        return (
            "weekend_session_unverified",
            "Weekend date; special-session verification required",
            "Official exchange circular required",
        )

    if year not in NSE_HOLIDAYS:
        return (
            "calendar_not_loaded",
            "NSE annual calendar not loaded for this year",
            "Pending",
        )

    if date_text in NSE_HOLIDAYS[year]:
        return (
            "official_holiday_candidate",
            "Listed NSE trading holiday; no regular session expected",
            SOURCES[year],
        )

    return (
        "calendar_expected_record_missing",
        "Weekday absent from the published NSE holiday list; "
        "candidate missing instrument record",
        SOURCES[year],
    )


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)

    entries = []

    with SOURCE.open(
        newline="",
        encoding="utf-8",
    ) as file:
        for row in csv.DictReader(file):
            if row["instrument"] != "BANKNIFTY":
                continue

            session_date = row["candidate_missing_date"]

            status, explanation, source = classify(session_date)

            entries.append({
                "instrument": "BANKNIFTY",
                "exchange": "NSE",
                "candidate_date": session_date,
                "weekday": date.fromisoformat(
                    session_date
                ).strftime("%A"),
                "matching_peer_count": row["matching_peer_count"],
                "matching_peers": row["matching_peers"],
                "classification": status,
                "explanation": explanation,
                "calendar_source": source,
                "final_verification": "pending",
            })

    entries.sort(key=lambda item: item["candidate_date"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        fields = list(entries[0].keys()) if entries else []
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(entries)

    counts = Counter(
        entry["classification"]
        for entry in entries
    )

    monthly = defaultdict(int)

    for entry in entries:
        if entry["classification"] == "calendar_expected_record_missing":
            monthly[entry["candidate_date"][:7]] += 1

    print("\nBANK NIFTY GAP REGISTER")
    print("=" * 60)
    print(f"Total peer-supported candidates: {len(entries)}")

    print("\nCLASSIFICATION SUMMARY")

    for status, count in sorted(counts.items()):
        print(f"{status}: {count:,}")

    print("\nCALENDAR-EXPECTED CANDIDATES BY MONTH")

    for month, count in sorted(monthly.items()):
        print(f"{month}: {count}")

    print(f"\nRegister saved: {OUTPUT}")
    print("\nNo raw or curated records were modified.")
    print("All candidates remain pending final verification.")


if __name__ == "__main__":
    main()
