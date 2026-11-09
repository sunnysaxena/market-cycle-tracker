#!/usr/bin/env python3
"""Read-only reconciliation of legacy and NSE BANKNIFTY daily OHLC data.

Reads the already-staged NSE source rows and their legacy overlap fields from
historical_staging.db. Does not update any database table or promote data.

Outputs:
  backend/data/banknifty_source_reconciliation_2015_2016.csv
  backend/data/banknifty_source_reconciliation_monthly_2015_2016.csv
"""

from __future__ import annotations

import csv
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
DETAIL_CSV = ROOT / "backend" / "data" / "banknifty_source_reconciliation_2015_2016.csv"
MONTHLY_CSV = ROOT / "backend" / "data" / "banknifty_source_reconciliation_monthly_2015_2016.csv"

NUMERIC_FIELDS = ("open", "high", "low", "close")


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "pstdev": None,
            "mean_abs": None,
        }
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "pstdev": statistics.pstdev(values),
        "mean_abs": statistics.mean(abs(v) for v in values),
    }


def fmt(value: float | int | None, digits: int = 5) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Staging database not found: {DATABASE}")

    uri = f"file:{DATABASE.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row

    try:
        # Verify the required staging schema before doing any calculations.
        table_columns = {
            row[1]
            for row in connection.execute(
                'PRAGMA table_info("external_index_daily_records")'
            ).fetchall()
        }
        required = {
            "batch_id", "instrument_code", "candle_date", "open", "high",
            "low", "close", "legacy_open", "legacy_high", "legacy_low",
            "legacy_close", "overlap_status", "quality_status"
        }
        missing_columns = sorted(required - table_columns)
        if missing_columns:
            raise RuntimeError(
                "external_index_daily_records is missing required columns: "
                + ", ".join(missing_columns)
            )

        records = connection.execute("""
            SELECT
                r.batch_id,
                b.calendar_year,
                r.source_row_number,
                r.candle_date,
                r.source_index_name,
                r.open, r.high, r.low, r.close,
                r.legacy_open, r.legacy_high, r.legacy_low, r.legacy_close,
                r.open_difference, r.high_difference,
                r.low_difference, r.close_difference,
                r.overlap_status,
                r.quality_status,
                r.issue_codes
            FROM external_index_daily_records AS r
            JOIN external_index_source_batches AS b
              ON b.id = r.batch_id
            WHERE r.instrument_code = 'BANKNIFTY'
              AND b.calendar_year IN (2015, 2016)
            ORDER BY r.candle_date
        """).fetchall()

        if not records:
            raise RuntimeError("No staged BANKNIFTY records found for 2015–2016.")

        # One source date should appear only once across the two yearly files.
        source_by_date: dict[str, dict[str, Any]] = {}
        for row in records:
            d = row["candle_date"]
            if d in source_by_date:
                raise RuntimeError(f"Duplicate staged source date found: {d}")
            source_by_date[d] = dict(row)

        # Source returns use the immediately preceding date in the complete NSE
        # source series. Legacy returns are compared only when that same
        # immediately preceding source date also exists in the legacy series.
        ordered_dates = sorted(source_by_date)
        source_prev_date: dict[str, str | None] = {}
        for index, d in enumerate(ordered_dates):
            source_prev_date[d] = ordered_dates[index - 1] if index else None

        for d, row in source_by_date.items():
            row["source_previous_date"] = source_prev_date[d]
            row["source_daily_return_pct"] = None
            row["legacy_daily_return_pct"] = None
            row["daily_return_difference_pp"] = None
            row["daily_return_difference_bps"] = None

            previous_date = source_prev_date[d]
            if previous_date is None:
                continue

            previous_source_close = safe_float(source_by_date[previous_date]["close"])
            current_source_close = safe_float(row["close"])
            if previous_source_close and current_source_close is not None:
                row["source_daily_return_pct"] = (
                    (current_source_close / previous_source_close) - 1.0
                ) * 100.0

            previous_legacy_close = safe_float(source_by_date[previous_date]["legacy_close"])
            current_legacy_close = safe_float(row["legacy_close"])
            if (
                previous_legacy_close is not None
                and previous_legacy_close != 0
                and current_legacy_close is not None
            ):
                row["legacy_daily_return_pct"] = (
                    (current_legacy_close / previous_legacy_close) - 1.0
                ) * 100.0
                if row["source_daily_return_pct"] is not None:
                    difference_pp = (
                        row["source_daily_return_pct"]
                        - row["legacy_daily_return_pct"]
                    )
                    row["daily_return_difference_pp"] = difference_pp
                    row["daily_return_difference_bps"] = difference_pp * 100.0

        detail_rows: list[dict[str, Any]] = []
        monthly_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for d in ordered_dates:
            row = source_by_date[d]
            source = {field: safe_float(row[field]) for field in NUMERIC_FIELDS}
            legacy = {field: safe_float(row[f"legacy_{field}"]) for field in NUMERIC_FIELDS}
            deltas = {
                field: (
                    source[field] - legacy[field]
                    if source[field] is not None and legacy[field] is not None
                    else None
                )
                for field in NUMERIC_FIELDS
            }
            available_deltas = [v for v in deltas.values() if v is not None]
            spread = (
                max(available_deltas) - min(available_deltas)
                if len(available_deltas) == 4
                else None
            )
            mean_delta = statistics.mean(available_deltas) if len(available_deltas) == 4 else None

            source_body = (
                source["close"] - source["open"]
                if source["close"] is not None and source["open"] is not None else None
            )
            legacy_body = (
                legacy["close"] - legacy["open"]
                if legacy["close"] is not None and legacy["open"] is not None else None
            )
            source_range = (
                source["high"] - source["low"]
                if source["high"] is not None and source["low"] is not None else None
            )
            legacy_range = (
                legacy["high"] - legacy["low"]
                if legacy["high"] is not None and legacy["low"] is not None else None
            )

            source_upper_wick = (
                source["high"] - max(source["open"], source["close"])
                if all(source[k] is not None for k in ("high", "open", "close")) else None
            )
            legacy_upper_wick = (
                legacy["high"] - max(legacy["open"], legacy["close"])
                if all(legacy[k] is not None for k in ("high", "open", "close")) else None
            )
            source_lower_wick = (
                min(source["open"], source["close"]) - source["low"]
                if all(source[k] is not None for k in ("open", "close", "low")) else None
            )
            legacy_lower_wick = (
                min(legacy["open"], legacy["close"]) - legacy["low"]
                if all(legacy[k] is not None for k in ("open", "close", "low")) else None
            )

            out = {
                "date": d,
                "year": row["calendar_year"],
                "batch_id": row["batch_id"],
                "source_row_number": row["source_row_number"],
                "index_name": row["source_index_name"],
                "overlap_status": row["overlap_status"],
                "quality_status": row["quality_status"],
            }
            for field in NUMERIC_FIELDS:
                out[f"source_{field}"] = source[field]
                out[f"legacy_{field}"] = legacy[field]
                out[f"{field}_delta"] = deltas[field]
            out.update({
                "ohlc_delta_mean": mean_delta,
                "ohlc_delta_spread": spread,
                "source_body": source_body,
                "legacy_body": legacy_body,
                "body_difference": (
                    source_body - legacy_body
                    if source_body is not None and legacy_body is not None else None
                ),
                "source_range": source_range,
                "legacy_range": legacy_range,
                "range_difference": (
                    source_range - legacy_range
                    if source_range is not None and legacy_range is not None else None
                ),
                "source_upper_wick": source_upper_wick,
                "legacy_upper_wick": legacy_upper_wick,
                "upper_wick_difference": (
                    source_upper_wick - legacy_upper_wick
                    if source_upper_wick is not None and legacy_upper_wick is not None else None
                ),
                "source_lower_wick": source_lower_wick,
                "legacy_lower_wick": legacy_lower_wick,
                "lower_wick_difference": (
                    source_lower_wick - legacy_lower_wick
                    if source_lower_wick is not None and legacy_lower_wick is not None else None
                ),
                "source_previous_date": row["source_previous_date"],
                "source_daily_return_pct": row["source_daily_return_pct"],
                "legacy_daily_return_pct": row["legacy_daily_return_pct"],
                "daily_return_difference_pp": row["daily_return_difference_pp"],
                "daily_return_difference_bps": row["daily_return_difference_bps"],
            })
            detail_rows.append(out)
            monthly_groups[d[:7]].append(out)

        detail_columns = list(detail_rows[0].keys())
        write_csv(DETAIL_CSV, detail_rows, detail_columns)

        monthly_rows: list[dict[str, Any]] = []
        for month in sorted(monthly_groups):
            rows = monthly_groups[month]
            summary: dict[str, Any] = {
                "month": month,
                "source_rows": len(rows),
                "legacy_close_overlap": sum(r["legacy_close"] is not None for r in rows),
                "legacy_full_ohlc_overlap": sum(
                    all(r[f"legacy_{field}"] is not None for field in NUMERIC_FIELDS)
                    for r in rows
                ),
                "comparable_daily_returns": sum(
                    r["daily_return_difference_pp"] is not None for r in rows
                ),
            }
            for field in NUMERIC_FIELDS:
                values = [r[f"{field}_delta"] for r in rows if r[f"{field}_delta"] is not None]
                s = stats(values)
                summary[f"{field}_delta_mean"] = s["mean"]
                summary[f"{field}_delta_median"] = s["median"]
                summary[f"{field}_delta_min"] = s["min"]
                summary[f"{field}_delta_max"] = s["max"]
            for metric in (
                "body_difference", "range_difference", "upper_wick_difference",
                "lower_wick_difference", "daily_return_difference_pp",
                "daily_return_difference_bps"
            ):
                values = [r[metric] for r in rows if r[metric] is not None]
                s = stats(values)
                summary[f"{metric}_mean"] = s["mean"]
                summary[f"{metric}_median"] = s["median"]
                summary[f"{metric}_mean_abs"] = s["mean_abs"]
                summary[f"{metric}_max_abs"] = max((abs(v) for v in values), default=None)
            monthly_rows.append(summary)

        write_csv(MONTHLY_CSV, monthly_rows, list(monthly_rows[0].keys()))

        # Overall statistics and sample counts.
        full_overlap = [r for r in detail_rows if all(r[f"legacy_{f}"] is not None for f in NUMERIC_FIELDS)]
        close_overlap = [r for r in detail_rows if r["legacy_close"] is not None]
        comparable_returns = [r for r in detail_rows if r["daily_return_difference_pp"] is not None]

        print("\nBANKNIFTY SOURCE RECONCILIATION")
        print("=" * 82)
        print("Database mode: read-only")
        print("Staged NSE rows:", len(detail_rows))
        print("Legacy close overlaps:", len(close_overlap))
        print("Legacy full-OHLC overlaps:", len(full_overlap))
        print("Comparable one-session daily returns:", len(comparable_returns))

        print("\nOHLC PRICE DIFFERENCES (NSE source minus legacy)")
        print("-" * 82)
        print(f"{'FIELD':<10}{'COUNT':>8}{'MEAN':>12}{'MEDIAN':>12}{'MIN':>12}{'MAX':>12}{'STD DEV':>12}")
        for field in NUMERIC_FIELDS:
            values = [r[f"{field}_delta"] for r in full_overlap if r[f"{field}_delta"] is not None]
            s = stats(values)
            print(
                f"{field:<10}{s['count']:>8}{fmt(s['mean']):>12}"
                f"{fmt(s['median']):>12}{fmt(s['min']):>12}"
                f"{fmt(s['max']):>12}{fmt(s['pstdev']):>12}"
            )

        print("\nCANDLE GEOMETRY DIFFERENCES (NSE source minus legacy)")
        print("-" * 82)
        for metric in ("body_difference", "range_difference", "upper_wick_difference", "lower_wick_difference"):
            values = [r[metric] for r in full_overlap if r[metric] is not None]
            s = stats(values)
            print(
                f"{metric:<25} n={s['count']:>3}"
                f" mean={fmt(s['mean'])} median={fmt(s['median'])}"
                f" mean_abs={fmt(s['mean_abs'])} max_abs={fmt(max((abs(v) for v in values), default=None))}"
            )

        print("\nDAILY RETURN COMPARISON")
        print("-" * 82)
        return_values = [r["daily_return_difference_pp"] for r in comparable_returns]
        return_stats = stats(return_values)
        print("Comparable returns:", return_stats["count"])
        print("Mean difference (percentage points):", fmt(return_stats["mean"], 7))
        print("Median difference (percentage points):", fmt(return_stats["median"], 7))
        print("Mean absolute difference (percentage points):", fmt(return_stats["mean_abs"], 7))
        print("Maximum absolute difference (percentage points):", fmt(max((abs(v) for v in return_values), default=None), 7))

        print("\nYEARLY SUMMARY")
        print("-" * 82)
        for year in (2015, 2016):
            year_rows = [r for r in detail_rows if r["year"] == year]
            year_full = [r for r in year_rows if all(r[f"legacy_{f}"] is not None for f in NUMERIC_FIELDS)]
            year_returns = [r["daily_return_difference_pp"] for r in year_rows if r["daily_return_difference_pp"] is not None]
            close_deltas = [r["close_delta"] for r in year_rows if r["close_delta"] is not None]
            print(
                f"{year}: source={len(year_rows)}, full_OHLC_overlap={len(year_full)}, "
                f"close_overlap={sum(r['legacy_close'] is not None for r in year_rows)}, "
                f"return_comparisons={len(year_returns)}, "
                f"mean_close_delta={fmt(statistics.mean(close_deltas) if close_deltas else None)}, "
                f"mean_abs_return_difference_pp={fmt(statistics.mean(abs(v) for v in year_returns) if year_returns else None, 7)}"
            )

        print("\nOUTPUT FILES")
        print("Detailed date-level report:", DETAIL_CSV)
        print("Monthly reconciliation report:", MONTHLY_CSV)
        print("Database changes: none.")
        print("Canonical data promotion: none.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
