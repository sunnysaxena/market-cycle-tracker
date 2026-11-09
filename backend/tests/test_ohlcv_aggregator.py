
import unittest
from datetime import date

from app.engines.ohlcv_aggregator import (
    CandleValidationError,
    aggregate_all_timeframes,
    aggregate_daily_candles,
)


class TestOHLCVAggregator(unittest.TestCase):

    def setUp(self):
        self.records = [
            {
                "timestamp": "2026-03-30 00:00:00",
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 102,
                "volume": 10,
            },
            {
                "timestamp": "2026-03-31 00:00:00",
                "open": 102,
                "high": 108,
                "low": 101,
                "close": 107,
                "volume": 20,
            },
            {
                "timestamp": "2026-04-01 00:00:00",
                "open": 107,
                "high": 110,
                "low": 105,
                "close": 109,
                "volume": 30,
            },
        ]

    def test_weekly_aggregation(self):
        result = aggregate_daily_candles(
            self.records,
            "1W",
            as_of_date=date(2026, 4, 6),
        )

        self.assertEqual(len(result), 1)

        candle = result[0]

        self.assertEqual(candle.open, 100)
        self.assertEqual(candle.high, 110)
        self.assertEqual(candle.low, 98)
        self.assertEqual(candle.close, 109)
        self.assertEqual(candle.volume, 60)
        self.assertEqual(candle.session_count, 3)
        self.assertEqual(candle.period_status, "completed")

    def test_monthly_aggregation(self):
        result = aggregate_daily_candles(
            self.records,
            "1M",
            as_of_date=date(2026, 4, 2),
        )

        self.assertEqual(len(result), 2)

        march = result[0]
        april = result[1]

        self.assertEqual(march.period_start, date(2026, 3, 1))
        self.assertEqual(march.open, 100)
        self.assertEqual(march.close, 107)
        self.assertEqual(march.volume, 30)
        self.assertEqual(march.period_status, "completed")

        self.assertEqual(april.period_start, date(2026, 4, 1))
        self.assertEqual(april.open, 107)
        self.assertEqual(april.close, 109)
        self.assertEqual(april.period_status, "provisional")

    def test_calendar_year_aggregation(self):
        result = aggregate_daily_candles(
            self.records,
            "1Y",
            as_of_date=date(2027, 1, 1),
        )

        self.assertEqual(len(result), 1)

        candle = result[0]

        self.assertEqual(candle.period_start, date(2026, 1, 1))
        self.assertEqual(candle.period_end, date(2026, 12, 31))
        self.assertEqual(candle.open, 100)
        self.assertEqual(candle.high, 110)
        self.assertEqual(candle.low, 98)
        self.assertEqual(candle.close, 109)
        self.assertEqual(candle.volume, 60)
        self.assertEqual(candle.period_status, "completed")

    def test_incomplete_week_is_provisional(self):
        result = aggregate_daily_candles(
            self.records,
            "1W",
            as_of_date=date(2026, 4, 4),
        )

        self.assertEqual(
            result[0].period_status,
            "provisional",
        )

    def test_duplicate_daily_dates_are_rejected(self):
        duplicate_records = self.records + [self.records[0]]

        with self.assertRaises(CandleValidationError):
            aggregate_daily_candles(
                duplicate_records,
                "1W",
            )

    def test_invalid_ohlc_is_rejected(self):
        bad_records = [
            {
                "timestamp": "2026-04-01",
                "open": 100,
                "high": 90,
                "low": 95,
                "close": 98,
                "volume": 10,
            }
        ]

        with self.assertRaises(CandleValidationError):
            aggregate_daily_candles(
                bad_records,
                "1M",
            )

    def test_missing_volume_is_not_replaced_with_zero(self):
        records = [
            {
                "timestamp": "2026-03-30",
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 102,
                "volume": 10,
            },
            {
                "timestamp": "2026-03-31",
                "open": 102,
                "high": 108,
                "low": 101,
                "close": 107,
                "volume": None,
            },
        ]

        result = aggregate_daily_candles(
            records,
            "1W",
            as_of_date=date(2026, 4, 6),
        )

        self.assertIsNone(result[0].volume)
        self.assertEqual(result[0].volume_status, "partial")

    def test_all_timeframes_are_generated(self):
        result = aggregate_all_timeframes(
            self.records,
            as_of_date=date(2027, 1, 1),
        )

        self.assertEqual(
            set(result.keys()),
            {"1W", "1M", "1Y"},
        )


    def test_all_zero_volume_is_unavailable(self):
        records = [
            {
                "timestamp": "2026-03-30",
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 102,
                "volume": 0,
            },
            {
                "timestamp": "2026-03-31",
                "open": 102,
                "high": 108,
                "low": 101,
                "close": 107,
                "volume": 0,
            },
        ]

        result = aggregate_daily_candles(
            records,
            "1W",
            as_of_date=date(2026, 4, 6),
        )

        self.assertIsNone(result[0].volume)
        self.assertEqual(
            result[0].volume_status,
            "unavailable",
        )


if __name__ == "__main__":
    unittest.main()
