
from dataclasses import FrozenInstanceError
from decimal import Decimal
import unittest

from app.engines.candlestick_pattern_engine import (
    CandlestickPatternError,
)
from app.engines.candlestick_pattern_config import (
    CALCULATION_VERSION,
    CandlestickPatternConfig,
)
from app.engines.candlestick_multi_candle_engine import (
    MULTI_CANDLE_CALCULATION_VERSION,
    MultiCandlePatternConfig,
)
from app.services.candlestick_analysis_service import (
    CandlestickAnalysisResult,
    IndexedSingleCandleResult,
    TwoCandlePatternMatch,
    analyze_candlestick_patterns,
)


class TestCandlestickAnalysisService(unittest.TestCase):

    def test_single_candle_input(self):
        records = [
            {
                "open": 100,
                "high": 105,
                "low": 95,
                "close": 102,
            }
        ]

        result = analyze_candlestick_patterns(records)

        self.assertEqual(result.candle_count, 1)
        self.assertEqual(len(result.single_candle_results), 1)
        self.assertEqual(result.single_candle_results[0].candle_index, 0)
        self.assertEqual(result.two_candle_matches, ())
        self.assertEqual(result.multi_candle_matches, ())

    def test_two_candle_input(self):
        records = [
            {
                "open": 110,
                "high": 112,
                "low": 98,
                "close": 100,
            },
            {
                "open": 97,
                "high": 113,
                "low": 96,
                "close": 111,
            },
        ]

        result = analyze_candlestick_patterns(records)

        self.assertEqual(result.candle_count, 2)
        self.assertEqual(len(result.single_candle_results), 2)
        self.assertEqual(result.two_candle_matches, (
            TwoCandlePatternMatch(
                pattern="BULLISH_ENGULFING",
                start_index=0,
                end_index=1,
            ),
        ))
        self.assertEqual(result.multi_candle_matches, ())

    def test_single_candle_indices_preserve_input_order(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
            {"open": 102, "high": 108, "low": 100, "close": 106},
            {"open": 106, "high": 109, "low": 103, "close": 104},
        ]

        result = analyze_candlestick_patterns(records)

        self.assertEqual(
            tuple(item.candle_index for item in result.single_candle_results),
            (0, 1, 2),
        )

    def test_multi_candle_analysis_runs_for_three_candles(self):
        records = [
            {"open": 10, "high": 12, "low": 8, "close": 9},
            {"open": 8, "high": 13, "low": 7, "close": 12},
            {"open": 12, "high": 14, "low": 11, "close": 13.5},
        ]

        result = analyze_candlestick_patterns(records)

        self.assertEqual(result.candle_count, 3)
        self.assertTrue(
            any(
                match.pattern == "THREE_OUTSIDE_UP"
                for match in result.multi_candle_matches
            )
        )

    def test_multi_candle_indices_are_preserved(self):
        records = [
            {"open": 100, "high": 102, "low": 98, "close": 99},
            {"open": 98, "high": 103, "low": 97, "close": 102},
            {"open": 102, "high": 104, "low": 101, "close": 103.5},
        ]

        result = analyze_candlestick_patterns(records)

        match = next(
            item
            for item in result.multi_candle_matches
            if item.pattern == "THREE_OUTSIDE_UP"
        )

        self.assertEqual(match.candle_count, 3)
        self.assertEqual(match.start_index, 0)
        self.assertEqual(match.end_index, 2)

    def test_calculation_versions_are_returned(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
        ]

        result = analyze_candlestick_patterns(records)

        self.assertEqual(
            result.single_candle_calculation_version,
            CALCULATION_VERSION,
        )
        self.assertEqual(
            result.two_candle_calculation_version,
            CALCULATION_VERSION,
        )
        self.assertEqual(
            result.multi_candle_calculation_version,
            MULTI_CANDLE_CALCULATION_VERSION,
        )

    def test_custom_configurations_are_accepted(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
        ]

        pattern_config = CandlestickPatternConfig(
            doji_max_body_ratio=Decimal("0.12"),
        )
        multi_config = MultiCandlePatternConfig(
            soldier_min_body_range_ratio=Decimal("0.55"),
        )

        result = analyze_candlestick_patterns(
            records,
            pattern_config=pattern_config,
            multi_candle_config=multi_config,
        )

        self.assertEqual(result.candle_count, 1)

    def test_empty_input_is_rejected(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns([])

    def test_non_sequence_input_is_rejected(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns(
                {"open": 100, "high": 105, "low": 95, "close": 102}
            )

    def test_string_input_is_rejected(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns("invalid")

    def test_non_mapping_candle_is_rejected(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
            None,
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns(records)

    def test_invalid_ohlc_is_rejected(self):
        records = [
            {"open": 100, "high": 95, "low": 90, "close": 92},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns(records)

    def test_invalid_pattern_config_type_is_rejected(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns(
                records,
                pattern_config=None,
            )

    def test_invalid_multi_config_type_is_rejected(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_candlestick_patterns(
                records,
                multi_candle_config=None,
            )

    def test_result_dataclasses_are_immutable(self):
        records = [
            {"open": 100, "high": 105, "low": 95, "close": 102},
        ]

        result = analyze_candlestick_patterns(records)

        with self.assertRaises(FrozenInstanceError):
            result.candle_count = 10


if __name__ == "__main__":
    unittest.main()
