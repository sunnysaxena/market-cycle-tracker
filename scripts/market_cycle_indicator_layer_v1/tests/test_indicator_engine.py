import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.engines.indicator_engine import (
    CALCULATION_VERSION,
    IndicatorCalculationError,
    calculate_indicator_series,
)

GENERATED = datetime(2026, 11, 1, tzinfo=timezone.utc)


def daily_rows(closes, statuses=None):
    statuses = statuses or ["accepted"] * len(closes)
    start = date(2025, 1, 1)
    return [
        {
            "period_start": date.fromordinal(start.toordinal() + index),
            "period_end": date.fromordinal(start.toordinal() + index),
            "close": close,
            "source_status": status,
        }
        for index, (close, status) in enumerate(zip(closes, statuses))
    ]


def weekly_rows(closes, statuses=None, alignments=None):
    statuses = statuses or ["completed"] * len(closes)
    alignments = alignments or ["aligned"] * len(closes)
    start = date(2025, 1, 6)  # Monday
    rows = []
    for index, (close, status, alignment) in enumerate(zip(closes, statuses, alignments)):
        period_start = date.fromordinal(start.toordinal() + index * 7)
        rows.append({
            "period_start": period_start,
            "period_end": date.fromordinal(period_start.toordinal() + 6),
            "close": close,
            "source_status": status,
            "boundary_alignment_status": alignment,
            "session_coverage_status": "not_checked",
        })
    return rows


def calculate(rows, timeframe="1D", instrument="NIFTY50"):
    return calculate_indicator_series(
        rows, instrument_code=instrument, timeframe=timeframe,
        import_batch_id=5, generated_at_utc=GENERATED,
    )


class TestIndicatorEngine(unittest.TestCase):
    def test_ema_9_uses_sma_seed_then_recursive_update(self):
        result = calculate(daily_rows(range(1, 11)))
        self.assertIsNone(result[7]["ema_9"])
        self.assertEqual(result[8]["ema_9"], Decimal("5.00000000"))
        self.assertEqual(result[9]["ema_9"], Decimal("6.00000000"))

    def test_ema_periods_become_available_after_full_seed_window(self):
        result = calculate(daily_rows([Decimal("100")] * 222))
        for period in (9, 20, 50, 100, 200):
            self.assertIsNone(result[period - 2][f"ema_{period}"])
            self.assertEqual(result[period - 1][f"ema_{period}"], Decimal("100.00000000"))

    def test_sma_222_is_rolling_average(self):
        result = calculate(daily_rows(range(1, 224)))
        self.assertIsNone(result[220]["sma_222"])
        self.assertEqual(result[221]["sma_222"], Decimal("111.50000000"))
        self.assertEqual(result[222]["sma_222"], Decimal("112.50000000"))

    def test_calculation_status_warming_partial_ready(self):
        rows = calculate(daily_rows([100] * 222))
        self.assertEqual(rows[7]["calculation_status"], "warming_up")
        self.assertEqual(rows[8]["calculation_status"], "partial")
        self.assertEqual(rows[220]["calculation_status"], "partial")
        self.assertEqual(rows[221]["calculation_status"], "ready")

    def test_nonaccepted_daily_candle_resets_calculation(self):
        closes = [100] * 8 + [101] + [100] * 9
        statuses = ["accepted"] * 8 + ["review_required"] + ["accepted"] * 9
        rows = calculate(daily_rows(closes, statuses))
        self.assertEqual(len(rows), 17)
        self.assertEqual(rows[7]["calculation_status"], "warming_up")
        self.assertEqual(rows[8]["calculation_status"], "warming_up")
        self.assertIsNone(rows[8]["ema_9"])
        self.assertEqual(rows[16]["calculation_status"], "partial")

    def test_provisional_week_is_excluded_and_resets_ema(self):
        statuses = ["completed"] * 9 + ["provisional"] + ["completed"] * 9
        rows = calculate(weekly_rows([100] * len(statuses), statuses), timeframe="1W")
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[8]["calculation_status"], "partial")
        self.assertEqual(rows[9]["calculation_status"], "warming_up")
        self.assertEqual(rows[17]["calculation_status"], "partial")

    def test_quality_limited_month_is_excluded(self):
        candles = [
            {"period_start": date(2025, 1, 1), "period_end": date(2025, 1, 31), "close": 100,
             "source_status": "completed", "boundary_alignment_status": "quality_limited",
             "session_coverage_status": "not_checked"},
            {"period_start": date(2025, 2, 1), "period_end": date(2025, 2, 28), "close": 101,
             "source_status": "completed", "boundary_alignment_status": "aligned",
             "session_coverage_status": "not_checked"},
        ]
        rows = calculate(candles, timeframe="1M")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["period_start"], date(2025, 2, 1))
        self.assertEqual(rows[0]["session_coverage_status"], "not_checked")

    def test_missing_week_bucket_resets_calculation(self):
        rows = weekly_rows([100] * 9)
        rows = rows[:4] + rows[5:]
        result = calculate(rows, timeframe="1W")
        self.assertEqual(len(result), 8)
        self.assertTrue(all(row["calculation_status"] == "warming_up" for row in result))

    def test_india_vix_is_rejected(self):
        with self.assertRaises(IndicatorCalculationError):
            calculate(daily_rows([100] * 10), instrument="INDIA_VIX")

    def test_duplicate_period_is_rejected(self):
        rows = daily_rows([100, 101])
        rows[1]["period_start"] = rows[0]["period_start"]
        rows[1]["period_end"] = rows[0]["period_end"]
        with self.assertRaises(IndicatorCalculationError):
            calculate(rows)

    def test_invalid_close_is_rejected(self):
        with self.assertRaises(IndicatorCalculationError):
            calculate(daily_rows([100, None]))

    def test_metadata_and_precision_are_retained(self):
        last = calculate(daily_rows([123.456789123] * 9))[-1]
        self.assertEqual(last["source_table"], "daily_ohlcv")
        self.assertEqual(last["source_status"], "accepted")
        self.assertEqual(last["calculation_version"], CALCULATION_VERSION)
        self.assertEqual(last["generated_at_utc"], GENERATED)
        self.assertEqual(last["source_close"], Decimal("123.45678912"))


if __name__ == "__main__":
    unittest.main()
