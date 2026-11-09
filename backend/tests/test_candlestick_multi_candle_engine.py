import unittest
from decimal import Decimal

from app.engines.candlestick_pattern_engine import CandlestickPatternError
from app.engines.candlestick_multi_candle_engine import (
    DEFAULT_MULTI_CANDLE_CONFIG,
    MultiCandlePatternConfig,
    analyze_multi_candle_patterns,
)


class TestMultiCandlePatternEngine(unittest.TestCase):

    def test_morning_star(self):
        records = [
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 98, "high": 99, "low": 97, "close": 98.5},
            {"open": 99, "high": 108, "low": 98, "close": 107},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("MORNING_STAR", result.patterns)
        self.assertEqual(result.calculation_version,
                         "candlestick_multi_patterns_v1.2")

    def test_morning_doji_star(self):
        records = [
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 98, "high": 99, "low": 97, "close": 98},
            {"open": 99, "high": 108, "low": 98, "close": 107},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("MORNING_DOJI_STAR", result.patterns)
        self.assertNotIn("MORNING_STAR", result.patterns)

    def test_evening_star(self):
        records = [
            {"open": 100, "high": 111, "low": 99, "close": 110},
            {"open": 112, "high": 113, "low": 111, "close": 112.5},
            {"open": 111, "high": 112, "low": 102, "close": 103},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("EVENING_STAR", result.patterns)

    def test_three_white_soldiers(self):
        records = [
            {"open": 100, "high": 112, "low": 99, "close": 111},
            {"open": 110, "high": 122, "low": 109, "close": 121},
            {"open": 120, "high": 132, "low": 119, "close": 131},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("THREE_WHITE_SOLDIERS", result.patterns)

    def test_three_black_crows(self):
        records = [
            {"open": 130, "high": 131, "low": 118, "close": 119},
            {"open": 120, "high": 121, "low": 108, "close": 109},
            {"open": 110, "high": 111, "low": 98, "close": 99},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("THREE_BLACK_CROWS", result.patterns)

    def test_three_inside_up(self):
        records = [
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 101, "high": 109, "low": 100, "close": 108},
            {"open": 108, "high": 113, "low": 107, "close": 112},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("THREE_INSIDE_UP", result.patterns)

    
    def test_bearish_three_line_strike(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11},
            {"open": 10.5, "high": 13, "low": 10, "close": 12},
            {"open": 11.5, "high": 14, "low": 11, "close": 13},
            {"open": 13.5, "high": 14, "low": 8, "close": 9},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("BEARISH_THREE_LINE_STRIKE", result.patterns)

    def test_bullish_three_line_strike(self):
        records = [
            {"open": 13, "high": 14, "low": 11, "close": 12},
            {"open": 12.5, "high": 13, "low": 10, "close": 11},
            {"open": 11.5, "high": 12, "low": 9, "close": 10},
            {"open": 9.5, "high": 16, "low": 8, "close": 14},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("BULLISH_THREE_LINE_STRIKE", result.patterns)


    def test_rising_three_methods(self):
        records = [
            {"open": 10, "high": 16, "low": 9, "close": 15},
            {"open": 14, "high": 15, "low": 12, "close": 13},
            {"open": 13, "high": 14, "low": 11, "close": 12},
            {"open": 12, "high": 13, "low": 10.5, "close": 11},
            {"open": 12, "high": 17, "low": 11, "close": 16},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("RISING_THREE_METHODS", result.patterns)

    def test_falling_three_methods(self):
        records = [
            {"open": 16, "high": 17, "low": 10, "close": 11},
            {"open": 12, "high": 15, "low": 11, "close": 14},
            {"open": 13, "high": 14, "low": 12, "close": 13.5},
            {"open": 14, "high": 15, "low": 13, "close": 14.5},
            {"open": 13, "high": 14, "low": 8, "close": 9},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("FALLING_THREE_METHODS", result.patterns)

    def test_requires_at_least_three_candles(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11},
            {"open": 11, "high": 13, "low": 10, "close": 12},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_multi_candle_patterns(records)

    def test_invalid_ohlc_is_rejected(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11},
            {"open": 11, "high": 13, "low": 10, "close": 12},
            {"open": 12, "high": 11, "low": 10, "close": 13},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_multi_candle_patterns(records)

    def test_invalid_config_type_is_rejected(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11},
            {"open": 11, "high": 13, "low": 10, "close": 12},
            {"open": 12, "high": 14, "low": 11, "close": 13},
        ]

        with self.assertRaises(CandlestickPatternError):
            analyze_multi_candle_patterns(records, config="invalid")

    def test_config_rejects_float_threshold(self):
        with self.assertRaises(ValueError):
            MultiCandlePatternConfig(
                long_body_min_range_ratio=0.5
            )

    def test_match_contains_correct_candle_indexes(self):
        records = [
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 98, "high": 99, "low": 97, "close": 98.5},
            {"open": 99, "high": 108, "low": 98, "close": 107},
        ]

        result = analyze_multi_candle_patterns(records)

        morning_star = next(
            match for match in result.matches
            if match.pattern == "MORNING_STAR"
        )

        self.assertEqual(morning_star.candle_count, 3)
        self.assertEqual(morning_star.start_index, 0)
        self.assertEqual(morning_star.end_index, 2)

    
    def test_three_outside_up(self):
        records = [
            {"open": 10, "high": 12, "low": 8, "close": 9},
            {"open": 8, "high": 13, "low": 7, "close": 12},
            {"open": 12, "high": 14, "low": 11, "close": 13.5},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("THREE_OUTSIDE_UP", result.patterns)

    def test_three_outside_down(self):
        records = [
            {"open": 12, "high": 14, "low": 11, "close": 13},
            {"open": 14, "high": 15, "low": 10, "close": 11},
            {"open": 11, "high": 12, "low": 9, "close": 9.5},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("THREE_OUTSIDE_DOWN", result.patterns)

    def test_upside_tasuki_gap(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11.5},
            {"open": 12.5, "high": 14, "low": 12.2, "close": 13.8},
            {"open": 13.5, "high": 13.6, "low": 11.9, "close": 12.1},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("UPSIDE_TASUKI_GAP", result.patterns)

    
    
    def test_downside_tasuki_gap(self):
        records = [
            {"open": 14, "high": 14.5, "low": 12, "close": 12.5},
            {"open": 11.8, "high": 11.9, "low": 10, "close": 10.2},
            {"open": 11.0, "high": 12.0, "low": 10.9, "close": 11.95},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("DOWNSIDE_TASUKI_GAP", result.patterns)


    def test_bullish_abandoned_baby(self):
        records = [
            {"open": 12, "high": 13, "low": 9, "close": 10},
            {"open": 8, "high": 8.2, "low": 7.8, "close": 8},
            {"open": 9.5, "high": 12, "low": 9.3, "close": 11.5},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("BULLISH_ABANDONED_BABY", result.patterns)

    def test_bearish_abandoned_baby(self):
        records = [
            {"open": 9, "high": 13, "low": 8, "close": 12},
            {"open": 14, "high": 14.2, "low": 13.8, "close": 14},
            {"open": 12.5, "high": 12.7, "low": 9, "close": 9.5},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("BEARISH_ABANDONED_BABY", result.patterns)


    
    def test_three_stars_in_the_south(self):
        records = [
            {"open": 100, "high": 101, "low": 88, "close": 90},
            {"open": 89, "high": 89.1, "low": 87.8, "close": 88.5},
            {"open": 88.9, "high": 88.9, "low": 88.7, "close": 88.7},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertIn("THREE_STARS_IN_THE_SOUTH", result.patterns)

    def test_three_stars_in_the_south_rejects_bullish_third_candle(self):
        records = [
            {"open": 100, "high": 101, "low": 88, "close": 90},
            {"open": 89, "high": 89.1, "low": 87.8, "close": 88.5},
            {"open": 88.7, "high": 88.9, "low": 88.7, "close": 88.9},
        ]

        result = analyze_multi_candle_patterns(records)
        self.assertNotIn("THREE_STARS_IN_THE_SOUTH", result.patterns)

    
    def test_morning_star_excludes_doji_star(self):
        records = [
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 98, "high": 99, "low": 97, "close": 98.5},
            {"open": 99, "high": 108, "low": 98, "close": 107},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("MORNING_STAR", result.patterns)
        self.assertNotIn("MORNING_DOJI_STAR", result.patterns)

    def test_evening_doji_star_excludes_evening_star(self):
        records = [
            {"open": 100, "high": 111, "low": 99, "close": 110},
            {"open": 112, "high": 113, "low": 111, "close": 112.1},
            {"open": 111, "high": 112, "low": 102, "close": 103},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("EVENING_DOJI_STAR", result.patterns)
        self.assertNotIn("EVENING_STAR", result.patterns)

    def test_three_inside_down(self):
        records = [
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 109, "high": 110, "low": 101, "close": 102},
            {"open": 102, "high": 103, "low": 96, "close": 97},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertIn("THREE_INSIDE_DOWN", result.patterns)

    def test_three_inside_up_rejects_weak_confirmation(self):
        records = [
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 101, "high": 109, "low": 100, "close": 108},
            {"open": 108, "high": 109, "low": 107, "close": 109},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_INSIDE_UP", result.patterns)

    def test_three_inside_down_rejects_weak_confirmation(self):
        records = [
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 109, "high": 110, "low": 101, "close": 102},
            {"open": 102, "high": 103, "low": 101, "close": 101},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_INSIDE_DOWN", result.patterns)


    
    def test_upside_tasuki_rejects_missing_gap(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11.5},
            {"open": 11.4, "high": 14, "low": 11.2, "close": 13.8},
            {"open": 13.5, "high": 13.6, "low": 11.9, "close": 12.1},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("UPSIDE_TASUKI_GAP", result.patterns)

    def test_downside_tasuki_rejects_missing_gap(self):
        records = [
            {"open": 14, "high": 14.5, "low": 12, "close": 12.5},
            {"open": 12.4, "high": 12.6, "low": 10, "close": 10.2},
            {"open": 11.0, "high": 12.0, "low": 10.9, "close": 11.95},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("DOWNSIDE_TASUKI_GAP", result.patterns)

    def test_bullish_abandoned_baby_rejects_missing_first_gap(self):
        records = [
            {"open": 12, "high": 13, "low": 9, "close": 10},
            {"open": 10.1, "high": 10.2, "low": 9.9, "close": 10},
            {"open": 11, "high": 12, "low": 10.8, "close": 11.5},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("BULLISH_ABANDONED_BABY", result.patterns)

    def test_bearish_abandoned_baby_rejects_missing_second_gap(self):
        records = [
            {"open": 9, "high": 13, "low": 8, "close": 12},
            {"open": 14, "high": 14.2, "low": 13.8, "close": 14},
            {"open": 13.5, "high": 14.0, "low": 9, "close": 9.5},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("BEARISH_ABANDONED_BABY", result.patterns)

    def test_rising_three_methods_rejects_oversized_middle_candle(self):
        result = analyze_multi_candle_patterns([
            {"open": 10, "high": 16, "low": 9, "close": 15},
            {"open": 14, "high": 15, "low": 11.5, "close": 11.9},
            {"open": 13, "high": 14, "low": 11, "close": 12},
            {"open": 12, "high": 13, "low": 10.5, "close": 11},
            {"open": 12, "high": 17, "low": 11, "close": 16},
        ])

        self.assertNotIn("RISING_THREE_METHODS", result.patterns)

    def test_falling_three_methods_rejects_oversized_middle_candle(self):
        result = analyze_multi_candle_patterns([
            {"open": 16, "high": 17, "low": 10, "close": 11},
            {"open": 12, "high": 14.5, "low": 11.5, "close": 14.1},
            {"open": 13, "high": 14, "low": 12, "close": 13.5},
            {"open": 14, "high": 15, "low": 13, "close": 14.5},
            {"open": 13, "high": 14, "low": 8, "close": 9},
        ])

        self.assertNotIn("FALLING_THREE_METHODS", result.patterns)

    def test_rising_three_methods_rejects_weak_final_candle(self):
        result = analyze_multi_candle_patterns([
            {"open": 10, "high": 16, "low": 9, "close": 15},
            {"open": 14, "high": 15, "low": 12, "close": 13},
            {"open": 13, "high": 14, "low": 11, "close": 12},
            {"open": 12, "high": 13, "low": 10.5, "close": 11},
            {"open": 15.2, "high": 17, "low": 14, "close": 16},
        ])

        self.assertNotIn("RISING_THREE_METHODS", result.patterns)

    def test_falling_three_methods_rejects_weak_final_candle(self):
        result = analyze_multi_candle_patterns([
            {"open": 16, "high": 17, "low": 10, "close": 11},
            {"open": 12, "high": 15, "low": 11, "close": 14},
            {"open": 13, "high": 14, "low": 12, "close": 13.5},
            {"open": 14, "high": 15, "low": 13, "close": 14.5},
            {"open": 10, "high": 11, "low": 8, "close": 9.8},
        ])

        self.assertNotIn("FALLING_THREE_METHODS", result.patterns)

    def test_methods_middle_body_threshold_accepts_zero(self):
        config = MultiCandlePatternConfig(
            methods_middle_max_body_to_first_body_ratio=Decimal("0")
        )
        self.assertEqual(
            config.methods_middle_max_body_to_first_body_ratio,
            Decimal("0"),
        )

    def test_methods_middle_body_threshold_accepts_one(self):
        config = MultiCandlePatternConfig(
            methods_middle_max_body_to_first_body_ratio=Decimal("1")
        )
        self.assertEqual(
            config.methods_middle_max_body_to_first_body_ratio,
            Decimal("1"),
        )

    def test_methods_middle_body_threshold_rejects_negative(self):
        with self.assertRaises(ValueError):
            MultiCandlePatternConfig(
                methods_middle_max_body_to_first_body_ratio=Decimal("-0.01")
            )

    def test_methods_middle_body_threshold_rejects_above_one(self):
        with self.assertRaises(ValueError):
            MultiCandlePatternConfig(
                methods_middle_max_body_to_first_body_ratio=Decimal("1.01")
            )

    def test_config_rejects_doji_threshold_above_small_body_threshold(self):
        with self.assertRaises(ValueError): 
            MultiCandlePatternConfig(
                doji_max_body_ratio=Decimal("0.40"),
                small_body_max_range_ratio=Decimal("0.30"),
            )

    def test_config_rejects_overlapping_small_and_long_body_thresholds(self):
        with self.assertRaises(ValueError):
            MultiCandlePatternConfig(
                small_body_max_range_ratio=Decimal("0.50"),
                long_body_min_range_ratio=Decimal("0.50"),
            )

    def test_config_accepts_valid_ordered_thresholds(self):
        config = MultiCandlePatternConfig(
            doji_max_body_ratio=Decimal("0.10"),
            small_body_max_range_ratio=Decimal("0.30"),
            long_body_min_range_ratio=Decimal("0.50"),
        )

        self.assertEqual(
            config.doji_max_body_ratio,
            Decimal("0.10"),
        )

    def test_three_outside_up_rejects_weak_confirmation(self):
        records = [
            {"open": 10, "high": 12, "low": 8, "close": 9},
            {"open": 8, "high": 13, "low": 7, "close": 12},
            {"open": 12, "high": 13, "low": 11.9, "close": 12.1},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_OUTSIDE_UP", result.patterns)

    def test_three_outside_down_rejects_weak_confirmation(self):
        records = [
            {"open": 12, "high": 14, "low": 11, "close": 13},
            {"open": 14, "high": 15, "low": 10, "close": 11},
            {"open": 11, "high": 11.1, "low": 10, "close": 10.9},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_OUTSIDE_DOWN", result.patterns)


    
    def test_three_white_soldiers_rejects_excessive_upper_wick(self):
        records = [
            {"open": 100, "high": 112, "low": 99, "close": 111},
            {"open": 110, "high": 127, "low": 109, "close": 121},
            {"open": 120, "high": 132, "low": 119, "close": 131},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_WHITE_SOLDIERS", result.patterns)

    def test_three_black_crows_rejects_excessive_lower_wick(self):
        records = [
            {"open": 130, "high": 131, "low": 118, "close": 119},
            {"open": 120, "high": 121, "low": 102, "close": 109},
            {"open": 110, "high": 111, "low": 98, "close": 99},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_BLACK_CROWS", result.patterns)

    
    # --------------------------------------------------
    # THREE WHITE SOLDIERS / THREE BLACK CROWS
    # --------------------------------------------------

    def test_three_white_soldiers_rejects_excessive_upper_wick(self):
        records = [
            {"open": 100, "high": 112, "low": 99, "close": 111},
            {"open": 110, "high": 130, "low": 109, "close": 121},
            {"open": 120, "high": 132, "low": 119, "close": 131},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_WHITE_SOLDIERS", result.patterns)

    def test_three_black_crows_rejects_excessive_lower_wick(self):
        records = [
            {"open": 130, "high": 131, "low": 118, "close": 119},
            {"open": 120, "high": 121, "low": 100, "close": 109},
            {"open": 110, "high": 111, "low": 98, "close": 99},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_BLACK_CROWS", result.patterns)

    def test_three_white_soldiers_rejects_open_outside_previous_body(self):
        records = [
            {"open": 100, "high": 112, "low": 99, "close": 111},
            {"open": 112, "high": 124, "low": 111, "close": 121},
            {"open": 120, "high": 132, "low": 119, "close": 131},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_WHITE_SOLDIERS", result.patterns)

    def test_three_black_crows_rejects_open_outside_previous_body(self):
        records = [
            {"open": 130, "high": 131, "low": 118, "close": 119},
            {"open": 118, "high": 119, "low": 106, "close": 109},
            {"open": 110, "high": 111, "low": 98, "close": 99},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_BLACK_CROWS", result.patterns)

    # --------------------------------------------------
    # THREE STARS IN THE SOUTH
    # --------------------------------------------------

    def test_three_stars_in_the_south_rejects_bullish_first_candle(self):
        records = [
            {"open": 100, "high": 110, "low": 95, "close": 108},
            {"open": 108, "high": 109, "low": 99, "close": 101},
            {"open": 101, "high": 103, "low": 98, "close": 100},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_STARS_IN_THE_SOUTH", result.patterns)

    def test_three_stars_in_the_south_rejects_higher_third_high(self):
        records = [
            {"open": 110, "high": 112, "low": 95, "close": 98},
            {"open": 98, "high": 101, "low": 96, "close": 97},
            {"open": 97, "high": 102, "low": 96, "close": 98},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("THREE_STARS_IN_THE_SOUTH", result.patterns)

    # --------------------------------------------------
    # THREE LINE STRIKE
    # --------------------------------------------------

    def test_bullish_three_line_strike_rejects_weak_first_candle(self):
        records = [
            {"open": 13, "high": 14, "low": 10, "close": 12},
            {"open": 12.5, "high": 13, "low": 9, "close": 10},
            {"open": 10.5, "high": 11, "low": 7, "close": 8},
            {"open": 7.5, "high": 14, "low": 7, "close": 13.5},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("BULLISH_THREE_LINE_STRIKE", result.patterns)

    def test_bearish_three_line_strike_rejects_weak_final_candle(self):
        records = [
            {"open": 10, "high": 12, "low": 9, "close": 11},
            {"open": 10.5, "high": 13, "low": 10, "close": 12},
            {"open": 11.5, "high": 14, "low": 11, "close": 13},
            {"open": 13.5, "high": 14, "low": 8, "close": 12.5},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("BEARISH_THREE_LINE_STRIKE", result.patterns)

    # --------------------------------------------------
    # MORNING / EVENING STAR
    # --------------------------------------------------

    def test_morning_star_rejects_weak_final_confirmation(self):
        records = [
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 99, "high": 101, "low": 97, "close": 99.5},
            {"open": 99, "high": 106, "low": 98, "close": 104},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("MORNING_STAR", result.patterns)

    def test_evening_star_rejects_weak_final_confirmation(self):
        records = [
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 111, "high": 113, "low": 109, "close": 110.5},
            {"open": 111, "high": 112, "low": 104, "close": 106},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("EVENING_STAR", result.patterns)

    # --------------------------------------------------
    # TASUKI GAP
    # --------------------------------------------------

    def test_upside_tasuki_gap_rejects_missing_gap(self):
        records = [
            {"open": 100, "high": 110, "low": 99, "close": 109},
            {"open": 108, "high": 119, "low": 107, "close": 118},
            {"open": 117, "high": 118, "low": 111, "close": 113},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("UPSIDE_TASUKI_GAP", result.patterns)

    def test_downside_tasuki_gap_rejects_missing_gap(self):
        records = [
            {"open": 120, "high": 121, "low": 109, "close": 110},
            {"open": 111, "high": 112, "low": 99, "close": 100},
            {"open": 101, "high": 107, "low": 100, "close": 106},
        ]

        result = analyze_multi_candle_patterns(records)

        self.assertNotIn("DOWNSIDE_TASUKI_GAP", result.patterns)



if __name__ == "__main__":
    unittest.main()
