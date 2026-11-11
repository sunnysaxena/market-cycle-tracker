
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
    AggregatedOHLCV,
    DailyOHLCV,
    HistoricalRawRecord,
    HistoricalSnapshot,
    MarketCycleClassification,
)
from app.services.research_service import get_forward_returns_by_phase


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(element, compiler, **kw):
    return "JSON"


class TestResearchForwardReturns(unittest.TestCase):

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
        self.seed_database()

    def tearDown(self):
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
            HistoricalSnapshot(
                id=5,
                source_path="research_test",
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

    def add_classification(
        self,
        period_start,
        classification="MARKUP",
        timeframe="1D",
        period_end=None,
    ):
        self.db.add(
            MarketCycleClassification(
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end or period_start,
                cycle_classification=classification,
                rule_score=75,
                bandwidth_percentile=Decimal("50"),
                classification_basis="PRICE_TREND_RULES",
                evidence=[],
                missing_inputs=[],
                config_json={},
                calculation_version="research_test_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

    def add_daily(self, day, close, quality="accepted"):
        raw_id = int(day.strftime("%Y%m%d"))

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
                candle_date=day,
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=None,
                volume_status="unavailable",
                source_volume_raw=None,
                raw_record_id=raw_id,
                source_id=str(raw_id),
                source_table="nifty50_1d",
                quality_status=quality,
                issue_codes=[],
            )
        )

    def add_aggregate(
        self,
        timeframe,
        period_start,
        close,
        status="completed",
        alignment="aligned",
    ):
        suffix = {"1W": 1, "1M": 2, "1Y": 3}[timeframe]
        row_id = int(period_start.strftime("%Y%m%d")) * 10 + suffix

        self.db.add(
            AggregatedOHLCV(
                id=row_id,
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_start,
                first_session_date=period_start,
                last_session_date=period_start,
                open=Decimal(str(close)),
                high=Decimal(str(close)),
                low=Decimal(str(close)),
                close=Decimal(str(close)),
                volume=None,
                volume_status="unavailable",
                session_count=1,
                period_status=status,
                boundary_alignment_status=alignment,
                session_coverage_status="complete",
                aggregation_version="research_test_v1",
                generated_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            )
        )

    def test_daily_forward_returns_use_subsequent_eligible_closes(self):
        base = date(2026, 1, 1)

        for offset in range(21):
            self.add_daily(
                date.fromordinal(base.toordinal() + offset),
                100 + offset,
            )

        self.add_classification(base)

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        expected_returns = {
            1: 1.0,
            5: 5.0,
            10: 10.0,
            20: 20.0,
        }

        for horizon in markup.horizons:
            self.assertAlmostEqual(
                horizon.average_return_pct,
                expected_returns[horizon.horizon_candles],
                places=5,
            )
            self.assertEqual(horizon.sample_count, 1)
            self.assertEqual(horizon.unavailable_count, 0)

    def test_rejected_daily_candles_are_excluded(self):
        base = date(2026, 1, 1)

        self.add_daily(base, 100)
        self.add_daily(date(2026, 1, 2), 999, "rejected")
        self.add_daily(date(2026, 1, 3), 110)
        self.add_classification(base)

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        self.assertAlmostEqual(
            markup.horizons[0].average_return_pct,
            10.0,
            places=5,
        )

    def test_insufficient_data_phase_is_excluded(self):
        base = date(2026, 1, 1)

        self.add_daily(base, 100)
        self.add_daily(date(2026, 1, 2), 110)

        self.add_classification(
            base,
            classification="INSUFFICIENT_DATA",
        )

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
        )

        phase = next(
            item for item in result.phases
            if item.cycle_classification == "INSUFFICIENT_DATA"
        )

        self.assertEqual(phase.classified_candle_count, 1)
        self.assertTrue(phase.excluded_from_return_analysis)
        self.assertEqual(phase.horizons[0].sample_count, 0)
        self.assertIsNone(phase.horizons[0].average_return_pct)

    def test_missing_future_candles_are_counted(self):
        base = date(2026, 1, 1)

        self.add_daily(base, 100)
        self.add_daily(date(2026, 1, 2), 105)
        self.add_classification(base)

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        self.assertEqual(markup.horizons[0].sample_count, 1)
        self.assertEqual(markup.horizons[0].unavailable_count, 0)
        self.assertEqual(markup.horizons[1].sample_count, 0)
        self.assertEqual(markup.horizons[1].unavailable_count, 1)
        self.assertIsNone(markup.horizons[1].average_return_pct)

    def test_date_filter_keeps_future_candles_after_end_date(self):
        base = date(2026, 1, 1)

        for offset in range(6):
            self.add_daily(
                date.fromordinal(base.toordinal() + offset),
                100 + offset,
            )

        self.add_classification(base)

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            start_date=base,
            end_date=base,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        self.assertEqual(result.total_classifications, 1)
        self.assertEqual(markup.horizons[1].sample_count, 1)
        self.assertAlmostEqual(
            markup.horizons[1].average_return_pct,
            5.0,
            places=5,
        )

    def test_weekly_uses_completed_aligned_aggregates(self):
        starts = [
            date(2026, 1, 5),
            date(2026, 1, 12),
            date(2026, 1, 19),
        ]

        self.add_aggregate("1W", starts[0], 100)
        self.add_aggregate(
            "1W", starts[1], 999, status="partial"
        )
        self.add_aggregate("1W", starts[2], 110)

        self.add_classification(
            starts[0],
            timeframe="1W",
            period_end=date(2026, 1, 11),
        )

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1W",
            import_batch_id=5,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        self.assertAlmostEqual(
            markup.horizons[0].average_return_pct,
            10.0,
            places=5,
        )

    def test_unaligned_aggregates_are_excluded(self):
        first = date(2026, 1, 5)
        second = date(2026, 1, 12)

        self.add_aggregate("1W", first, 100)
        self.add_aggregate(
            "1W", second, 999, alignment="unaligned"
        )

        self.add_classification(
            first,
            timeframe="1W",
            period_end=date(2026, 1, 11),
        )

        self.db.commit()

        result = get_forward_returns_by_phase(
            self.db,
            instrument="NIFTY50",
            timeframe="1W",
            import_batch_id=5,
        )

        markup = next(
            phase for phase in result.phases
            if phase.cycle_classification == "MARKUP"
        )

        self.assertEqual(markup.horizons[0].sample_count, 0)
        self.assertEqual(markup.horizons[0].unavailable_count, 1)


if __name__ == "__main__":
    unittest.main()
