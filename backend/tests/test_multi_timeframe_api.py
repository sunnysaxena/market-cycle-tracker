from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.exception_handlers import api_service_exception_handler
from app.api.v1.multi_timeframe import router as multi_timeframe_router
from app.core.database import Base, get_db
from app.models.index import Index
from app.models.historical import (
    HistoricalSnapshot,
    DailyOHLCV,
    AggregatedOHLCV,
    TechnicalIndicatorValue,
    MarketStructureSnapshot,
    MarketCycleClassification,
)
from app.services.api_errors import APIServiceError


class TestMultiTimeframeAPI(unittest.TestCase):

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
                DailyOHLCV.__table__,
                AggregatedOHLCV.__table__,
                TechnicalIndicatorValue.__table__,
                MarketStructureSnapshot.__table__,
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
            multi_timeframe_router,
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
        for model in (
            MarketCycleClassification,
            MarketStructureSnapshot,
            TechnicalIndicatorValue,
            DailyOHLCV,
            AggregatedOHLCV,
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
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

        self.db.flush()

        # Daily: two accepted records and one newer rejected record.
        self.add_daily(date(2026, 10, 29), "accepted")
        self.add_daily(date(2026, 10, 30), "accepted")
        self.add_daily(date(2026, 10, 31), "rejected")

        self.add_analytics(
            "1D",
            date(2026, 10, 30),
            date(2026, 10, 30),
            "ready",
        )

        # Weekly: two eligible records, plus newer ineligible records.
        self.add_aggregate(
            "1W", date(2026, 10, 12), date(2026, 10, 18)
        )
        self.add_aggregate(
            "1W", date(2026, 10, 19), date(2026, 10, 25)
        )
        self.add_aggregate(
            "1W", date(2026, 10, 26), date(2026, 11, 1),
            alignment="misaligned",
        )
        self.add_aggregate(
            "1W", date(2026, 11, 2), date(2026, 11, 8),
            status="incomplete",
        )

        self.add_analytics(
            "1W",
            date(2026, 10, 19),
            date(2026, 10, 25),
            "ready",
        )

        # Monthly: eligible October record and newer misaligned record.
        self.add_aggregate(
            "1M", date(2026, 9, 1), date(2026, 9, 30)
        )
        self.add_aggregate(
            "1M", date(2026, 10, 1), date(2026, 10, 31)
        )
        self.add_aggregate(
            "1M", date(2026, 11, 1), date(2026, 11, 30),
            alignment="misaligned",
        )

        self.add_analytics(
            "1M",
            date(2026, 10, 1),
            date(2026, 10, 31),
            "partial",
        )

        # Annual: a valid historical annual record with warming indicators.
        self.add_aggregate(
            "1Y", date(2025, 1, 1), date(2025, 12, 31)
        )

        self.add_analytics(
            "1Y",
            date(2025, 1, 1),
            date(2025, 12, 31),
            "warming_up",
            cycle_classification="INSUFFICIENT_DATA",
        )

        self.db.flush()

    def add_daily(self, candle_date, quality_status):
        self.db.add(
            DailyOHLCV(
                import_batch_id=5,
                instrument_code="NIFTY50",
                candle_date=candle_date,
                open=Decimal("22900"),
                high=Decimal("23100"),
                low=Decimal("22800"),
                close=Decimal("23000"),
                volume=None,
                volume_status="unavailable",
                source_volume_raw=None,
                raw_record_id=int(candle_date.strftime("%Y%m%d")),
                source_id="test",
                source_table="test_source",
                quality_status=quality_status,
                issue_codes=[],
            )
        )

    def add_aggregate(
        self,
        timeframe,
        period_start,
        period_end,
        status="completed",
        alignment="aligned",
    ):
        self.db.add(
            AggregatedOHLCV(
                id=int(
                    period_start.strftime("%Y%m%d")
                    + {"1W": "1", "1M": "2", "1Y": "3"}[timeframe]
                ),
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                first_session_date=period_start,
                last_session_date=period_end,
                open=Decimal("22900"),
                high=Decimal("23100"),
                low=Decimal("22800"),
                close=Decimal("23000"),
                volume=None,
                volume_status="unavailable",
                session_count=5,
                period_status=status,
                boundary_alignment_status=alignment,
                session_coverage_status="complete",
                aggregation_version="test_aggregation_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

    def add_analytics(
        self,
        timeframe,
        period_start,
        period_end,
        indicator_status,
        cycle_classification="TRANSITION_UNCERTAIN",
    ):
        source_table = (
            "daily_ohlcv" if timeframe == "1D"
            else "aggregated_ohlcv"
        )
        source_status = (
            "accepted" if timeframe == "1D"
            else "completed"
        )

        self.db.add(
            TechnicalIndicatorValue(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                source_table=source_table,
                source_status=source_status,
                boundary_alignment_status=(
                    None if timeframe == "1D" else "aligned"
                ),
                session_coverage_status=(
                    None if timeframe == "1D" else "complete"
                ),
                source_open=Decimal("22900"),
                source_high=Decimal("23100"),
                source_low=Decimal("22800"),
                source_close=Decimal("23000"),
                ema_9=Decimal("23010"),
                ema_20=Decimal("22990"),
                ema_50=None,
                ema_100=None,
                ema_200=None,
                sma_222=None,
                rsi_14=Decimal("55"),
                chop_14=None,
                bollinger_bandwidth_20_2=None,
                adx_14=Decimal("22"),
                plus_di_14=Decimal("25"),
                minus_di_14=Decimal("18"),
                macd_line_12_26=Decimal("10"),
                macd_signal_9=Decimal("8"),
                macd_histogram=Decimal("2"),
                atr_14=Decimal("100"),
                bollinger_upper_20_2=None,
                bollinger_middle_20_2=None,
                bollinger_lower_20_2=None,
                calculation_status=indicator_status,
                calculation_version="test_indicator_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

        self.db.add(
            MarketStructureSnapshot(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                source_close=Decimal("23000"),
                support_price=Decimal("22800"),
                support_pivot_date=period_start,
                support_confirmation_date=period_end,
                support_classification="HL",
                resistance_price=Decimal("23500"),
                resistance_pivot_date=period_start,
                resistance_confirmation_date=period_end,
                resistance_classification="HH",
                market_structure_state="BULLISH",
                breakout_status="NONE",
                range_position="WITHIN_SWING_RANGE",
                left_bars=3,
                right_bars=3,
                equal_tolerance_pct=Decimal("0.001"),
                calculation_version="test_structure_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

        self.db.add(
            MarketCycleClassification(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                cycle_classification=cycle_classification,
                rule_score=50,
                bandwidth_percentile=None,
                classification_basis="PRICE_TREND_RULES",
                evidence=["test evidence"],
                missing_inputs=(
                    ["EMA200"] if cycle_classification == "INSUFFICIENT_DATA"
                    else []
                ),
                config_json={},
                calculation_version="test_cycle_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

    def test_returns_latest_eligible_snapshot_for_all_timeframes(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body["instrument_code"], "NIFTY50")
        self.assertEqual(body["batch"]["import_batch_id"], 5)

        timeframes = body["timeframes"]
        self.assertEqual(set(timeframes), {"1D", "1W", "1M", "1Y"})

        self.assertEqual(
            timeframes["1D"]["period"]["period_start"],
            "2026-10-30",
        )
        self.assertEqual(
            timeframes["1W"]["period"]["period_start"],
            "2026-10-19",
        )
        self.assertEqual(
            timeframes["1M"]["period"]["period_start"],
            "2026-10-01",
        )
        self.assertEqual(
            timeframes["1Y"]["period"]["period_start"],
            "2025-01-01",
        )

        self.assertEqual(timeframes["1D"]["availability"]["status"], "available")
        self.assertEqual(timeframes["1W"]["availability"]["status"], "available")
        self.assertEqual(timeframes["1M"]["availability"]["status"], "partial")
        self.assertEqual(timeframes["1Y"]["availability"]["status"], "partial")

    def test_partial_and_warming_up_indicators_are_preserved(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 5},
        )

        body = response.json()
        monthly = body["timeframes"]["1M"]
        yearly = body["timeframes"]["1Y"]

        self.assertEqual(
            monthly["indicators"]["calculation"]["status"],
            "partial",
        )
        self.assertEqual(
            yearly["indicators"]["calculation"]["status"],
            "warming_up",
        )
        self.assertIsNone(
            monthly["indicators"]["moving_averages"]["sma_222"]
        )

        self.assertEqual(
            yearly["cycle"]["cycle_classification"],
            "INSUFFICIENT_DATA",
        )
        self.assertTrue(yearly["availability"]["cycle_available"])

    def test_missing_exact_key_indicator_is_not_joined(self):
        self.db.execute(
            delete(TechnicalIndicatorValue).where(
                TechnicalIndicatorValue.timeframe == "1D",
                TechnicalIndicatorValue.period_start == date(2026, 10, 30),
            )
        )
        self.db.flush()

        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 5},
        )

        daily = response.json()["timeframes"]["1D"]

        self.assertIsNone(daily["indicators"])
        self.assertFalse(daily["availability"]["indicator_available"])
        self.assertTrue(daily["availability"]["structure_available"])
        self.assertTrue(daily["availability"]["cycle_available"])
        self.assertEqual(daily["availability"]["status"], "partial")

    def test_no_data_timeframe_is_returned_without_error(self):
        self.db.execute(
            delete(AggregatedOHLCV).where(
                AggregatedOHLCV.timeframe == "1Y"
            )
        )
        self.db.flush()

        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 200)

        yearly = response.json()["timeframes"]["1Y"]
        self.assertEqual(yearly["availability"]["status"], "no_data")
        self.assertFalse(yearly["availability"]["is_available"])
        self.assertIsNone(yearly["period"])
        self.assertIsNone(yearly["market_data"])

    def test_automatic_batch_selection_uses_latest_completed_batch(self):
        self.db.add(
            HistoricalSnapshot(
                id=6,
                source_path="newer_test_source",
                source_sha256="c" * 64,
                source_size_bytes=100,
                status="completed",
                imported_rows=100,
                imported_at_utc=datetime(
                    2026, 11, 2, tzinfo=timezone.utc
                ),
            )
        )
        self.db.flush()

        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe"
        )

        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body["batch"]["import_batch_id"], 6)

        for timeframe in ("1D", "1W", "1M", "1Y"):
            self.assertEqual(
                body["timeframes"][timeframe]["availability"]["status"],
                "no_data",
            )

    def test_unsupported_instrument_category_returns_422(self):
        response = self.client.get(
            "/api/v1/market/INDIA_VIX/multi-timeframe",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "UNSUPPORTED_INSTRUMENT_CATEGORY",
        )

    def test_unknown_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/market/UNKNOWN_INDEX/multi-timeframe",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_inactive_instrument_returns_404(self):
        response = self.client.get(
            "/api/v1/market/INACTIVE_INDEX/multi-timeframe",
            params={"import_batch_id": 5},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "INSTRUMENT_NOT_FOUND",
        )

    def test_unknown_batch_returns_404(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 99999},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "BATCH_NOT_FOUND",
        )

    def test_invalid_batch_id_returns_422(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/multi-timeframe",
            params={"import_batch_id": 0},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
