"""Controlled SQLite staging -> PostgreSQL migration for Market Cycle Tracker.

Default is a transaction-backed DRY RUN (inserts are rolled back).
Use --apply only after a successful dry run has been reviewed.
Run from E:\\market-cycle-tracker\\backend:
    python scripts\\migrate_staging_to_postgres.py
    python scripts\\migrate_staging_to_postgres.py --apply

SQLite is opened read-only and is never modified.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, MetaData, Numeric, Table, func, insert, select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
SQLITE_PATH = BACKEND_DIR / "data" / "historical_staging.db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from app.core.database import engine  # noqa: E402

BATCH_ID = 5
JSON_COLUMNS = {
    "metadata_json", "calendar_missing_dates_json", "calendar_unexpected_dates_json",
    "issue_codes", "raw_record_ids_json",
}

# Source table, PostgreSQL table, optional SQLite WHERE expression, parameters.
SPECS = [
    ("import_batches", "historical_snapshots", None, ()),
    ("historical_data_sources", "historical_data_sources", None, ()),
    ("external_index_source_batches", "external_index_source_batches", None, ()),
    ("historical_instrument_source_mappings", "historical_instrument_source_mappings", None, ()),
    ("historical_source_batch_links", "historical_source_batch_links", None, ()),
    ("historical_snapshot_sources", "historical_snapshot_sources", None, ()),
    ("daily_quality_assessments", "daily_quality_assessments", "import_batch_id = ?", (BATCH_ID,)),
    ("daily_close_series", "daily_close_series", "import_batch_id = ?", (BATCH_ID,)),
    ("daily_ohlcv_analytical", "daily_ohlcv", "import_batch_id = ?", (BATCH_ID,)),
    ("aggregated_ohlcv", "aggregated_ohlcv", "import_batch_id = ?", (BATCH_ID,)),
    ("aggregated_close_series", "aggregated_close_series", "import_batch_id = ?", (BATCH_ID,)),
    ("historical_quality_annotations", "historical_quality_annotations", None, ()),
]

EXPECTED = {
    "historical_snapshots": 5,
    "historical_data_sources": 3,
    "external_index_source_batches": 14,
    "historical_instrument_source_mappings": 19,
    "historical_source_batch_links": 39,
    "historical_snapshot_sources": 12,
    "historical_raw_records": 22617,  # batch 5 plus 8 referenced older raw records
    "daily_quality_assessments": 22609,
    "daily_close_series": 22555,
    "daily_ohlcv": 22435,
    "aggregated_ohlcv": 5953,
    "aggregated_close_series": 5984,
    "historical_quality_annotations": 11,
}
DEST_TABLES = list(EXPECTED)
SEQUENCES = {
    "historical_snapshots": "id",
    "external_index_source_batches": "id",
    "historical_instrument_source_mappings": "mapping_id",
    "historical_snapshot_sources": "id",
    "historical_raw_records": "id",
    "aggregated_ohlcv": "id",
    "aggregated_close_series": "id",
}


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def read_rows(conn: sqlite3.Connection, table: str, where: str | None = None,
              params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {qident(table)}"
    if where:
        sql += f" WHERE {where}"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def load_source_rows() -> tuple[dict[str, list[dict[str, Any]]], set[int]]:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"SQLite staging database not found: {SQLITE_PATH}")
    sqlite_conn = sqlite3.connect(f"file:{SQLITE_PATH.as_posix()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_conn.execute("PRAGMA query_only = ON")
    try:
        annotations = read_rows(sqlite_conn, "historical_quality_annotations")
        annotation_ids: set[int] = set()
        for a in annotations:
            raw_ids = a.get("raw_record_ids_json")
            if raw_ids:
                parsed = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
                if not isinstance(parsed, list):
                    raise ValueError(f"Invalid raw_record_ids_json in {a['annotation_code']}")
                annotation_ids.update(int(x) for x in parsed)
            if a.get("canonical_raw_record_id") is not None:
                annotation_ids.add(int(a["canonical_raw_record_id"]))

        if annotation_ids:
            ids = sorted(annotation_ids)
            marks = ",".join("?" for _ in ids)
            found = sqlite_conn.execute(
                f"SELECT id FROM raw_daily_records WHERE id IN ({marks})", tuple(ids)
            ).fetchall()
            found_ids = {int(r["id"]) for r in found}
            missing = sorted(annotation_ids - found_ids)
            if missing:
                raise ValueError(f"Annotation raw-record IDs missing from SQLite: {missing}")

        marks = ",".join("?" for _ in annotation_ids)
        raw_where = "import_batch_id = ?"
        raw_params: tuple[Any, ...] = (BATCH_ID,)
        if annotation_ids:
            raw_where = f"(import_batch_id = ?) OR id IN ({marks})"
            raw_params = (BATCH_ID, *sorted(annotation_ids))
        raw_rows = read_rows(sqlite_conn, "raw_daily_records", raw_where, raw_params)

        batch5_rows = [r for r in raw_rows if int(r["import_batch_id"]) == BATCH_ID]
        dependency_rows = [r for r in raw_rows if int(r["import_batch_id"]) != BATCH_ID]
        if len(batch5_rows) != 22609:
            raise ValueError(f"Expected 22,609 batch 5 raw rows; found {len(batch5_rows)}")
        if len(dependency_rows) != 8:
            raise ValueError(f"Expected 8 older annotation dependency rows; found {len(dependency_rows)}")
        if not annotation_ids.issubset({int(r["id"]) for r in raw_rows}):
            raise ValueError("Not all annotation raw-record dependencies were selected")

        selected: dict[str, list[dict[str, Any]]] = {"historical_raw_records": raw_rows}
        for source, dest, where, params in SPECS:
            selected[dest] = annotations if source == "historical_quality_annotations" else read_rows(
                sqlite_conn, source, where, params
            )
        return selected, annotation_ids
    finally:
        sqlite_conn.close()


def verify_source_counts(rows: dict[str, list[dict[str, Any]]]) -> None:
    errors = [f"{t}: expected {n:,}, found {len(rows.get(t, [])):,}"
              for t, n in EXPECTED.items() if len(rows.get(t, [])) != n]
    if errors:
        raise ValueError("Source row-count audit mismatch:\n  " + "\n  ".join(errors))


def convert(value: Any, column: Any) -> Any:
    if value is None:
        return None
    name, typ = column.name, column.type
    if name in JSON_COLUMNS:
        return value if isinstance(value, (dict, list)) else json.loads(value)
    if isinstance(typ, DateTime):
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if typ.timezone:
            return dt
        if dt.tzinfo is not None:
            # *_utc values with offsets (including +05:30) are normalized to UTC.
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        # Keep naive source_timestamp session dates unchanged.
        return dt
    if isinstance(typ, Date):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    if isinstance(typ, Numeric):
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if isinstance(typ, Boolean):
        return bool(value)
    return value


def prepare_rows(source_rows: list[dict[str, Any]], table: Table, name: str) -> list[dict[str, Any]]:
    columns = {c.name: c for c in table.columns}
    prepared = []
    for idx, row in enumerate(source_rows, start=1):
        missing = set(columns) - set(row)
        if missing:
            raise ValueError(f"{name} source row {idx} lacks columns: {sorted(missing)}")
        prepared.append({col: convert(row[col], spec) for col, spec in columns.items()})
    return prepared


def set_sequences(conn: Any) -> None:
    for table, column in SEQUENCES.items():
        seq = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"),
            {"t": f"public.{table}", "c": column},
        ).scalar_one_or_none()
        if not seq:
            print(f"  No serial sequence detected for {table}.{column}; skipped")
            continue
        max_id = conn.execute(text(f'SELECT COALESCE(MAX("{column}"), 1) FROM public."{table}"')).scalar_one()
        conn.execute(text("SELECT setval(CAST(:seq AS regclass), :val, true)"), {"seq": seq, "val": max_id})


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate audited historical staging data to PostgreSQL")
    parser.add_argument("--apply", action="store_true", help="Commit the migration; default is dry-run and rollback")
    args = parser.parse_args()

    print("MARKET CYCLE TRACKER — HISTORICAL DATA MIGRATION")
    print("Mode:", "APPLY / COMMIT" if args.apply else "DRY RUN / ROLLBACK")
    print("SQLite:", SQLITE_PATH)
    print("PostgreSQL database:", engine.url.database)

    rows, annotation_ids = load_source_rows()
    verify_source_counts(rows)
    print("\n=== AUDITED SOURCE ROW COUNTS ===")
    for table, count in EXPECTED.items():
        print(f"{table:43} {count:>10,}")
    print(f"Annotation raw-record dependencies: {len(annotation_ids):,}")

    # Start a single transaction before reflection, checks, and inserts.
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            metadata = MetaData()
            tables = {name: Table(name, metadata, schema="public", autoload_with=conn)
                      for name in DEST_TABLES}

            nonempty = []
            for name, table in tables.items():
                count = conn.execute(select(func.count()).select_from(table)).scalar_one()
                if count:
                    nonempty.append(f"{name}={count:,}")
            if nonempty:
                raise RuntimeError("Destination tables are not empty; refusing to overwrite/append: " + ", ".join(nonempty))

            codes = set()
            for record_rows in rows.values():
                for record in record_rows:
                    if record.get("instrument_code"):
                        codes.add(str(record["instrument_code"]))
            existing_codes = set(conn.execute(text("SELECT code FROM public.index_master")).scalars())
            missing_codes = sorted(codes - existing_codes)
            if missing_codes:
                raise ValueError("Missing index_master instruments: " + ", ".join(missing_codes))

            prepared = {name: prepare_rows(rows[name], tables[name], name) for name in DEST_TABLES}

            order = [
                "historical_snapshots",
                "historical_data_sources",
                "external_index_source_batches",
                "historical_instrument_source_mappings",
                "historical_raw_records",
                "historical_source_batch_links",
                "historical_snapshot_sources",
                "daily_quality_assessments",
                "daily_close_series",
                "daily_ohlcv",
                "aggregated_ohlcv",
                "aggregated_close_series",
                "historical_quality_annotations",
            ]
            print("\n=== POSTGRESQL INSERT / CONSTRAINT VALIDATION ===")
            for name in order:
                data = prepared[name]
                statement = insert(tables[name])
                for start in range(0, len(data), 1000):
                    conn.execute(statement, data[start:start + 1000])
                print(f"{name:43} tested {len(data):>10,}")

            failures = []
            for name, expected in EXPECTED.items():
                actual = conn.execute(select(func.count()).select_from(tables[name])).scalar_one()
                if actual != expected:
                    failures.append(f"{name}: expected {expected}, found {actual}")
            if failures:
                raise RuntimeError("Post-insert row-count checks failed: " + "; ".join(failures))

            if args.apply:
                set_sequences(conn)
                tx.commit()
                print("\nPOSTGRESQL TRANSACTION COMMITTED.")
            else:
                tx.rollback()
                print("\nDRY RUN PASSED. Transaction rolled back; no historical rows committed.")
        except Exception:
            if tx.is_active:
                tx.rollback()
            raise

    if args.apply:
        print("\n=== POST-COMMIT VERIFICATION ===")
        with engine.connect() as verify_conn:
            for name, expected in EXPECTED.items():
                actual = verify_conn.execute(text(f'SELECT COUNT(*) FROM public."{name}"')).scalar_one()
                print(f"{name:43} {actual:>10,}")
                if actual != expected:
                    raise RuntimeError(f"Post-commit mismatch for {name}: expected {expected}, found {actual}")
        print("\nMIGRATION APPLIED AND VERIFIED.")
    else:
        print("Review the dry-run output before running with --apply.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nMIGRATION FAILED: {exc}", file=sys.stderr)
        raise
