import unittest
from datetime import date, timedelta
from decimal import Decimal

from app.engines.market_cycle_engine import (
    CALCULATION_VERSION,
    MarketCycleCalculationError,
    calculate_market_cycles,
)


def make_row(
    index,
    *,
    timeframe="1D",
    close=100,
    ema20=100,
    ema50=99,
    ema200=98,
    rsi=50,
    adx=22,
    macd=0,
    chop=45,
    bbw=10,
    structure="MIXED_TRANSITION",
    breakout="NONE",
):
    start = date(2025, 1, 6)

    if timeframe == "1D":
        period_start = start + timedelta(days=index)
    else:
        period_start = start + timedelta(days=index * 7)

    period_end = (
        period_start
        if timeframe == "1D"
        else period_start + timedelta(days=6)
    )

    def dec(value):
        return None if value is None else Decimal(str(value))

    return {
        "period_start": period_start,
        "period_end": period_end,
        "source_close": dec(close),
        "ema_20": dec(ema20),
        "ema_50": dec(ema50),
        "ema_200": dec(ema200),
        "rsi_14": dec(rsi),
        "adx_14": dec(adx),
        "macd_histogram": dec(macd),
        "chop_14": dec(chop),
        "bollinger_bandwidth_20_2": dec(bbw),
        "market_structure_state": structure,
        "breakout_status": breakout,
    }


def make_rows(count, **kwargs):
    return [
        make_row(i, **kwargs)
        for i in range(count)
    ]


class TestMarketCycleEngine(unittest.TestCase):

    def calculate(self, rows, timeframe="1D"):
        return calculate_market_cycles(
            rows,
            instrument_code="NIFTY50",
            timeframe=timeframe,
        )

    def test_engine_version_and_classification_count(self):
        result = self.calculate(make_rows(10))

        self.assertEqual(
            result["calculation_version"],
            CALCULATION_VERSION,
        )
        self.assertEqual(result["classification_count"], 10)

    def test_markup_classification(self):
        rows = make_rows(
            60,
            close=120,
            ema20=110,
            ema50=105,
            ema200=100,
            rsi=60,
            adx=30,
            macd=2,
            chop=35,
            bbw=10,
            structure="BULLISH",
        )

        # Current BandWidth is much lower than its history.
        rows[-1]["bollinger_bandwidth_20_2"] = Decimal("5")

        result = self.calculate(rows)
        latest = result["classifications"][-1]

        self.assertEqual(
            latest["cycle_classification"],
            "MARKUP",
        )
        self.assertEqual(latest["rule_score"], 100)

    def test_markdown_classification(self):
        rows = make_rows(
            60,
            close=80,
            ema20=90,
            ema50=95,
            ema200=100,
            rsi=40,
            adx=30,
            macd=-2,
            chop=35,
            bbw=10,
            structure="BEARISH",
        )

        rows[-1]["bollinger_bandwidth_20_2"] = Decimal("5")

        result = self.calculate(rows)

        self.assertEqual(
            result["classifications"][-1]["cycle_classification"],
            "MARKDOWN",
        )

    def test_accumulation_requires_previous_bearish_context(self):
        rows = make_rows(
            59,
            close=80,
            ema20=90,
            ema50=95,
            ema200=100,
            rsi=40,
            adx=30,
            macd=-2,
            chop=45,
            bbw=10,
            structure="BEARISH",
        )

        current = make_row(
            59,
            close=101,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=43,
            adx=22,
            macd=-1,
            chop=55,
            bbw=5,
            structure="MIXED_TRANSITION",
        )

        rows.append(current)

        result = self.calculate(rows)
        latest = result["classifications"][-1]

        self.assertEqual(
            latest["cycle_classification"],
            "ACCUMULATION",
        )
        self.assertEqual(
            latest["classification_basis"],
            "PRICE_ACTION_HEURISTIC",
        )

    def test_distribution_requires_previous_bullish_context(self):
        rows = make_rows(
            59,
            close=120,
            ema20=110,
            ema50=105,
            ema200=100,
            rsi=60,
            adx=30,
            macd=2,
            chop=45,
            bbw=10,
            structure="BULLISH",
        )

        current = make_row(
            59,
            close=99,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=55,
            adx=22,
            macd=1,
            chop=55,
            bbw=5,
            structure="MIXED_TRANSITION",
        )

        rows.append(current)

        result = self.calculate(rows)

        self.assertEqual(
            result["classifications"][-1]["cycle_classification"],
            "DISTRIBUTION",
        )

    def test_sideways_consolidation_classification(self):
        rows = make_rows(
            60,
            close=100,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=50,
            adx=18,
            macd=0,
            chop=65,
            bbw=10,
            structure="MIXED_TRANSITION",
        )

        rows[-1]["bollinger_bandwidth_20_2"] = Decimal("5")

        result = self.calculate(rows)

        self.assertEqual(
            result["classifications"][-1]["cycle_classification"],
            "SIDEWAYS_CONSOLIDATION",
        )

    def test_transition_uncertain_classification(self):
        rows = make_rows(
            60,
            close=100,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=50,
            adx=22,
            macd=0,
            chop=45,
            bbw=10,
            structure="MIXED_TRANSITION",
        )

        result = self.calculate(rows)

        self.assertEqual(
            result["classifications"][-1]["cycle_classification"],
            "TRANSITION_UNCERTAIN",
        )

    def test_insufficient_data_during_bandwidth_warmup(self):
        result = self.calculate(make_rows(30))

        self.assertTrue(
            all(
                row["cycle_classification"] == "INSUFFICIENT_DATA"
                for row in result["classifications"]
            )
        )

    def test_bandwidth_percentile_uses_only_available_history(self):
        rows = make_rows(60, bbw=10)
        rows[-1]["bollinger_bandwidth_20_2"] = Decimal("5")

        result = self.calculate(rows)

        percentile = (
            result["classifications"][-1]["bandwidth_percentile"]
        )

        self.assertIsNotNone(percentile)
        self.assertLess(percentile, Decimal("2"))

    def test_future_candles_do_not_change_past_classifications(self):
        rows = make_rows(
            70,
            close=100,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=50,
            adx=22,
            macd=0,
            chop=45,
            bbw=10,
            structure="MIXED_TRANSITION",
        )

        first_result = self.calculate(rows[:60])
        extended_result = self.calculate(rows)

        self.assertEqual(
            first_result["classifications"],
            extended_result["classifications"][:60],
        )

    def test_missing_week_resets_percentile_history(self):
        rows = make_rows(
            60,
            timeframe="1W",
            bbw=10,
        )

        # Introduce one missing weekly period.
        for row in rows[30:]:
            row["period_start"] += timedelta(days=7)
            row["period_end"] += timedelta(days=7)

        result = self.calculate(rows, timeframe="1W")

        self.assertEqual(result["segment_count"], 2)

        # First candle after the gap must start a fresh window.
        self.assertIsNone(
            result["classifications"][30]["bandwidth_percentile"]
        )

    def test_invalid_market_structure_state_is_rejected(self):
        rows = make_rows(5)
        rows[2]["market_structure_state"] = "UNKNOWN"

        with self.assertRaises(MarketCycleCalculationError):
            self.calculate(rows)

    def test_rejected_daily_candle_resets_analysis_segment(self):
        rows = make_rows(
            130,
            close=100,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=50,
            adx=22,
            macd=0,
            chop=45,
            bbw=10,
            structure="MIXED_TRANSITION",
        )

        for row in rows:
            row["source_status"] = "accepted"

        # One rejected source candle divides the series.
        rows[65]["source_status"] = "review_required"

        result = self.calculate(rows)

        self.assertEqual(result["segment_count"], 2)

        # The rejected candle must not receive a classification.
        self.assertEqual(result["classification_count"], 129)

        # The first classification after the rejected candle
        # must start with a fresh BandWidth history.
        after_rejection = result["classifications"][65]

        self.assertEqual(
            after_rejection["period_start"],
            rows[66]["period_start"],
        )

        self.assertIsNone(
            after_rejection["bandwidth_percentile"]
        )

        # The preceding segment had enough data for a percentile.
        self.assertIsNotNone(
            result["classifications"][64]["bandwidth_percentile"]
        )

    def test_india_vix_is_rejected(self):
        with self.assertRaises(MarketCycleCalculationError):
            calculate_market_cycles(
                make_rows(10),
                instrument_code="INDIA_VIX",
                timeframe="1D",
            )

    def test_duplicate_period_is_rejected(self):
        rows = make_rows(5)
        rows[1]["period_start"] = rows[0]["period_start"]

        with self.assertRaises(MarketCycleCalculationError):
            self.calculate(rows)

    def test_accumulation_requires_minimum_prior_bearish_ratio(self):

        # Create 60 consecutive daily candles.
        rows = make_rows(
            60,
            close=100,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=50,
            adx=22,
            macd=0,
            chop=45,
            bbw=10,
            structure="MIXED_TRANSITION",
        )

        # Modify nine candles to represent bearish conditions.
        for index in range(40, 49):

            bearish_row = make_row(
                index,
                close=80,
                ema20=90,
                ema50=95,
                ema200=100,
                rsi=40,
                adx=30,
                macd=-2,
                chop=45,
                bbw=10,
                structure="BEARISH",
            )

            rows[index].update({
                key: value
                for key, value in bearish_row.items()
                if key not in ("period_start", "period_end")
            })

        # Eleven remaining observations are non-bearish.
        # Bearish context ratio = 9 / 20 = 45%.

        current = make_row(
            60,
            close=101,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=55,
            adx=22,
            macd=1,
            chop=55,
            bbw=5,
            structure="MIXED_TRANSITION",
        )

        rows.append(current)

        result = self.calculate(rows)

        self.assertNotEqual(
            result["classifications"][-1]["cycle_classification"],
            "ACCUMULATION",
        )

    def test_accumulation_requires_minimum_context_samples(self):
        rows = make_rows(
            9,
            close=80,
            ema20=90,
            ema50=95,
            ema200=100,
            rsi=40,
            adx=30,
            macd=-2,
            chop=45,
            bbw=10,
            structure="BEARISH",
        )

        rows.append(make_row(
            9,
            close=101,
            ema20=100,
            ema50=99,
            ema200=98,
            rsi=45,
            adx=22,
            macd=-1,
            chop=55,
            bbw=5,
            structure="MIXED_TRANSITION",
        ))

        result = self.calculate(rows)

        self.assertNotEqual(
            result["classifications"][-1]["cycle_classification"],
            "ACCUMULATION",
        )

if __name__ == "__main__":
    unittest.main()
