#!/usr/bin/env python3
"""Initialize a persistent, non-destructive historical quality annotation register.

Default mode is dry-run. Use --apply to create/update only the annotation table.
No raw, quality, curated daily, calendar, or aggregate data is modified.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "backend" / "data" / "historical_staging.db"
BACKUP_DIR = ROOT / "backend" / "data" / "backups"

# These records annotate known context. They do not invalidate or suppress
# the original unusual_daily_close_return audit finding.
MARKET_EVENT_ANNOTATIONS = [
    {
        "annotation_code": "MARKET_EVENT:SENSEX:2009-05-18:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "SENSEX",
        "candle_date": "2009-05-18",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_context_value_still_requires_source_reconciliation",
        "review_status": "context_documented_not_suppressed",
        "event_title": "Election-result rally and market-wide circuit breakers",
        "description": (
            "Contemporaneous reporting documents an exceptional post-election rally "
            "and circuit-breaker trading halt on both NSE and BSE. The article's "
            "reported percentage is not an exact match to the database return; "
            "this annotation supplies context only and does not validate the exact candle value."
        ),
        "evidence_title": "Sensex Hits Upper Circuit",
        "evidence_url": "https://www.valueresearchonline.com/stories/100231/sensex-hits-upper-circuit/",
        "evidence_published_date": "2009-05-18",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Keep the original unusual-return finding visible; verify exact OHLC against an authoritative historical source if needed.",
    },
    {
        "annotation_code": "MARKET_EVENT:INDIA_VIX:2015-08-24:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2015-08-24",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_context_value_still_requires_source_reconciliation",
        "review_status": "context_documented_not_suppressed",
        "event_title": "Global sell-off and sharp India VIX surge",
        "description": (
            "Contemporaneous reporting describes a sharp India VIX increase of roughly 64% "
            "during the global market sell-off. Reported intraday/closing descriptions may "
            "not be identical to the database's close-to-close calculation; context only."
        ),
        "evidence_title": "5 reasons why the Sensex tanked 1,624 points on Monday",
        "evidence_url": "https://www.business-standard.com/article/markets/5-reasons-why-the-sensex-tanked-1-100-points-on-monday-115082400312_1.html",
        "evidence_published_date": "2015-08-24",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Do not treat a reported intraday high as the official daily close return.",
    },
    {
        "annotation_code": "MARKET_EVENT:BANKNIFTY:2020-03-23:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "BANKNIFTY",
        "candle_date": "2020-03-23",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_event_index_move_reported",
        "review_status": "context_documented_not_suppressed",
        "event_title": "COVID-19 market sell-off and circuit-breaker session",
        "description": (
            "Contemporaneous market reporting specifically records a 16.73% fall in Nifty Bank "
            "on this date. This corroborates the exceptional direction and scale of the move, "
            "but is not a substitute for independent OHLC source verification."
        ),
        "evidence_title": "Nifty Bank index suffers biggest single-day loss",
        "evidence_url": "https://www.moneycontrol.com/news/business/markets/nifty-bank-index-suffers-biggest-single-day-loss-may-continue-correction-toward-16000-15500-levels-5062661.html",
        "evidence_published_date": "2020-03-23",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Keep the underlying return alert in the audit output as documented context, not as a suppressed issue.",
    },
    {
        "annotation_code": "MARKET_EVENT:FINNIFTY:2020-03-23:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "FINNIFTY",
        "candle_date": "2020-03-23",
        "issue_code": "unusual_daily_close_return",
        "classification": "broad_market_context_only_index_lineage_requires_review",
        "review_status": "context_only_index_lineage_unverified",
        "event_title": "COVID-19 market sell-off and circuit-breaker session",
        "description": (
            "Broad market reports document an exceptional market-wide sell-off on this date. "
            "This source does not independently verify the historical FINNIFTY series value "
            "or its methodology/lineage for 2020; retain the anomaly for instrument-level review."
        ),
        "evidence_title": "Stock markets post worst losses in history; Sensex crashes 3,935 points",
        "evidence_url": "https://indianexpress.com/article/business/market/bse-sensex-nse-nifty-stock-market-live-updates-coronavirus-global-markets-6327415/",
        "evidence_published_date": "2020-03-23",
        "evidence_level": "secondary_market_wide_context",
        "notes": "Do not mark FINNIFTY's historical value as independently verified by this broad-market article.",
    },
    {
        "annotation_code": "MARKET_EVENT:NIFTY50:2020-03-23:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "NIFTY50",
        "candle_date": "2020-03-23",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_event_index_move_reported",
        "review_status": "context_documented_not_suppressed",
        "event_title": "COVID-19 market sell-off and circuit-breaker session",
        "description": (
            "Contemporaneous reporting records the Nifty 50 falling approximately 12.98% "
            "and describes the market-wide circuit-breaker session. This is event context, "
            "not a replacement for source-level OHLC verification."
        ),
        "evidence_title": "Stock markets post worst losses in history; Sensex crashes 3,935 points",
        "evidence_url": "https://indianexpress.com/article/business/market/bse-sensex-nse-nifty-stock-market-live-updates-coronavirus-global-markets-6327415/",
        "evidence_published_date": "2020-03-23",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Keep the underlying return alert in the audit output as documented context, not as a suppressed issue.",
    },
    {
        "annotation_code": "MARKET_EVENT:SENSEX:2020-03-23:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "SENSEX",
        "candle_date": "2020-03-23",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_event_index_move_reported",
        "review_status": "context_documented_not_suppressed",
        "event_title": "COVID-19 market sell-off and circuit-breaker session",
        "description": (
            "Contemporaneous reporting records the Sensex falling approximately 13.15% "
            "and describes the market-wide circuit-breaker session. This is event context, "
            "not a replacement for source-level OHLC verification."
        ),
        "evidence_title": "Stock markets post worst losses in history; Sensex crashes 3,935 points",
        "evidence_url": "https://indianexpress.com/article/business/market/bse-sensex-nse-nifty-stock-market-live-updates-coronavirus-global-markets-6327415/",
        "evidence_published_date": "2020-03-23",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Keep the underlying return alert in the audit output as documented context, not as a suppressed issue.",
    },
    {
        "annotation_code": "MARKET_EVENT:INDIA_VIX:2024-08-05:UNUSUAL_RETURN",
        "annotation_type": "market_event_context",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2024-08-05",
        "issue_code": "unusual_daily_close_return",
        "classification": "documented_market_context_value_still_requires_source_reconciliation",
        "review_status": "context_documented_not_suppressed",
        "event_title": "Global sell-off and sharp India VIX surge",
        "description": (
            "Contemporaneous reporting records India VIX ending approximately 42.33% higher "
            "during a global market sell-off. This corroborates the exceptional move, while "
            "the exact source close and return calculation remain subject to source reconciliation."
        ),
        "evidence_title": "Market mayhem: Vix up 42%, signals more turmoil in domestic markets",
        "evidence_url": "https://www.business-standard.com/amp/markets/stock-market-news/india-vix-surges-42-signals-more-turbulence-in-domestic-markets-124080501071_1.html",
        "evidence_published_date": "2024-08-05",
        "evidence_level": "secondary_contemporaneous_reporting",
        "notes": "Keep the underlying return alert in the audit output as documented context, not as a suppressed issue.",
    },
]

DUPLICATE_ANNOTATIONS = [
    {
        "annotation_code": "DUPLICATE:INDIA_VIX:2015-12-31:RAW_DATE_GROUP",
        "annotation_type": "duplicate_group_resolution",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2015-12-31",
        "issue_code": "duplicate_raw_instrument_date",
        "classification": "exact_duplicate_canonical_retained_extra_quarantined",
        "review_status": "resolved_exact_duplicate",
        "event_title": "Exact duplicate raw daily record",
        "description": "Both raw rows have identical OHLC values. The canonical raw record remains accepted for close and full OHLC; the extra raw record remains quarantined.",
        "raw_record_ids": [24680, 24681],
        "canonical_raw_record_id": 24680,
        "evidence_title": "Internal raw-record and quality-assessment inspection",
        "evidence_url": None,
        "evidence_published_date": None,
        "evidence_level": "internal_database_review",
        "notes": "Both raw rows remain preserved; no raw data was deleted.",
    },
    {
        "annotation_code": "DUPLICATE:INDIA_VIX:2023-10-20:RAW_DATE_GROUP",
        "annotation_type": "duplicate_group_resolution",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2023-10-20",
        "issue_code": "duplicate_raw_instrument_date",
        "classification": "conflicting_duplicate_close_canonical_full_ohlc_excluded",
        "review_status": "partially_resolved_close_only",
        "event_title": "Conflicting duplicate OHLC records; close agrees",
        "description": "The two raw rows differ in Low (10.07 versus 10.08) but share Close 10.82. One deterministic canonical raw row is used for close series only; neither row is eligible for full OHLC analytics.",
        "raw_record_ids": [26664, 26665],
        "canonical_raw_record_id": 26664,
        "evidence_title": "Internal raw-record and quality-assessment inspection",
        "evidence_url": None,
        "evidence_published_date": None,
        "evidence_level": "internal_database_review",
        "notes": "Keep the full OHLC conflict open until an independent authoritative source resolves it.",
    },
    {
        "annotation_code": "DUPLICATE:INDIA_VIX:2023-11-03:RAW_DATE_GROUP",
        "annotation_type": "duplicate_group_resolution",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2023-11-03",
        "issue_code": "duplicate_raw_instrument_date",
        "classification": "conflicting_duplicate_close_canonical_full_ohlc_excluded",
        "review_status": "partially_resolved_close_only",
        "event_title": "Conflicting duplicate OHLC records; close agrees",
        "description": "The two raw rows differ in Open and High (11.07 versus 11.08) but share Close 10.88. One deterministic canonical raw row is used for close series only; neither row is eligible for full OHLC analytics.",
        "raw_record_ids": [26674, 26675],
        "canonical_raw_record_id": 26674,
        "evidence_title": "Internal raw-record and quality-assessment inspection",
        "evidence_url": None,
        "evidence_published_date": None,
        "evidence_level": "internal_database_review",
        "notes": "Keep the full OHLC conflict open until an independent authoritative source resolves it.",
    },
    {
        "annotation_code": "DUPLICATE:INDIA_VIX:2023-11-24:RAW_DATE_GROUP",
        "annotation_type": "duplicate_group_resolution",
        "instrument_code": "INDIA_VIX",
        "candle_date": "2023-11-24",
        "issue_code": "duplicate_raw_instrument_date",
        "classification": "conflicting_duplicate_close_canonical_full_ohlc_excluded",
        "review_status": "partially_resolved_close_only",
        "event_title": "Conflicting duplicate OHLC records; close agrees",
        "description": "The two raw rows differ in Open (11.31 versus 11.32) but share Close 11.33. One deterministic canonical raw row is used for close series only; neither row is eligible for full OHLC analytics.",
        "raw_record_ids": [26690, 26691],
        "canonical_raw_record_id": 26690,
        "evidence_title": "Internal raw-record and quality-assessment inspection",
        "evidence_url": None,
        "evidence_published_date": None,
        "evidence_level": "internal_database_review",
        "notes": "Keep the full OHLC conflict open until an independent authoritative source resolves it.",
    },
]

ALL_ANNOTATIONS = MARKET_EVENT_ANNOTATIONS + DUPLICATE_ANNOTATIONS

SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_quality_annotations (
    annotation_code TEXT PRIMARY KEY,
    annotation_type TEXT NOT NULL CHECK (
        annotation_type IN ('market_event_context', 'duplicate_group_resolution')
    ),
    instrument_code TEXT NOT NULL,
    candle_date TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    classification TEXT NOT NULL,
    review_status TEXT NOT NULL,
    event_title TEXT NOT NULL,
    description TEXT NOT NULL,
    raw_record_ids_json TEXT NOT NULL DEFAULT '[]',
    canonical_raw_record_id INTEGER,
    evidence_title TEXT,
    evidence_url TEXT,
    evidence_published_date TEXT,
    evidence_level TEXT NOT NULL,
    notes TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    FOREIGN KEY (canonical_raw_record_id) REFERENCES raw_daily_records(id),
    UNIQUE (annotation_type, instrument_code, candle_date, issue_code)
);
CREATE INDEX IF NOT EXISTS idx_quality_annotations_instrument_date
    ON historical_quality_annotations(instrument_code, candle_date);
CREATE INDEX IF NOT EXISTS idx_quality_annotations_issue_status
    ON historical_quality_annotations(issue_code, review_status);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_readonly() -> sqlite3.Connection:
    if not DATABASE.is_file():
        raise FileNotFoundError(DATABASE)
    return sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)


def validate_expected_rows(con: sqlite3.Connection) -> None:
    required = {
        "raw_daily_records",
        "daily_quality_assessments",
        "daily_close_series",
        "daily_ohlcv_analytical",
        "historical_data_sources",
        "historical_instrument_source_mappings",
        "historical_source_batch_links",
    }
    found = {
        row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(required - found)
    if missing:
        raise RuntimeError(f"Required tables are missing: {missing}")

    for item in MARKET_EVENT_ANNOTATIONS:
        exists = con.execute("""
            SELECT COUNT(*)
            FROM daily_close_series
            WHERE import_batch_id = 2
              AND instrument_code = ?
              AND candle_date = ?
        """, (item["instrument_code"], item["candle_date"])).fetchone()[0]
        if exists != 1:
            raise RuntimeError(
                f"Expected exactly one batch-2 close record for "
                f"{item['instrument_code']} {item['candle_date']}; found {exists}"
            )

    for item in DUPLICATE_ANNOTATIONS:
        ids = item["raw_record_ids"]
        rows = con.execute(f"""
            SELECT r.id, r.open_raw, r.high_raw, r.low_raw, r.close_raw,
                   q.record_status, q.close_eligible, q.full_ohlc_eligible,
                   CASE WHEN c.raw_record_id IS NULL THEN 0 ELSE 1 END AS in_close,
                   CASE WHEN o.raw_record_id IS NULL THEN 0 ELSE 1 END AS in_ohlc
            FROM raw_daily_records r
            LEFT JOIN daily_quality_assessments q ON q.raw_record_id = r.id
            LEFT JOIN daily_close_series c
              ON c.raw_record_id = r.id
             AND c.import_batch_id = 2
             AND c.instrument_code = 'INDIA_VIX'
            LEFT JOIN daily_ohlcv_analytical o
              ON o.raw_record_id = r.id
             AND o.import_batch_id = 2
             AND o.instrument_code = 'INDIA_VIX'
            WHERE r.id IN ({','.join('?' for _ in ids)})
            ORDER BY r.id
        """, ids).fetchall()
        if len(rows) != 2:
            raise RuntimeError(
                f"Expected raw record IDs {ids}; found {len(rows)} records"
            )
        if rows[0][0] != item["canonical_raw_record_id"]:
            raise RuntimeError(
                f"Unexpected canonical raw record for {item['candle_date']}"
            )
        if item["candle_date"] == "2015-12-31":
            if not (rows[0][5] == "accepted" and rows[0][6] == 1 and rows[0][7] == 1 and rows[0][8] == 1 and rows[0][9] == 1):
                raise RuntimeError("Exact duplicate canonical row no longer matches expected accepted policy")
            if not (rows[1][5] == "quarantined" and rows[1][6] == 0 and rows[1][7] == 0 and rows[1][8] == 0 and rows[1][9] == 0):
                raise RuntimeError("Exact duplicate extra row no longer matches expected quarantine policy")
        else:
            if not (rows[0][5] == "review_required" and rows[0][6] == 1 and rows[0][7] == 0 and rows[0][8] == 1 and rows[0][9] == 0):
                raise RuntimeError(f"Conflicting duplicate canonical row policy changed for {item['candle_date']}")
            if not (rows[1][5] == "review_required" and rows[1][6] == 0 and rows[1][7] == 0 and rows[1][8] == 0 and rows[1][9] == 0):
                raise RuntimeError(f"Conflicting duplicate alternate row policy changed for {item['candle_date']}")


def print_plan(existing_count: int | None) -> None:
    print("\nHISTORICAL QUALITY ANNOTATION REGISTER")
    print("=" * 82)
    print(f"Database: {DATABASE}")
    print("Mode: " + ("APPLY" if APPLY else "DRY RUN (read-only)"))
    print(f"Market-event context annotations: {len(MARKET_EVENT_ANNOTATIONS)}")
    print(f"Duplicate-group resolution annotations: {len(DUPLICATE_ANNOTATIONS)}")
    print(f"Total annotations: {len(ALL_ANNOTATIONS)}")
    print(f"Existing annotation rows: {existing_count if existing_count is not None else 0}")
    print("\nMARKET EVENT CONTEXT")
    for item in MARKET_EVENT_ANNOTATIONS:
        print(
            f"  {item['candle_date']} | {item['instrument_code']:<10} | "
            f"{item['review_status']} | {item['event_title']}"
        )
    print("\nDUPLICATE GROUP POLICY")
    for item in DUPLICATE_ANNOTATIONS:
        print(
            f"  {item['candle_date']} | raw IDs={item['raw_record_ids']} | "
            f"canonical={item['canonical_raw_record_id']} | {item['review_status']}"
        )
    print("\nSAFETY POLICY")
    print("  Original audit findings are not suppressed.")
    print("  Raw records, quality assessments, curated candles and aggregates are not changed.")
    print("  Market-event notes provide context, not proof of exact OHLC values.")
    print("  Conflicting duplicate OHLC groups remain excluded from full-OHLC analytics.")


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"historical_staging_before_quality_annotations_{stamp}.db"
    src = sqlite3.connect(DATABASE)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    # Verify backup integrity and expected current batch.
    check = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        batch2 = check.execute("SELECT COUNT(*) FROM raw_daily_records WHERE import_batch_id=2").fetchone()[0]
        if integrity != "ok" or batch2 != 20149:
            raise RuntimeError(f"Backup verification failed: integrity={integrity}, batch2_raw={batch2}")
    finally:
        check.close()
    return backup


def apply_annotations() -> None:
    backup = make_backup()
    print(f"\nVerified database backup: {backup}")
    con = sqlite3.connect(DATABASE, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")
        # Execute DDL statements individually so they remain inside this transaction.
        schema_statements = [
            """CREATE TABLE IF NOT EXISTS historical_quality_annotations (
                annotation_code TEXT PRIMARY KEY,
                annotation_type TEXT NOT NULL CHECK (
                    annotation_type IN ('market_event_context', 'duplicate_group_resolution')
                ),
                instrument_code TEXT NOT NULL,
                candle_date TEXT NOT NULL,
                issue_code TEXT NOT NULL,
                classification TEXT NOT NULL,
                review_status TEXT NOT NULL,
                event_title TEXT NOT NULL,
                description TEXT NOT NULL,
                raw_record_ids_json TEXT NOT NULL DEFAULT '[]',
                canonical_raw_record_id INTEGER,
                evidence_title TEXT,
                evidence_url TEXT,
                evidence_published_date TEXT,
                evidence_level TEXT NOT NULL,
                notes TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                FOREIGN KEY (canonical_raw_record_id) REFERENCES raw_daily_records(id),
                UNIQUE (annotation_type, instrument_code, candle_date, issue_code)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_quality_annotations_instrument_date
                ON historical_quality_annotations(instrument_code, candle_date)""",
            """CREATE INDEX IF NOT EXISTS idx_quality_annotations_issue_status
                ON historical_quality_annotations(issue_code, review_status)""",
        ]
        for statement in schema_statements:
            con.execute(statement)
        now = now_utc()
        sql = """
            INSERT INTO historical_quality_annotations (
                annotation_code, annotation_type, instrument_code, candle_date,
                issue_code, classification, review_status, event_title, description,
                raw_record_ids_json, canonical_raw_record_id, evidence_title,
                evidence_url, evidence_published_date, evidence_level, notes,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(annotation_code) DO UPDATE SET
                annotation_type=excluded.annotation_type,
                instrument_code=excluded.instrument_code,
                candle_date=excluded.candle_date,
                issue_code=excluded.issue_code,
                classification=excluded.classification,
                review_status=excluded.review_status,
                event_title=excluded.event_title,
                description=excluded.description,
                raw_record_ids_json=excluded.raw_record_ids_json,
                canonical_raw_record_id=excluded.canonical_raw_record_id,
                evidence_title=excluded.evidence_title,
                evidence_url=excluded.evidence_url,
                evidence_published_date=excluded.evidence_published_date,
                evidence_level=excluded.evidence_level,
                notes=excluded.notes,
                updated_at_utc=excluded.updated_at_utc
        """
        for item in ALL_ANNOTATIONS:
            con.execute(sql, (
                item["annotation_code"], item["annotation_type"],
                item["instrument_code"], item["candle_date"], item["issue_code"],
                item["classification"], item["review_status"], item["event_title"],
                item["description"], json.dumps(item.get("raw_record_ids", [])),
                item.get("canonical_raw_record_id"), item.get("evidence_title"),
                item.get("evidence_url"), item.get("evidence_published_date"),
                item["evidence_level"], item.get("notes"), now, now,
            ))
        count = con.execute("SELECT COUNT(*) FROM historical_quality_annotations").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Pre-commit integrity check failed: {integrity}; FK={len(fk_errors)}")
        con.commit()
        print("\nANNOTATION REGISTER COMMITTED")
        print("=" * 82)
        print("Rows in annotation register:", count)
        print("Rows inserted/updated this run:", len(ALL_ANNOTATIONS))
        print("SQLite integrity:", integrity)
        print("Foreign-key errors:", len(fk_errors))
        print("Backup:", backup)
        print("Historical prices / quality assessments / aggregates: unchanged")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    global APPLY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/update the annotation register")
    args = parser.parse_args()
    APPLY = args.apply

    con = connect_readonly()
    try:
        validate_expected_rows(con)
        existing = con.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='historical_quality_annotations'
        """).fetchone()[0]
        existing_count = None
        if existing:
            existing_count = con.execute(
                "SELECT COUNT(*) FROM historical_quality_annotations"
            ).fetchone()[0]
        print_plan(existing_count)
    finally:
        con.close()

    if not APPLY:
        print("\nDry run completed. No database changes were made.")
        print("Review the plan, then rerun with --apply to initialize the annotation register.")
        return 0

    apply_annotations()
    return 0


APPLY = False

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
