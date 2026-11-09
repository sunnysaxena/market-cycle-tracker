
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.engines.indicator_engine import (
    CALCULATION_VERSION,
    IndicatorCalculationError,
    calculate_indicator_series,
)

from app.engines.indicator_engine import (
    CALCULATION_VERSION,
    IndicatorCalculationError,
    _IndicatorState,
    calculate_indicator_series,
)

GENERATED = datetime(2026, 11, 1, tzinfo=timezone.utc)


def daily_rows(closes, statuses=None, highs=None, lows=None):
    statuses = statuses or ["accepted"] * len(closes)
    rows = []
    start = date(2025, 1, 1)

    for index, (value, status) in enumerate(zip(closes, statuses)):
        close = Decimal(str(value))
        high = Decimal(str(highs[index])) if highs else close + 2
        low = Decimal(str(lows[index])) if lows else close - 2

        candle_date = date.fromordinal(start.toordinal() + index)

        rows.append({
            "period_start": candle_date,
            "period_end": candle_date,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "source_status": status,
        })

    return rows


def weekly_rows(closes, statuses=None, alignments=None):
    statuses = statuses or ["completed"] * len(closes)
    alignments = alignments or ["aligned"] * len(closes)
    rows = []
    start = date(2025, 1, 6)

    for index, (value, status, alignment) in enumerate(
        zip(closes, statuses, alignments)
    ):
        period_start = date.fromordinal(start.toordinal() + index * 7)
        close = Decimal(str(value))

        rows.append({
            "period_start": period_start,
            "period_end": date.fromordinal(
                period_start.toordinal() + 6
            ),
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "source_status": status,
            "boundary_alignment_status": alignment,
            "session_coverage_status": "not_checked",
        })

    return rows


def calculate(rows, timeframe="1D", instrument="NIFTY50"):
    return calculate_indicator_series(
        rows,
        instrument_code=instrument,
        timeframe=timeframe,
        import_batch_id=5,
        generated_at_utc=GENERATED,
    )


class TestFullIndicatorEngine(unittest.TestCase):

    def test_ema_9_sma_seed_and_recursive_update(self):
        result = calculate(daily_rows(range(1, 11)))

        self.assertIsNone(result[7]["ema_9"])
        self.assertEqual(
            result[8]["ema_9"],
            Decimal("5.00000000"),
        )
        self.assertEqual(
            result[9]["ema_9"],
            Decimal("6.00000000"),
        )

    def test_long_ema_and_sma_222(self):
        result = calculate(daily_rows([100] * 222))

        self.assertEqual(
            result[221]["ema_200"],
            Decimal("100.00000000"),
        )
        self.assertIsNone(result[220]["sma_222"])
        self.assertEqual(
            result[221]["sma_222"],
            Decimal("100.00000000"),
        )

    def test_rsi_flat_market_returns_50(self):
        result = calculate(daily_rows([100] * 15))

        self.assertIsNone(result[13]["rsi_14"])
        self.assertEqual(
            result[14]["rsi_14"],
            Decimal("50.00000000"),
        )

    def test_rsi_all_gains_returns_100(self):
        result = calculate(daily_rows(range(100, 115)))

        self.assertEqual(
            result[14]["rsi_14"],
            Decimal("100.00000000"),
        )

    def test_rsi_all_losses_returns_zero(self):
        result = calculate(daily_rows(range(115, 100, -1)))

        self.assertEqual(
            result[14]["rsi_14"],
            Decimal("0E-8"),
        )

    def test_atr_14(self):
        result = calculate(
            daily_rows(
                [100] * 15,
                highs=[110] * 15,
                lows=[90] * 15,
            )
        )

        self.assertIsNone(result[13]["atr_14"])
        self.assertEqual(
            result[14]["atr_14"],
            Decimal("20.00000000"),
        )

    def test_directional_indicators_and_adx(self):
        closes = [Decimal(100 + i) for i in range(28)]
        highs = [c + 1 for c in closes]
        lows = [c - 2 for c in closes]

        result = calculate(
            daily_rows(closes, highs=highs, lows=lows)
        )

        self.assertIsNotNone(result[14]["plus_di_14"])
        self.assertEqual(
            result[14]["minus_di_14"],
            Decimal("0E-8"),
        )
        self.assertIsNone(result[26]["adx_14"])
        self.assertEqual(
            result[27]["adx_14"],
            Decimal("100.00000000"),
        )

    def test_macd_signal_after_34_closes(self):
        result = calculate(daily_rows([100] * 34))

        self.assertIsNone(result[32]["macd_signal_9"])
        self.assertEqual(
            result[33]["macd_line_12_26"],
            Decimal("0E-8"),
        )
        self.assertEqual(
            result[33]["macd_signal_9"],
            Decimal("0E-8"),
        )
        self.assertEqual(
            result[33]["macd_histogram"],
            Decimal("0E-8"),
        )

    def test_bollinger_bands_constant_series(self):
        result = calculate(daily_rows([100] * 20))
        row = result[19]

        self.assertEqual(
            row["bollinger_middle_20_2"],
            Decimal("100.00000000"),
        )
        self.assertEqual(
            row["bollinger_upper_20_2"],
            Decimal("100.00000000"),
        )
        self.assertEqual(
            row["bollinger_lower_20_2"],
            Decimal("100.00000000"),
        )

    def test_bollinger_population_standard_deviation(self):
        result = calculate(daily_rows(range(1, 21)))
        row = result[19]

        self.assertEqual(
            row["bollinger_middle_20_2"],
            Decimal("10.50000000"),
        )
        self.assertGreater(
            row["bollinger_upper_20_2"],
            row["bollinger_middle_20_2"],
        )
        self.assertLess(
            row["bollinger_lower_20_2"],
            row["bollinger_middle_20_2"],
        )

    def test_warming_partial_ready_status(self):
        result = calculate(daily_rows([100] * 222))

        self.assertEqual(
            result[7]["calculation_status"], "warming_up"
        )
        self.assertEqual(
            result[8]["calculation_status"], "partial"
        )
        self.assertEqual(
            result[220]["calculation_status"], "partial"
        )
        self.assertEqual(
            result[221]["calculation_status"], "ready"
        )

    def test_chop_14_warmup_and_known_value(self):
        result = calculate(daily_rows(range(100, 115)))

        # CHOP needs 14 True Range values, requiring 15 candles.
        self.assertIsNone(result[13]["chop_14"])

        self.assertEqual(
            result[14]["chop_14"],
            Decimal("45.17288553"),
    )

    def test_chop_14_constant_series_equals_100(self):
        result = calculate(daily_rows([100] * 15))

        self.assertEqual(
            result[14]["chop_14"],
            Decimal("100.00000000"),
        )

    def test_bollinger_bandwidth_population_standard_deviation(self):
        result = calculate(daily_rows(range(1, 21)))
        row = result[19]

        self.assertEqual(
            row["bollinger_bandwidth_20_2"],
            Decimal("219.66785895"),
        )

    def test_bollinger_bandwidth_constant_series_zero(self):
        result = calculate(daily_rows([100] * 20))

        self.assertEqual(
            result[19]["bollinger_bandwidth_20_2"],
            Decimal("0E-8"),
        )

    def test_bollinger_bandwidth_zero_middle_returns_none(self):
        state = _IndicatorState()
        values = {}

        for _ in range(20):
            values = state.update(
                Decimal("0"),
                Decimal("2"),
                Decimal("-2"),
                Decimal("0"),
            )

        self.assertEqual(
            values["bollinger_middle_20_2"],
            Decimal("0"),
        )

        self.assertIsNone(
            values["bollinger_bandwidth_20_2"]
        )

    def test_nonaccepted_daily_candle_resets_state(self):
        closes = [100] * 8 + [101] + [100] * 9
        statuses = (
            ["accepted"] * 8
            + ["review_required"]
            + ["accepted"] * 9
        )

        result = calculate(daily_rows(closes, statuses))

        self.assertEqual(len(result), 17)
        self.assertEqual(
            result[8]["calculation_status"], "warming_up"
        )
        self.assertIsNone(result[8]["ema_9"])

    def test_provisional_week_is_excluded(self):
        statuses = (
            ["completed"] * 9
            + ["provisional"]
            + ["completed"] * 9
        )

        result = calculate(
            weekly_rows([100] * len(statuses), statuses),
            timeframe="1W",
        )

        self.assertEqual(len(result), 18)
        self.assertEqual(
            result[8]["calculation_status"], "partial"
        )
        self.assertEqual(
            result[9]["calculation_status"], "warming_up"
        )

    def test_quality_limited_period_is_excluded(self):
        rows = weekly_rows([100, 101])
        rows[1]["boundary_alignment_status"] = "quality_limited"

        result = calculate(rows, timeframe="1W")

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["boundary_alignment_status"], "aligned"
        )

    def test_missing_week_resets_state(self):
        rows = weekly_rows([100] * 9)
        rows = rows[:4] + rows[5:]

        result = calculate(rows, timeframe="1W")

        self.assertEqual(len(result), 8)
        self.assertTrue(
            all(
                row["calculation_status"] == "warming_up"
                for row in result
            )
        )

    def test_india_vix_is_rejected(self):
        with self.assertRaises(IndicatorCalculationError):
            calculate(
                daily_rows([100] * 20),
                instrument="INDIA_VIX",
            )

    def test_invalid_ohlc_is_rejected(self):
        rows = daily_rows([100])
        rows[0]["high"] = Decimal("99")

        with self.assertRaises(IndicatorCalculationError):
            calculate(rows)

    def test_duplicate_period_is_rejected(self):
        rows = daily_rows([100, 101])
        rows[1]["period_start"] = rows[0]["period_start"]
        rows[1]["period_end"] = rows[0]["period_end"]

        with self.assertRaises(IndicatorCalculationError):
            calculate(rows)

    def test_metadata_and_source_ohlc_are_retained(self):
        result = calculate(daily_rows([100] * 10))
        row = result[-1]

        self.assertEqual(row["source_open"], Decimal("100.00000000"))
        self.assertEqual(row["source_high"], Decimal("102.00000000"))
        self.assertEqual(row["source_low"], Decimal("98.00000000"))
        self.assertEqual(row["source_close"], Decimal("100.00000000"))

        self.assertEqual(row["source_table"], "daily_ohlcv")
        self.assertEqual(row["calculation_version"], CALCULATION_VERSION)
        self.assertEqual(row["generated_at_utc"], GENERATED)

    def test_weekly_coverage_metadata_is_preserved(self):
        result = calculate(
            weekly_rows([100] * 10),
            timeframe="1W",
        )

        self.assertEqual(
            result[0]["session_coverage_status"], "not_checked"
        )


if __name__ == "__main__":
    unittest.main()
