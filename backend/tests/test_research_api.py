
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
from app.api.v1.research import router as research_router
from app.core.database import Base, get_db
from app.models.index import Index
from app.models.historical import (
    AggregatedOHLCV,
    DailyOHLCV,
    HistoricalRawRecord,
    HistoricalSnapshot,
    MarketCycleClassification,
)
from app.services.api_errors import APIServiceError


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(element, compiler, **kw):
    return "JSON"


class TestResearchAPI(unittest.TestCase):

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
                AggregatedOHLCV.__table__,
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
            research_router,
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
        for model in (
            MarketCycleClassification,
            DailyOHLCV,
            AggregatedOHLCV,
            HistoricalRawRecord,
            HistoricalSnapshot,
            Index,
        ):
            self.db.execute(delete(model))

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
            Index(
                id=3,
                code="INACTIVE_INDEX",
                name="Inactive Index",
                exchange="NSE",
                category="market_index",
                is_active=False,
                display_order=3,
            ),
            HistoricalSnapshot(
                id=5,
                source_path="research_api_test",
                source_sha256="a" * 64,
                source_size_bytes=100,
                status="completed",
                imported_rows=100,
                imported_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            ),
        ])

        self.db.flush()

        # Six accepted daily candles, with steadily increasing closes.
        base = date(2026, 1, 1)

        for offset in range(6):
            candle_date = date.fromordinal(
                base.toordinal() + offset
            )
            close = Decimal(str(100 + offset))
            raw_id = int(candle_date.strftime("%Y%m%d"))

            self.db.add(
                HistoricalRawRecord(
                    id=raw_id,
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    source_table="nifty50_1d",
                    source_row_number=raw_id,
                    source_id=str(raw_id),
                )
            )

            self.db.add(
                DailyOHLCV(
                    import_batch_id=5,
                    instrument_code="NIFTY50",
                    candle_date=candle_date,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=None,
                    volume_status="unavailable",
                    source_volume_raw=None,
                    raw_record_id=raw_id,
                    source_id=str(raw_id),
                    source_table="nifty50_1d",
                    quality_status="accepted",
                    issue_codes=[],
                )
            )

        self.db.add(
            MarketCycleClassification(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe="1D",
                period_start=base,
                period_end=base,
                cycle_classification="MARKUP",
                rule_score=75,
                bandwidth_percentile=Decimal("50"),
                classification_basis="PRICE_TREND_RULES",
                evidence=["test evidence"],
                missing_inputs=[],
                config_json={},
                calculation_version="research_api_test_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

        self.db.flush()

    def test_forward_returns_endpoint_returns_expected_data(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()

        self.assertEqual(body["instrument_code"], "NIFTY50")
        self.assertEqual(body["timeframe"], "1D")
        self.assertEqual(body["batch"]["import_batch_id"], 5)
        self.assertEqual(body["total_classifications"], 1)
        self.assertEqual(body["eligible_classifications"], 1)
        self.assertEqual(body["availability_status"], "available")

        markup = next(
            phase for phase in body["phases"]
            if phase["cycle_classification"] == "MARKUP"
        )

        self.assertEqual(markup["classified_candle_count"], 1)

        horizons = {
            item["horizon_candles"]: item
            for item in markup["horizons"]
        }

        self.assertAlmostEqual(
            horizons[1]["average_return_pct"],
            1.0,
            places=5,
        )
        self.assertAlmostEqual(
            horizons[5]["average_return_pct"],
            5.0,
            places=5,
        )
        self.assertEqual(horizons[10]["sample_count"], 0)
        self.assertEqual(horizons[20]["sample_count"], 0)

    def test_date_filters_are_accepted(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
                "start_date": "2026-01-01",
                "end_date": "2026-01-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_classifications"], 1)

    def test_missing_timeframe_returns_422(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_timeframe_returns_422(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "5m",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_unsupported_instrument_returns_422(self):
        response = self.client.get(
            "/api/v1/research/INDIA_VIX/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "UNSUPPORTED_INSTRUMENT_CATEGORY",
        )

    def test_unknown_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/research/UNKNOWN_INDEX/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_inactive_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/research/INACTIVE_INDEX/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_unknown_batch_returns_404(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 99999,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "BATCH_NOT_FOUND",
        )

    def test_invalid_batch_id_returns_422(self):
        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 0,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_no_classifications_returns_no_data_status(self):
        self.db.execute(delete(MarketCycleClassification))
        self.db.flush()

        response = self.client.get(
            "/api/v1/research/NIFTY50/forward-returns",
            params={
                "timeframe": "1D",
                "import_batch_id": 5,
            },
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body["availability_status"], "no_data")
        self.assertEqual(body["total_classifications"], 0)
        self.assertEqual(body["eligible_classifications"], 0)


if __name__ == "__main__":
    unittest.main()
