from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.exception_handlers import api_service_exception_handler
from app.api.v1.cycles import cycles_router
from app.core.database import Base, get_db
from app.models.index import Index
from app.models.historical import (
    HistoricalSnapshot,
    MarketCycleClassification,
)
from app.services.api_errors import APIServiceError


# Compile PostgreSQL JSONB columns as JSON for isolated SQLite tests.
@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(element, compiler, **kw):
    return "JSON"


class TestMarketCycleAPI(unittest.TestCase):

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

        Base.metadata.create_all(
            cls.engine,
            tables=[
                Index.__table__,
                HistoricalSnapshot.__table__,
                MarketCycleClassification.__table__,
            ],
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(
            cycles_router,
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
        self.db.execute(delete(MarketCycleClassification))
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

        self.db.add_all([
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
            ),
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
            ),
        ])

        self.db.flush()

        self.add_classification(
            timeframe="1D",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 1),
            classification="TRANSITION_UNCERTAIN",
            basis="MIXED_OR_INCOMPLETE_RULES",
            rule_score=35,
            percentile=Decimal("45.12345678"),
        )

        self.add_classification(
            timeframe="1D",
            period_start=date(2026, 1, 2),
            period_end=date(2026, 1, 2),
            classification="MARKUP",
            basis="PRICE_TREND_RULES",
            rule_score=80,
            percentile=Decimal("75.50000000"),
        )

        self.add_classification(
            timeframe="1D",
            period_start=date(2026, 1, 3),
            period_end=date(2026, 1, 3),
            classification="INSUFFICIENT_DATA",
            basis="INSUFFICIENT_INPUT",
            rule_score=0,
            percentile=None,
            missing_inputs=["adx_14", "ema_200"],
        )

        self.add_classification(
            timeframe="1D",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 1),
            classification="ACCUMULATION",
            basis="PRICE_ACTION_HEURISTIC",
            rule_score=65,
            percentile=Decimal("25.00000000"),
        )

        self.add_classification(
            timeframe="1W",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 7),
            classification="MARKUP",
            basis="PRICE_TREND_RULES",
            rule_score=75,
        )

        self.add_classification(
            timeframe="1M",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            classification="DISTRIBUTION",
            basis="PRICE_ACTION_HEURISTIC",
            rule_score=60,
        )

        self.add_classification(
            timeframe="1Y",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            classification="SIDEWAYS_CONSOLIDATION",
            basis="RANGE_AND_VOLATILITY_RULES",
            rule_score=70,
        )

        self.db.commit()

    def add_classification(
        self,
        timeframe,
        period_start,
        period_end,
        classification,
        basis,
        rule_score,
        percentile=Decimal("50.00000000"),
        missing_inputs=None,
    ):
        self.db.add(
            MarketCycleClassification(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                cycle_classification=classification,
                rule_score=rule_score,
                bandwidth_percentile=percentile,
                classification_basis=basis,
                evidence=["test_evidence_1", "test_evidence_2"],
                missing_inputs=missing_inputs or [],
                config_json={
                    "adx_weak": "20",
                    "adx_strong": "25",
                    "prior_trend_lookback": 20,
                },
                calculation_version="test_market_cycle_v1",
                generated_at_utc=datetime(
                    2026, 11, 1,
                    tzinfo=timezone.utc,
                ),
            )
        )

    def test_endpoint_supports_all_timeframes(self):
        for timeframe in self.TIMEFRAMES:
            with self.subTest(timeframe=timeframe):
                response = self.client.get(
                    "/api/v1/market/NIFTY50/cycles",
                    params={"timeframe": timeframe},
                )

                self.assertEqual(response.status_code, 200)

                data = response.json()

                self.assertEqual(data["instrument_code"], "NIFTY50")
                self.assertEqual(data["timeframe"], timeframe)
                self.assertEqual(data["batch"]["import_batch_id"], 5)
                expected_count = 4 if timeframe == "1D" else 1

                self.assertEqual(
                    data["pagination"]["returned_count"],
                    expected_count,
                )

    def test_response_contains_batch_metadata(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={"timeframe": "1D"},
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["batch"]["status"], "completed")
        self.assertEqual(data["batch"]["imported_rows"], 100)

    def test_response_preserves_json_fields(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "MARKUP",
            },
        )

        record = response.json()["records"][0]

        self.assertEqual(
            record["evidence"],
            ["test_evidence_1", "test_evidence_2"],
        )
        self.assertEqual(record["missing_inputs"], [])
        self.assertEqual(
            record["config_json"]["adx_weak"],
            "20",
        )
        self.assertEqual(
            record["config_json"]["prior_trend_lookback"],
            20,
        )

    def test_response_preserves_decimal_precision(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "TRANSITION_UNCERTAIN",
            },
        )

        record = response.json()["records"][0]

        self.assertEqual(
            record["bandwidth_percentile"],
            "45.12345678",
        )

    def test_response_allows_null_bandwidth_percentile(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "INSUFFICIENT_DATA",
            },
        )

        record = response.json()["records"][0]

        self.assertIsNone(record["bandwidth_percentile"])
        self.assertEqual(
            record["missing_inputs"],
            ["adx_14", "ema_200"],
        )

    def test_response_contains_calculation_metadata(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={"timeframe": "1D"},
        )

        record = response.json()["records"][0]

        self.assertEqual(
            record["calculation_version"],
            "test_market_cycle_v1",
        )
        self.assertIn("generated_at_utc", record)

    def test_classification_filter(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "MARKUP",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 1)
        self.assertEqual(
            data["records"][0]["cycle_classification"],
            "MARKUP",
        )

    def test_classification_basis_filter(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification_basis": "PRICE_ACTION_HEURISTIC",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 1)
        self.assertEqual(
            data["records"][0]["classification_basis"],
            "PRICE_ACTION_HEURISTIC",
        )

    def test_date_filter_uses_period_start(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "start_date": "2026-01-02",
                "end_date": "2026-01-03",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 2)
        self.assertEqual(
            data["records"][0]["period_start"],
            "2026-01-02",
        )
        self.assertEqual(
            data["records"][1]["period_start"],
            "2026-01-03",
        )

    def test_latest_date_uses_unfiltered_dataset(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "MARKUP",
            },
        )

        data = response.json()

        self.assertEqual(
            data["availability"]["latest_date"],
            "2026-10-01",
        )

    def test_pagination(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "limit": 1,
                "offset": 1,
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["pagination"]["total_records"], 4)
        self.assertEqual(data["pagination"]["returned_count"], 1)
        self.assertEqual(
            data["records"][0]["period_start"],
            "2026-01-02",
        )

    def test_empty_date_range_reports_no_records_in_range(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "start_date": "2035-01-01",
                "end_date": "2035-12-31",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["records"], [])
        self.assertEqual(
            data["availability"]["status"],
            "no_records_in_range",
        )
        self.assertEqual(
            data["availability"]["latest_date"],
            "2026-10-01",
        )

    def test_filter_with_no_matching_classification(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "DISTRIBUTION",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["records"], [])
        self.assertEqual(
            data["availability"]["status"],
            "no_records_in_range",
        )

    def test_india_vix_returns_no_data(self):
        response = self.client.get(
            "/api/v1/market/INDIA_VIX/cycles",
            params={"timeframe": "1D"},
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["records"], [])
        self.assertEqual(
            data["availability"]["status"],
            "no_data",
        )
        self.assertFalse(data["availability"]["is_available"])
        self.assertIsNone(data["availability"]["latest_date"])

    def test_unknown_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/market/UNKNOWN/cycles",
            params={"timeframe": "1D"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_unknown_batch_returns_404(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
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
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "import_batch_id": 4,
            },
        )

        self.assertEqual(response.status_code, 409)

    def test_invalid_timeframe_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={"timeframe": "5M"},
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_classification_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification": "INVALID",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_classification_basis_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "classification_basis": "INVALID",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_date_range_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-31",
                "end_date": "2026-10-01",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_limit_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "limit": 2001,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_negative_offset_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/cycles",
            params={
                "timeframe": "1D",
                "offset": -1,
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

