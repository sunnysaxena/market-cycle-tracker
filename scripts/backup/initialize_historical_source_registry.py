from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"

LEGACY_SOURCE_CODE = "LEGACY_MYSQL_DUMP_20260308"
NSE_SOURCE_CODE = "NSE_INDICES_HISTORICAL_DATA"

EXPECTED_INSTRUMENTS = {
    "BANKNIFTY",
    "FINNIFTY",
    "INDIA_VIX",
    "MIDCPNIFTY",
    "NIFTY50",
    "SENSEX",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_baseline(connection: sqlite3.Connection) -> dict[str, Any]:
    required_tables = {
        "import_batches",
        "raw_daily_records",
        "external_index_source_batches",
        "external_index_daily_records",
    }
    present = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(required_tables - present)
    if missing:
        raise RuntimeError(
            "Required staging tables are missing: " + ", ".join(missing)
        )

    legacy_batch = connection.execute(
        "SELECT * FROM import_batches WHERE id = 1"
    ).fetchone()
    composite_batch = connection.execute(
        "SELECT * FROM import_batches WHERE id = 2"
    ).fetchone()
    if legacy_batch is None or composite_batch is None:
        raise RuntimeError("Expected legacy batch 1 and composite batch 2.")

    legacy_tables = connection.execute(
        """
        SELECT instrument_code, source_table,
               COUNT(*) AS row_count,
               MIN(date(source_timestamp)) AS first_date,
               MAX(date(source_timestamp)) AS last_date
        FROM raw_daily_records
        WHERE import_batch_id = 1
        GROUP BY instrument_code, source_table
        ORDER BY instrument_code, source_table
        """
    ).fetchall()

    discovered_instruments = {row["instrument_code"] for row in legacy_tables}
    if discovered_instruments != EXPECTED_INSTRUMENTS:
        raise RuntimeError(
            "Unexpected legacy instrument set. Expected "
            f"{sorted(EXPECTED_INSTRUMENTS)}, found {sorted(discovered_instruments)}"
        )

    external_batches = connection.execute(
        """
        SELECT id, source_provider, source_url, instrument_code,
               source_index_name, source_filename, source_sha256,
               source_size_bytes, calendar_year, source_row_count,
               unique_date_count, import_status
        FROM external_index_source_batches
        ORDER BY calendar_year, id
        """
    ).fetchall()
    if not external_batches:
        raise RuntimeError("No external source batches were found.")

    if any(row["instrument_code"] != "BANKNIFTY" for row in external_batches):
        raise RuntimeError(
            "This initial registry setup expects the currently staged external "
            "source files to be BANKNIFTY NSE data only."
        )

    raw_nse_tables = connection.execute(
        """
        SELECT DISTINCT source_table
        FROM raw_daily_records
        WHERE import_batch_id = 2
          AND instrument_code = 'BANKNIFTY'
          AND source_table LIKE 'nse_indices_historical_%'
        ORDER BY source_table
        """
    ).fetchall()
    nse_table_names = {row["source_table"] for row in raw_nse_tables}

    return {
        "legacy_batch": dict(legacy_batch),
        "composite_batch": dict(composite_batch),
        "legacy_tables": [dict(row) for row in legacy_tables],
        "external_batches": [dict(row) for row in external_batches],
        "nse_table_names": sorted(nse_table_names),
    }


def build_plan(baseline: dict[str, Any]) -> dict[str, Any]:
    legacy = baseline["legacy_batch"]
    composite = baseline["composite_batch"]
    external = baseline["external_batches"]

    legacy_metadata = {
        "original_import_batch_id": legacy["id"],
        "source_path": legacy["source_path"],
        "source_sha256": legacy["source_sha256"],
        "source_size_bytes": legacy["source_size_bytes"],
        "imported_rows": legacy["imported_rows"],
        "composite_snapshot_batch_id": composite["id"],
    }
    nse_metadata = {
        "external_source_batch_ids": [row["id"] for row in external],
        "files": [
            {
                "external_batch_id": row["id"],
                "calendar_year": row["calendar_year"],
                "filename": row["source_filename"],
                "sha256": row["source_sha256"],
                "source_row_count": row["source_row_count"],
            }
            for row in external
        ],
        "composite_snapshot_batch_id": composite["id"],
    }

    mappings: list[dict[str, Any]] = []
    for row in baseline["legacy_tables"]:
        instrument = row["instrument_code"]
        table = row["source_table"]
        mappings.append(
            {
                "mapping_code": f"LEGACY:{instrument}:{table}:1D",
                "source_code": LEGACY_SOURCE_CODE,
                "instrument_code": instrument,
                "source_symbol": None,
                "source_table": table,
                "timeframe": "1D",
                "mapping_role": "legacy_reference",
                "valid_from": row["first_date"],
                "valid_to": row["last_date"],
                "priority": 100,
                "mapping_status": "active",
                "notes": (
                    "Source table found in the original user-supplied MySQL dump. "
                    "Retained as legacy provenance; provider-level authority and "
                    "price equivalence have not been independently established."
                ),
                "metadata": {
                    "source_row_count": row["row_count"],
                    "composite_snapshot_batch_id": composite["id"],
                },
            }
        )

    for row in external:
        year = int(row["calendar_year"])
        table = f"nse_indices_historical_{year}"
        if table not in baseline["nse_table_names"]:
            raise RuntimeError(
                f"Expected raw provenance table {table!r} was not found in batch 2."
            )
        mappings.append(
            {
                "mapping_code": f"NSE:{row['instrument_code']}:{table}:1D",
                "source_code": NSE_SOURCE_CODE,
                "instrument_code": row["instrument_code"],
                "source_symbol": row["source_index_name"],
                "source_table": table,
                "timeframe": "1D",
                "mapping_role": "preferred_for_period",
                "valid_from": f"{year}-01-01",
                "valid_to": f"{year}-12-31",
                "priority": 10,
                "mapping_status": "active",
                "notes": (
                    "NSE Indices historical-data CSV staged and promoted into "
                    "composite snapshot batch 2 for this calendar year. "
                    "Preferred for this period; legacy source records remain preserved."
                ),
                "metadata": {
                    "external_source_batch_id": row["id"],
                    "source_filename": row["source_filename"],
                    "source_sha256": row["source_sha256"],
                    "source_row_count": row["source_row_count"],
                },
            }
        )

    return {
        "legacy_metadata": legacy_metadata,
        "nse_metadata": nse_metadata,
        "mappings": mappings,
        "external_batches": external,
        "legacy_tables": baseline["legacy_tables"],
        "composite_batch_id": composite["id"],
        "legacy_batch_id": legacy["id"],
    }


def print_plan(plan: dict[str, Any]) -> None:
    print("\nHISTORICAL SOURCE REGISTRY INITIALIZATION")
    print("=" * 78)
    print(f"Database: {DATABASE}")
    print("Mode: APPLY" if APPLY_MODE else "Mode: DRY RUN (read-only)")
    print("\nDISCOVERED SOURCES")
    print("-" * 78)
    print("1. Legacy MySQL dump")
    print(f"   Original import batch: {plan['legacy_batch_id']}")
    print(f"   Source SHA-256: {plan['legacy_metadata']['source_sha256']}")
    print(f"   Instrument/table mappings: {len(plan['legacy_tables'])}")
    print("2. NSE Indices historical data")
    print(f"   External source files: {len(plan['external_batches'])}")
    for row in plan["external_batches"]:
        print(
            f"   - {row['calendar_year']}: {row['source_filename']} | "
            f"{row['source_row_count']} rows | batch {row['id']}"
        )

    roles: dict[str, int] = {}
    for mapping in plan["mappings"]:
        roles[mapping["mapping_role"]] = roles.get(mapping["mapping_role"], 0) + 1
    print("\nREGISTRY MAPPINGS")
    print("-" * 78)
    for role, count in sorted(roles.items()):
        print(f"{role}: {count}")
    print(f"Total instrument/source mappings: {len(plan['mappings'])}")
    print("New registry tables: 3")
    print("Existing historical price, quality and aggregate tables: unchanged")


def create_schema(connection: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS historical_data_sources (
            source_code TEXT PRIMARY KEY,
            provider_name TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (
                source_type IN (
                    'database_dump',
                    'official_exchange_portal',
                    'broker_api',
                    'vendor_api',
                    'manual_file',
                    'other'
                )
            ),
            authority_level TEXT NOT NULL,
            source_url TEXT,
            data_format TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            description TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS historical_instrument_source_mappings (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mapping_code TEXT NOT NULL UNIQUE,
            source_code TEXT NOT NULL,
            instrument_code TEXT NOT NULL,
            source_symbol TEXT,
            source_table TEXT,
            timeframe TEXT NOT NULL,
            mapping_role TEXT NOT NULL CHECK (
                mapping_role IN (
                    'legacy_reference',
                    'preferred_for_period',
                    'fallback_reference',
                    'supplemental',
                    'pending_review'
                )
            ),
            valid_from TEXT,
            valid_to TEXT,
            priority INTEGER NOT NULL DEFAULT 100,
            mapping_status TEXT NOT NULL DEFAULT 'active' CHECK (
                mapping_status IN ('active', 'inactive', 'pending_review')
            ),
            notes TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            FOREIGN KEY (source_code)
                REFERENCES historical_data_sources(source_code),
            CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS historical_source_batch_links (
            link_code TEXT PRIMARY KEY,
            source_code TEXT NOT NULL,
            import_batch_id INTEGER,
            external_source_batch_id INTEGER,
            link_role TEXT NOT NULL CHECK (
                link_role IN (
                    'original_import',
                    'staged_external_file',
                    'contributed_to_snapshot'
                )
            ),
            notes TEXT,
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (source_code)
                REFERENCES historical_data_sources(source_code),
            FOREIGN KEY (import_batch_id)
                REFERENCES import_batches(id),
            FOREIGN KEY (external_source_batch_id)
                REFERENCES external_index_source_batches(id),
            CHECK (import_batch_id IS NOT NULL OR external_source_batch_id IS NOT NULL)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_historical_source_mapping_instrument
            ON historical_instrument_source_mappings (
                instrument_code, timeframe, mapping_status, priority
            )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_historical_source_mapping_period
            ON historical_instrument_source_mappings (
                instrument_code, valid_from, valid_to
            )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_historical_source_links_source
            ON historical_source_batch_links (source_code)
        """,
    ]
    for statement in statements:
        connection.execute(statement)


def upsert_source(
    connection: sqlite3.Connection,
    source_code: str,
    provider_name: str,
    source_type: str,
    authority_level: str,
    source_url: str | None,
    data_format: str,
    description: str,
    metadata: dict[str, Any],
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO historical_data_sources (
            source_code, provider_name, source_type, authority_level,
            source_url, data_format, timezone, description, metadata_json,
            is_active, created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, 'Asia/Kolkata', ?, ?, 1, ?, ?)
        ON CONFLICT(source_code) DO UPDATE SET
            provider_name = excluded.provider_name,
            source_type = excluded.source_type,
            authority_level = excluded.authority_level,
            source_url = excluded.source_url,
            data_format = excluded.data_format,
            description = excluded.description,
            metadata_json = excluded.metadata_json,
            is_active = 1,
            updated_at_utc = excluded.updated_at_utc
        """,
        (
            source_code,
            provider_name,
            source_type,
            authority_level,
            source_url,
            data_format,
            description,
            json.dumps(metadata, sort_keys=True),
            now,
            now,
        ),
    )


def upsert_mapping(
    connection: sqlite3.Connection,
    mapping: dict[str, Any],
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO historical_instrument_source_mappings (
            mapping_code, source_code, instrument_code, source_symbol,
            source_table, timeframe, mapping_role, valid_from, valid_to,
            priority, mapping_status, notes, metadata_json,
            created_at_utc, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mapping_code) DO UPDATE SET
            source_code = excluded.source_code,
            instrument_code = excluded.instrument_code,
            source_symbol = excluded.source_symbol,
            source_table = excluded.source_table,
            timeframe = excluded.timeframe,
            mapping_role = excluded.mapping_role,
            valid_from = excluded.valid_from,
            valid_to = excluded.valid_to,
            priority = excluded.priority,
            mapping_status = excluded.mapping_status,
            notes = excluded.notes,
            metadata_json = excluded.metadata_json,
            updated_at_utc = excluded.updated_at_utc
        """,
        (
            mapping["mapping_code"],
            mapping["source_code"],
            mapping["instrument_code"],
            mapping["source_symbol"],
            mapping["source_table"],
            mapping["timeframe"],
            mapping["mapping_role"],
            mapping["valid_from"],
            mapping["valid_to"],
            mapping["priority"],
            mapping["mapping_status"],
            mapping["notes"],
            json.dumps(mapping["metadata"], sort_keys=True),
            now,
            now,
        ),
    )


def upsert_link(
    connection: sqlite3.Connection,
    link_code: str,
    source_code: str,
    import_batch_id: int | None,
    external_batch_id: int | None,
    link_role: str,
    notes: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO historical_source_batch_links (
            link_code, source_code, import_batch_id,
            external_source_batch_id, link_role, notes, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_code) DO UPDATE SET
            source_code = excluded.source_code,
            import_batch_id = excluded.import_batch_id,
            external_source_batch_id = excluded.external_source_batch_id,
            link_role = excluded.link_role,
            notes = excluded.notes
        """,
        (
            link_code,
            source_code,
            import_batch_id,
            external_batch_id,
            link_role,
            notes,
            now,
        ),
    )


def apply_registry(path: Path, plan: dict[str, Any]) -> None:
    connection = sqlite3.connect(path, timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        create_schema(connection)
        now = utc_now()

        upsert_source(
            connection,
            LEGACY_SOURCE_CODE,
            "User-supplied MySQL historical dump (fnodatabase)",
            "database_dump",
            "legacy_source_unverified",
            None,
            "MySQL 8 SQL dump",
            (
                "Original user-supplied historical SQL dump. Retained as legacy "
                "provenance. Data quality was assessed during ingestion, but "
                "the upstream vendor/provider and all historical values have "
                "not been independently verified."
            ),
            plan["legacy_metadata"],
            now,
        )

        upsert_source(
            connection,
            NSE_SOURCE_CODE,
            "NSE Indices",
            "official_exchange_portal",
            "official_primary_source_download",
            "https://www.niftyindices.com/reports/historical-data",
            "CSV",
            (
                "Historical index OHLC CSV files downloaded from the NSE Indices "
                "historical-data portal. The staged examples currently cover "
                "NIFTY BANK for 2015 and 2016."
            ),
            plan["nse_metadata"],
            now,
        )

        for mapping in plan["mappings"]:
            upsert_mapping(connection, mapping, now)

        # Connect the legacy provider to its original import and the composite snapshot.
        upsert_link(
            connection,
            "LEGACY:IMPORT:1:ORIGINAL",
            LEGACY_SOURCE_CODE,
            plan["legacy_batch_id"],
            None,
            "original_import",
            "Original SQL dump import; source records remain preserved in batch 1.",
            now,
        )
        upsert_link(
            connection,
            f"LEGACY:IMPORT:{plan['composite_batch_id']}:CONTRIBUTION",
            LEGACY_SOURCE_CODE,
            plan["composite_batch_id"],
            None,
            "contributed_to_snapshot",
            "Legacy-source records outside the explicitly replaced BANKNIFTY 2015–2016 period contribute to composite snapshot batch 2.",
            now,
        )

        for external in plan["external_batches"]:
            external_id = int(external["id"])
            upsert_link(
                connection,
                f"NSE:EXTERNAL:{external_id}:STAGED",
                NSE_SOURCE_CODE,
                None,
                external_id,
                "staged_external_file",
                f"Staged NSE Indices CSV file: {external['source_filename']}.",
                now,
            )
            upsert_link(
                connection,
                f"NSE:SNAPSHOT:{plan['composite_batch_id']}:EXTERNAL:{external_id}",
                NSE_SOURCE_CODE,
                plan["composite_batch_id"],
                external_id,
                "contributed_to_snapshot",
                f"NSE external source batch {external_id} contributed to composite snapshot batch {plan['composite_batch_id']}.",
                now,
            )

        # Validate registry content and all existing foreign keys before commit.
        source_count = connection.execute(
            "SELECT COUNT(*) FROM historical_data_sources"
        ).fetchone()[0]
        mapping_count = connection.execute(
            "SELECT COUNT(*) FROM historical_instrument_source_mappings"
        ).fetchone()[0]
        link_count = connection.execute(
            "SELECT COUNT(*) FROM historical_source_batch_links"
        ).fetchone()[0]
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

        if source_count < 2:
            raise RuntimeError("Registry validation failed: fewer than 2 sources.")
        if mapping_count < len(plan["mappings"]):
            raise RuntimeError("Registry validation failed: source mappings are missing.")
        if link_count < 4:
            raise RuntimeError("Registry validation failed: source links are missing.")
        if fk_errors:
            raise RuntimeError(f"Foreign-key validation failed: {fk_errors[:5]}")
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        connection.commit()

        print("\nREGISTRY INITIALIZATION COMMITTED")
        print("=" * 78)
        print(f"Sources: {source_count}")
        print(f"Instrument/source mappings: {mapping_count}")
        print(f"Source-to-batch links: {link_count}")
        print(f"SQLite integrity: {integrity}")
        print(f"Foreign-key errors: {len(fk_errors)}")
        print("Historical price/quality/aggregate tables: not modified")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


APPLY_MODE = False


def main() -> int:
    global APPLY_MODE

    parser = argparse.ArgumentParser(
        description="Initialize a generic historical data source registry."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create and populate registry tables. Without this flag, run read-only preview.",
    )
    args = parser.parse_args()
    APPLY_MODE = args.apply

    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)

    read_connection = connect_readonly(DATABASE)
    try:
        baseline = load_baseline(read_connection)
    finally:
        read_connection.close()

    plan = build_plan(baseline)
    print_plan(plan)

    if not APPLY_MODE:
        print("\nDry run completed. No tables or records were changed.")
        print("Review this plan, then rerun with --apply to initialize the registry.")
        return 0

    apply_registry(DATABASE, plan)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise
