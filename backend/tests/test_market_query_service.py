from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine, delete
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.index import Index
from app.models.historical import (
    HistoricalSnapshot,
    HistoricalRawRecord,
    DailyOHLCV,
)
from app.services.market_query_service import get_market_history


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(element, compiler, **kw):
    return "JSON"


class TestMarketHistoryQueryService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
        )

        Base.metadata.create_all(
            cls.engine,
            tables=[
                Index.__table__,
                HistoricalSnapshot.__table__,
                HistoricalRawRecord.__table__,
                DailyOHLCV.__table__,
            ],
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.db = self.SessionLocal()
        self.seed_database()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def seed_database(self):
        self.db.execute(delete(DailyOHLCV))
        self.db.execute(delete(HistoricalRawRecord))
        self.db.execute(delete(HistoricalSnapshot))
        self.db.execute(delete(Index))
        self.db.flush()

        self.db.add(
            Index(
                id=1,
                code="NIFTY50",
                name="Nifty 50",
                exchange="NSE",
                category="market_index",
                is_active=True,
                display_order=1,
            )
        )

        self.db.add(
            HistoricalSnapshot(
                id=5,
                source_path="test_source",
                source_sha256="a" * 64,
                source_size_bytes=100,
                status="completed",
                imported_rows=5,
                imported_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

        self.db.flush()

        for day in range(1, 6):
            raw_id = 100 + day
            candle_date = date(2026, 1, day)

            self.db.add(
                HistoricalRawRecord(
                    id=raw_id,
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    source_table="nifty50_1d",
                    source_row_number=day,
                    source_id=str(day),
                )
            )

            self.db.add(
                DailyOHLCV(
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    candle_date=candle_date,
                    open=Decimal("100.00") + day,
                    high=Decimal("110.00") + day,
                    low=Decimal("95.00") + day,
                    close=Decimal("105.00") + day,
                    volume=1000 + day,
                    volume_status="available",
                    raw_record_id=raw_id,
                    source_table="nifty50_1d",
                    quality_status="valid",
                    issue_codes=[],
                )
            )

        self.db.commit()

    def get_dates(self, result):
        return [record.candle_date for record in result.records]

    def test_default_sort_order_is_ascending(self):
        result = get_market_history(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
        )

        self.assertEqual(
            self.get_dates(result),
            [
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 4),
                date(2026, 1, 5),
            ],
        )

    def test_descending_sort_order_returns_latest_first(self):
        result = get_market_history(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            sort_order="desc",
        )

        self.assertEqual(
            self.get_dates(result),
            [
                date(2026, 1, 5),
                date(2026, 1, 4),
                date(2026, 1, 3),
                date(2026, 1, 2),
                date(2026, 1, 1),
            ],
        )

    def test_ascending_pagination_preserves_chronological_order(self):
        result = get_market_history(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            limit=2,
            offset=2,
        )

        self.assertEqual(
            self.get_dates(result),
            [
                date(2026, 1, 3),
                date(2026, 1, 4),
            ],
        )

        self.assertEqual(result.pagination.total_records, 5)

    def test_descending_pagination_preserves_reverse_order(self):
        result = get_market_history(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            sort_order="desc",
            limit=2,
            offset=2,
        )

        self.assertEqual(
            self.get_dates(result),
            [
                date(2026, 1, 3),
                date(2026, 1, 2),
            ],
        )

        self.assertEqual(result.pagination.total_records, 5)


if __name__ == "__main__":
    unittest.main()
