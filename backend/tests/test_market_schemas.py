from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from app.schemas.market import (
    DailyHistoryRecord,
    AggregatedHistoryRecord,
    MarketHistoryResponse,
)


class TestMarketHistorySchemas(unittest.TestCase):

    def make_batch(self):
        return {
            "id": 5,
            "status": "completed",
            "imported_rows": 22609,
            "imported_at_utc": datetime(
                2026, 11, 1, 13, 38, 45,
                tzinfo=timezone.utc,
            ),
        }

    def test_daily_record_preserves_decimal_precision(self):
        record = DailyHistoryRecord(
            candle_date=date(2026, 10, 30),
            open=Decimal("23000.12345678"),
            high=Decimal("23100.12345678"),
            low=Decimal("22900.12345678"),
            close=Decimal("23050.12345678"),
            volume=None,
            volume_status="unavailable",
            quality_status="accepted",
            issue_codes=[],
        )

        data = record.model_dump(mode="json")

        self.assertEqual(
            data["close"],
            "23050.12345678",
        )
        self.assertIsNone(data["volume"])
        self.assertEqual(data["volume_status"], "unavailable")

    def test_aggregated_record_preserves_provisional_status(self):
        record = AggregatedHistoryRecord(
            timeframe="1W",
            period_start=date(2026, 10, 26),
            period_end=date(2026, 11, 1),
            first_session_date=date(2026, 10, 26),
            last_session_date=date(2026, 10, 30),
            open=Decimal("23000.00000000"),
            high=Decimal("23200.00000000"),
            low=Decimal("22900.00000000"),
            close=Decimal("23053.10000000"),
            volume=None,
            volume_status="unavailable",
            session_count=5,
            period_status="provisional",
            boundary_alignment_status="aligned",
            session_coverage_status="not_checked",
            aggregation_version="test_version",
            generated_at_utc=datetime(
                2026, 11, 2, tzinfo=timezone.utc
            ),
        )

        data = record.model_dump(mode="json")

        self.assertEqual(data["period_status"], "provisional")
        self.assertEqual(
            data["boundary_alignment_status"],
            "aligned",
        )
        self.assertEqual(
            data["session_coverage_status"],
            "not_checked",
        )
        self.assertEqual(data["close"], "23053.10000000")

    def test_market_history_response_with_daily_record(self):
        record = DailyHistoryRecord(
            candle_date=date(2026, 10, 30),
            open=Decimal("23000"),
            high=Decimal("23100"),
            low=Decimal("22900"),
            close=Decimal("23050"),
            volume=None,
            volume_status="unavailable",
            quality_status="accepted",
            issue_codes=[],
        )

        response = MarketHistoryResponse(
            instrument_code="NIFTY50",
            timeframe="1D",
            batch=self.make_batch(),
            records=[record],
            pagination={
                "limit": 500,
                "offset": 0,
                "returned_count": 1,
                "total_records": 1,
            },
            availability={
                "status": "available",
                "is_available": True,
                "record_count": 1,
                "latest_date": date(2026, 10, 30),
            },
        )

        data = response.model_dump(mode="json")

        self.assertEqual(data["batch"]["import_batch_id"], 5)
        self.assertEqual(data["instrument_code"], "NIFTY50")
        self.assertEqual(data["records"][0]["close"], "23050")

    def test_market_history_response_allows_empty_records(self):
        response = MarketHistoryResponse(
            instrument_code="NIFTY50",
            timeframe="1D",
            batch=self.make_batch(),
            records=[],
            pagination={
                "limit": 500,
                "offset": 0,
                "returned_count": 0,
                "total_records": 0,
            },
            availability={
                "status": "no_data",
                "is_available": False,
                "record_count": 0,
                "latest_date": None,
                "message": "No historical records are available.",
            },
        )

        self.assertEqual(response.records, [])
        self.assertFalse(response.availability.is_available)
        self.assertIsNone(response.availability.latest_date)

    def test_rejects_unsupported_timeframe(self):
        with self.assertRaises(Exception):
            MarketHistoryResponse(
                instrument_code="NIFTY50",
                timeframe="5M",
                batch=self.make_batch(),
                records=[],
                pagination={
                    "limit": 500,
                    "offset": 0,
                    "returned_count": 0,
                    "total_records": 0,
                },
                availability={
                    "status": "no_data",
                    "is_available": False,
                    "record_count": 0,
                },
            )


if __name__ == "__main__":
    unittest.main()