from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
DEFAULT_OUTPUT_DIR = ROOT / "backend" / "data" / "audit_reports"

INSTRUMENTS = (
    "BANKNIFTY",
    "FINNIFTY",
    "INDIA_VIX",
    "MIDCPNIFTY",
    "NIFTY50",
    "SENSEX",
)
TIMEFRAMES = ("1W", "1M", "1Y")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only historical data freshness report. Uses calendar-day age; "
            "does not infer missing trading sessions from incomplete calendars."
        )
    )
    parser.add_argument("--batch-id", type=int, default=None)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--warning-days", type=int, default=7)
    parser.add_argument("--critical-days", type=int, default=30)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    # Use the same SQLite URI pattern used by the project's other Windows scripts.
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def choose_batch(con: sqlite3.Connection, requested: int | None) -> int:
    if requested is not None:
        row = con.execute(
            "SELECT id FROM import_batches WHERE id=? AND status='completed'",
            (requested,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Import batch {requested} does not exist or is not completed.")
        return int(row["id"])
    row = con.execute(
        "SELECT id FROM import_batches WHERE status='completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No completed import batch exists.")
    return int(row["id"])


def get_mapping(
    con: sqlite3.Connection,
    instrument: str,
    source_table: str | None,
    candle_date: str | None,
) -> dict[str, Any] | None:
    if not table_exists(con, "historical_instrument_source_mappings"):
        return None
    if not candle_date:
        return None

    rows = con.execute(
        """
        SELECT mapping_code, source_code, source_table, mapping_role,
               mapping_status, valid_from, valid_to, priority
        FROM historical_instrument_source_mappings
        WHERE instrument_code = ?
          AND timeframe = '1D'
          AND mapping_status = 'active'
          AND (valid_from IS NULL OR valid_from <= ?)
          AND (valid_to IS NULL OR valid_to >= ?)
        ORDER BY
          CASE mapping_role
            WHEN 'preferred_for_period' THEN 0
            WHEN 'legacy_reference' THEN 1
            WHEN 'fallback_reference' THEN 2
            WHEN 'supplemental' THEN 3
            ELSE 4
          END,
          priority ASC,
          mapping_code ASC
        """,
        (instrument, candle_date, candle_date),
    ).fetchall()
    for row in rows:
        if source_table is None or row["source_table"] == source_table:
            return dict(row)
    return dict(rows[0]) if rows else None


def latest_aggregate(
    con: sqlite3.Connection,
    batch_id: int,
    instrument: str,
    timeframe: str,
) -> tuple[str | None, str | None]:
    if not table_exists(con, "aggregated_ohlcv"):
        return None, None
    row = con.execute(
        """
        SELECT period_end, generated_at_utc
        FROM aggregated_ohlcv
        WHERE import_batch_id = ? AND instrument_code = ? AND timeframe = ?
        ORDER BY period_end DESC
        LIMIT 1
        """,
        (batch_id, instrument, timeframe),
    ).fetchone()
    if row is None:
        return None, None
    return row["period_end"], row["generated_at_utc"]


def build_rows(
    con: sqlite3.Connection,
    batch_id: int,
    as_of: date,
    warning_days: int,
    critical_days: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for instrument in INSTRUMENTS:
        close = con.execute(
            """
            SELECT COUNT(*) AS n, MAX(candle_date) AS latest
            FROM daily_close_series
            WHERE import_batch_id = ? AND instrument_code = ?
            """,
            (batch_id, instrument),
        ).fetchone()
        ohlc = con.execute(
            """
            SELECT COUNT(*) AS n, MAX(candle_date) AS latest,
                   SUM(CASE WHEN volume_status = 'unavailable' THEN 1 ELSE 0 END) AS volume_unavailable,
                   SUM(CASE WHEN volume_status <> 'unavailable' THEN 1 ELSE 0 END) AS volume_available
            FROM daily_ohlcv_analytical
            WHERE import_batch_id = ? AND instrument_code = ?
            """,
            (batch_id, instrument),
        ).fetchone()

        latest_close_date = close["latest"]
        latest_ohlc_date = ohlc["latest"]
        close_age = (as_of - date.fromisoformat(latest_close_date)).days if latest_close_date else None
        ohlc_age = (as_of - date.fromisoformat(latest_ohlc_date)).days if latest_ohlc_date else None

        source_table = None
        if latest_close_date:
            source_row = con.execute(
                """
                SELECT source_table
                FROM daily_close_series
                WHERE import_batch_id = ? AND instrument_code = ? AND candle_date = ?
                LIMIT 1
                """,
                (batch_id, instrument, latest_close_date),
            ).fetchone()
            source_table = source_row["source_table"] if source_row else None
        mapping = get_mapping(con, instrument, source_table, latest_close_date)

        aggregates: dict[str, str | None] = {}
        generated_values: list[str] = []
        for timeframe in TIMEFRAMES:
            period_end, generated_at = latest_aggregate(
                con, batch_id, instrument, timeframe
            )
            aggregates[timeframe] = period_end
            if generated_at:
                generated_values.append(generated_at)

        ages = [a for a in (close_age, ohlc_age) if a is not None]
        worst_age = max(ages) if ages else None
        if worst_age is None:
            status = "no_daily_data"
            note = "No daily close or full-OHLC record exists in this snapshot."
        elif worst_age > critical_days:
            status = "critical_stale"
            note = (
                f"Latest local daily data is {worst_age} calendar days old. "
                "This is a freshness warning, not proof of a missing trading session."
            )
        elif worst_age > warning_days:
            status = "warning_stale"
            note = (
                f"Latest local daily data is {worst_age} calendar days old. "
                "Exchange holidays and weekends are not subtracted."
            )
        else:
            status = "fresh_by_calendar_age"
            note = (
                f"Latest local daily data is {worst_age} calendar days old. "
                "This does not independently verify that all expected sessions are present."
            )

        out.append({
            "batch_id": batch_id,
            "instrument_code": instrument,
            "as_of_date": as_of.isoformat(),
            "daily_close_rows": int(close["n"] or 0),
            "latest_close_date": latest_close_date or "",
            "close_age_calendar_days": close_age if close_age is not None else "",
            "daily_full_ohlc_rows": int(ohlc["n"] or 0),
            "latest_full_ohlc_date": latest_ohlc_date or "",
            "ohlc_age_calendar_days": ohlc_age if ohlc_age is not None else "",
            "latest_close_source_table": source_table or "",
            "matched_source_mapping_code": mapping["mapping_code"] if mapping else "",
            "matched_source_code": mapping["source_code"] if mapping else "",
            "matched_mapping_role": mapping["mapping_role"] if mapping else "",
            "mapping_status": mapping["mapping_status"] if mapping else "unmatched",
            "latest_weekly_period_end": aggregates["1W"] or "",
            "latest_monthly_period_end": aggregates["1M"] or "",
            "latest_yearly_period_end": aggregates["1Y"] or "",
            "volume_available_ohlc_rows": int(ohlc["volume_available"] or 0),
            "volume_unavailable_ohlc_rows": int(ohlc["volume_unavailable"] or 0),
            "latest_aggregate_generated_at_utc": max(generated_values) if generated_values else "",
            "freshness_status": status,
            "freshness_note": note,
        })
    return out


def main() -> int:
    args = parse_args()
    if args.warning_days < 0 or args.critical_days < 0:
        raise ValueError("Freshness thresholds must be non-negative.")
    if args.critical_days < args.warning_days:
        raise ValueError("--critical-days must be greater than or equal to --warning-days.")

    con = connect_read_only(args.database)
    try:
        batch_id = choose_batch(con, args.batch_id)
        batch = con.execute(
            "SELECT status, imported_at_utc, source_path FROM import_batches WHERE id=?",
            (batch_id,),
        ).fetchone()
        rows = build_rows(
            con, batch_id, args.as_of, args.warning_days, args.critical_days
        )
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()

        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / (
            f"historical_data_freshness_batch_{batch_id}_{args.as_of.isoformat()}.csv"
        )
        with output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        print("\nMARKET CYCLE TRACKER — HISTORICAL DATA FRESHNESS")
        print("=" * 100)
        print(f"Database          : {args.database.resolve()}")
        print(f"Snapshot batch    : {batch_id} ({batch['status']})")
        print(f"Snapshot source   : {batch['source_path']}")
        print(f"As-of date        : {args.as_of.isoformat()}")
        print(f"Warning threshold : > {args.warning_days} calendar days")
        print(f"Critical threshold: > {args.critical_days} calendar days")
        print("Age basis         : calendar days; weekends/holidays are not subtracted")
        print("Mode              : READ-ONLY")
        print("\nINSTRUMENT FRESHNESS")
        print("-" * 100)
        print(f"{'INSTRUMENT':<12}{'LATEST CLOSE':<14}{'AGE(D)':>8}{'LATEST OHLC':<14}{'AGE(D)':>8}{'STATUS':>22}")
        for r in rows:
            print(
                f"{r['instrument_code']:<12}"
                f"{r['latest_close_date']:<14}"
                f"{str(r['close_age_calendar_days']):>8}"
                f"{r['latest_full_ohlc_date']:<14}"
                f"{str(r['ohlc_age_calendar_days']):>8}"
                f"{r['freshness_status']:>22}"
            )
        print("\nSOURCE MAPPING")
        for r in rows:
            print(
                f"{r['instrument_code']}: {r['matched_source_mapping_code'] or 'UNMATCHED'} "
                f"| role={r['matched_mapping_role'] or '-'} "
                f"| table={r['latest_close_source_table'] or '-'}"
            )
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            counts[r["freshness_status"]] += 1
        print("\nFRESHNESS COUNTS")
        for key in sorted(counts):
            print(f"{key}: {counts[key]}")
        print(f"\nSQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print(f"CSV report: {output.resolve()}")
        print("Database mode: read-only; no records modified.")
        print("Note: stale age is not a confirmed missing-session diagnosis.")
        return 0 if integrity == "ok" and not fk_errors else 2
    finally:
        con.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
