from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.exception_handlers import api_service_exception_handler
from app.api.v1.structure import router as structure_router
from app.core.database import Base, get_db
from app.models.index import Index
from app.models.historical import (
    HistoricalSnapshot,
    MarketStructureSnapshot,
    MarketStructureEvent,
)
from app.services.api_errors import APIServiceError


class TestMarketStructureAPI(unittest.TestCase):

    TIMEFRAMES = ("1D", "1W", "1M", "1Y")

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

        # Create only the tables required by these API tests.
        Base.metadata.create_all(
            cls.engine,
            tables=[
                Index.__table__,
                HistoricalSnapshot.__table__,
                MarketStructureSnapshot.__table__,
                MarketStructureEvent.__table__,
            ],
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(
            structure_router,
            prefix="/api/v1",
        )
        self.app.add_exception_handler(
            APIServiceError,
            api_service_exception_handler,
        )

        def override_get_db():
            yield self.db

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

        self.seed_database()

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()
        self.db.rollback()
        self.db.close()

    def seed_database(self):
        # Clean shared in-memory SQLite tables before each test.
        self.db.execute(delete(MarketStructureEvent))
        self.db.execute(delete(MarketStructureSnapshot))
        self.db.execute(delete(HistoricalSnapshot))
        self.db.execute(delete(Index))
        self.db.flush()
        self.db.add_all([
            Index(
                id=1,
                code="NIFTY50",
                name="Nifty 50",
                exchange="NSE",
                category="market_index",
                is_active=True,
                display_order=1,
            ),
            Index(
                id=2,
                code="INDIA_VIX",
                name="India VIX",
                exchange="NSE",
                category="volatility_index",
                is_active=True,
                display_order=2,
            ),
        ])

        self.db.add(
            HistoricalSnapshot(
                id=5,
                source_path="test_source",
                source_sha256="a" * 64,
                source_size_bytes=100,
                status="completed",
                imported_rows=100,
                imported_at_utc=datetime(
                    2026, 11, 1, 13, 38, 45,
                    tzinfo=timezone.utc,
                ),
            )
        )

        self.db.add(
            HistoricalSnapshot(
                id=4,
                source_path="test_source_old",
                source_sha256="b" * 64,
                source_size_bytes=100,
                status="processing",
                imported_rows=50,
                imported_at_utc=datetime(
                    2026, 10, 31,
                    tzinfo=timezone.utc,
                ),
            )
        )

        self.db.flush()

        for index, timeframe in enumerate(self.TIMEFRAMES):
            start = date(2026, index + 1, 1)
            end = date(2026, index + 1, 28)

            self.db.add(
                MarketStructureSnapshot(
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    timeframe=timeframe,
                    period_start=start,
                    period_end=end,
                    source_close=Decimal("23050.12345678"),
                    support_price=Decimal("22800.12345678"),
                    support_pivot_date=start,
                    support_confirmation_date=end,
                    support_classification="HL",
                    resistance_price=Decimal("23500.12345678"),
                    resistance_pivot_date=start,
                    resistance_confirmation_date=end,
                    resistance_classification="HH",
                    market_structure_state="BULLISH",
                    breakout_status="NONE",
                    range_position="WITHIN_SWING_RANGE",
                    left_bars=3,
                    right_bars=3,
                    equal_tolerance_pct=Decimal("0.00100000"),
                    calculation_version="test_structure_v1",
                    generated_at_utc=datetime(
                        2026, 11, 1,
                        tzinfo=timezone.utc,
                    ),
                )
            )

            self.db.add(
                MarketStructureEvent(
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    timeframe=timeframe,
                    event_type="SWING_HIGH",
                    pivot_date=start,
                    pivot_period_end=end,
                    confirmation_date=end,
                    confirmation_period_end=end,
                    pivot_price=Decimal("23500.12345678"),
                    classification="HH",
                    left_bars=3,
                    right_bars=3,
                    equal_tolerance_pct=Decimal("0.00100000"),
                    calculation_version="test_structure_v1",
                    generated_at_utc=datetime(
                        2026, 11, 1,
                        tzinfo=timezone.utc,
                    ),
                )
            )

        # Additional daily records for filtering and pagination tests.
        self.db.add(
            MarketStructureSnapshot(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe="1D",
                period_start=date(2026, 10, 1),
                period_end=date(2026, 10, 1),
                source_close=Decimal("23100"),
                support_price=None,
                support_pivot_date=None,
                support_confirmation_date=None,
                support_classification=None,
                resistance_price=None,
                resistance_pivot_date=None,
                resistance_confirmation_date=None,
                resistance_classification=None,
                market_structure_state="INSUFFICIENT_DATA",
                breakout_status="NONE",
                range_position="INSUFFICIENT_LEVELS",
                left_bars=3,
                right_bars=3,
                equal_tolerance_pct=Decimal("0.00100000"),
                calculation_version="test_structure_v1",
                generated_at_utc=datetime(
                    2026, 11, 1,
                    tzinfo=timezone.utc,
                ),
            )
        )

        self.db.add(
            MarketStructureEvent(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe="1D",
                event_type="SWING_LOW",
                pivot_date=date(2026, 10, 5),
                pivot_period_end=date(2026, 10, 5),
                confirmation_date=date(2026, 10, 9),
                confirmation_period_end=date(2026, 10, 9),
                pivot_price=Decimal("22500"),
                classification="HL",
                left_bars=3,
                right_bars=3,
                equal_tolerance_pct=Decimal("0.00100000"),
                calculation_version="test_structure_v1",
                generated_at_utc=datetime(
                    2026, 11, 1,
                    tzinfo=timezone.utc,
                ),
            )
        )

        self.db.commit()

    def test_snapshot_endpoint_supports_all_timeframes(self):
        for timeframe in self.TIMEFRAMES:
            with self.subTest(timeframe=timeframe):
                response = self.client.get(
                    "/api/v1/market/NIFTY50/structure",
                    params={"timeframe": timeframe},
                )

                self.assertEqual(response.status_code, 200)

                data = response.json()

                self.assertEqual(data["instrument_code"], "NIFTY50")
                self.assertEqual(data["timeframe"], timeframe)
                self.assertEqual(data["batch"]["import_batch_id"], 5)
                expected_count = 2 if timeframe == "1D" else 1
                self.assertEqual(
                    data["pagination"]["returned_count"],
                    expected_count,
                )
                self.assertEqual(
                    data["records"][0]["calculation_version"],
                    "test_structure_v1",
                )

    def test_snapshot_preserves_decimal_precision(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={"timeframe": "1D"},
        )

        record = response.json()["records"][0]

        self.assertEqual(
            record["source_close"],
            "23050.12345678",
        )
        self.assertEqual(
            record["support"]["price"],
            "22800.12345678",
        )
        self.assertEqual(
            record["resistance"]["price"],
            "23500.12345678",
        )

    def test_snapshot_allows_null_support_and_resistance(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-01",
            },
        )

        record = response.json()["records"][0]

        self.assertIsNone(record["support"]["price"])
        self.assertIsNone(record["support"]["pivot_date"])
        self.assertIsNone(record["resistance"]["price"])
        self.assertIsNone(record["resistance"]["confirmation_date"])

    def test_snapshot_date_filter_uses_period_start(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-01",
                "end_date": "2026-10-01",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 1)
        self.assertEqual(
            data["records"][0]["period_start"],
            "2026-10-01",
        )

    def test_snapshot_pagination(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "limit": 1,
                "offset": 1,
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 2)
        self.assertEqual(data["pagination"]["returned_count"], 1)
        self.assertEqual(
            data["records"][0]["period_start"],
            "2026-10-01",
        )

    def test_snapshot_empty_range_reports_no_records_in_range(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["availability"]["status"],
            "no_records_in_range",
        )
        self.assertEqual(data["records"], [])

    def test_events_endpoint_supports_all_timeframes(self):
        for timeframe in self.TIMEFRAMES:
            with self.subTest(timeframe=timeframe):
                response = self.client.get(
                    "/api/v1/market/NIFTY50/structure/events",
                    params={"timeframe": timeframe},
                )

                self.assertEqual(response.status_code, 200)

                data = response.json()

                self.assertEqual(data["timeframe"], timeframe)
                self.assertEqual(
                    data["records"][0]["event_type"],
                    "SWING_HIGH",
                )

    def test_event_preserves_pivot_and_confirmation_dates(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={"timeframe": "1D"},
        )

        records = response.json()["records"]

        event = next(
            record
            for record in records
            if record["event_type"] == "SWING_LOW"
        )

        self.assertEqual(event["pivot_date"], "2026-10-05")
        self.assertEqual(event["confirmation_date"], "2026-10-09")
        self.assertEqual(event["classification"], "HL")
        self.assertEqual(event["pivot_price"], "22500.00000000")

    def test_event_type_filter(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "event_type": "SWING_HIGH",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            all(
                record["event_type"] == "SWING_HIGH"
                for record in data["records"]
            )
        )

    def test_event_classification_filter(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "classification": "HL",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 1)
        self.assertEqual(
            data["records"][0]["classification"],
            "HL",
        )

    def test_event_date_filter_uses_pivot_date(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-05",
                "end_date": "2026-10-05",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 1)
        self.assertEqual(
            data["records"][0]["pivot_date"],
            "2026-10-05",
        )

    def test_event_pagination(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "limit": 1,
                "offset": 1,
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 2)
        self.assertEqual(data["pagination"]["returned_count"], 1)

    def test_india_vix_events_returns_no_data(self):
        response = self.client.get(
            "/api/v1/market/INDIA_VIX/structure/events",
            params={"timeframe": "1D"},
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["records"], [])
        self.assertEqual(data["availability"]["status"], "no_data")

    def test_unknown_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/market/UNKNOWN/structure",
            params={"timeframe": "1D"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_unknown_batch_returns_404(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "import_batch_id": 999,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "BATCH_NOT_FOUND",
        )

    def test_non_completed_batch_returns_409(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "import_batch_id": 4,
            },
        )

        self.assertEqual(response.status_code, 409)

    def test_invalid_timeframe_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={"timeframe": "5M"},
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_event_type_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "event_type": "INVALID",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_classification_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "classification": "XX",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_date_range_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-31",
                "end_date": "2026-10-01",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_limit_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure",
            params={
                "timeframe": "1D",
                "limit": 2001,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_negative_offset_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/structure/events",
            params={
                "timeframe": "1D",
                "offset": -1,
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
