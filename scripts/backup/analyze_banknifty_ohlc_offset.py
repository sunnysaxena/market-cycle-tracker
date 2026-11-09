import csv
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "backend" / "data" / "incoming"
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
OUTPUT = ROOT / "backend" / "data" / "banknifty_ohlc_offset_diagnostic.csv"
FIELDS = ("Open", "High", "Low", "Close")


def load_csv_rows():
    records = {}
    for year in (2015, 2016):
        path = INCOMING / f"banknifty_nse_{year}.csv"
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"Date", *FIELDS}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError(
                    f"Unexpected columns in {path.name}: {reader.fieldnames}"
                )
            for row in reader:
                date_text = row["Date"].strip()
                try:
                    candle_date = datetime.strptime(date_text, "%d %b %Y").date().isoformat()
                except ValueError as exc:
                    raise ValueError(
                        f"Cannot parse date {date_text!r} in {path.name}"
                    ) from exc
                values = {field: float(row[field].replace(",", "").strip()) for field in FIELDS}
                if candle_date in records:
                    raise ValueError(f"Duplicate CSV date across files: {candle_date}")
                records[candle_date] = values
    return records


def load_database_rows():
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)
    uri = f"file:{DATABASE.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute("""
            SELECT candle_date, open, high, low, close
            FROM daily_ohlcv_analytical
            WHERE instrument_code = 'BANKNIFTY'
              AND candle_date BETWEEN '2015-01-01' AND '2016-12-31'
            ORDER BY candle_date
        """).fetchall()
        return {
            date: dict(zip(FIELDS, (float(open_), float(high), float(low), float(close))))
            for date, open_, high, low, close in rows
        }
    finally:
        connection.close()


def describe(values):
    if not values:
        return "n/a"
    return (
        f"count={len(values)}, mean={statistics.mean(values):.5f}, "
        f"median={statistics.median(values):.5f}, "
        f"min={min(values):.5f}, max={max(values):.5f}, "
        f"pstdev={statistics.pstdev(values):.5f}"
    )


def main():
    csv_rows = load_csv_rows()
    db_rows = load_database_rows()
    overlap = sorted(csv_rows.keys() & db_rows.keys())
    if not overlap:
        raise RuntimeError("No overlapping full-OHLC dates were found.")

    deltas_by_field = {field: [] for field in FIELDS}
    row_means = []
    row_spreads = []
    output_rows = []

    for candle_date in overlap:
        deltas = {
            field: csv_rows[candle_date][field] - db_rows[candle_date][field]
            for field in FIELDS
        }
        mean_delta = statistics.mean(deltas.values())
        spread = max(deltas.values()) - min(deltas.values())
        row_means.append(mean_delta)
        row_spreads.append(spread)
        for field in FIELDS:
            deltas_by_field[field].append(deltas[field])
        output_rows.append({
            "date": candle_date,
            **{f"{field.lower()}_delta": round(deltas[field], 6) for field in FIELDS},
            "mean_ohlc_delta": round(mean_delta, 6),
            "within_candle_delta_spread": round(spread, 6),
        })

    print("\nBANKNIFTY PER-CANDLE OHLC OFFSET DIAGNOSTIC")
    print("=" * 82)
    print("CSV records:", len(csv_rows))
    print("Existing full-OHLC overlap:", len(overlap))
    print("Dates present in CSV but not existing full-OHLC:", len(csv_rows) - len(overlap))
    print("\nFIELD DELTAS (NSE CSV minus existing database)")
    for field in FIELDS:
        print(f"{field:<6}: {describe(deltas_by_field[field])}")

    print("\nPER-CANDLE OFFSET CONSISTENCY")
    print("Mean of four OHLC deltas:", describe(row_means))
    print("Spread between largest and smallest OHLC delta on each date:", describe(row_spreads))
    print("Dates with all four deltas within 0.01 of that candle's mean:",
          sum(spread <= 0.01 for spread in row_spreads), "/", len(overlap))
    print("Dates with all four deltas within 0.02 of that candle's mean:",
          sum(spread <= 0.02 for spread in row_spreads), "/", len(overlap))
    print("Dates with all four deltas within 0.05 of that candle's mean:",
          sum(spread <= 0.05 for spread in row_spreads), "/", len(overlap))

    print("\nYEARLY PER-CANDLE MEAN OFFSET")
    for year in (2015, 2016):
        yearly = [
            item["mean_ohlc_delta"]
            for item in output_rows
            if item["date"].startswith(str(year))
        ]
        print(f"{year}: {describe(yearly)}")

    print("\nSAMPLE DATES WITH LARGEST WITHIN-CANDLE OFFSET SPREAD")
    for item in sorted(output_rows, key=lambda x: x["within_candle_delta_spread"], reverse=True)[:10]:
        print(
            item["date"],
            "deltas=", ", ".join(f"{field}={item[field.lower() + '_delta']:+.4f}" for field in FIELDS),
            "spread=", f"{item['within_candle_delta_spread']:.4f}"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    print("\nPer-date diagnostic CSV:", OUTPUT)
    print("Database mode: read-only; no database changes made.")


if __name__ == "__main__":
    main()
