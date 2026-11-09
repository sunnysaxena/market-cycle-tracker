import unittest
from dataclasses import replace
from decimal import Decimal

from app.engines.candlestick_pattern_config import (
    CALCULATION_VERSION,
    DEFAULT_PATTERN_CONFIG,
)
from app.engines.candlestick_pattern_engine import (
    CandlestickPatternError,
    analyze_candle,
    calculate_candle_geometry, analyze_two_candle_patterns
)


class TestCandlestickPatternEngine(unittest.TestCase):

    def check_pattern(self, candle, expected_pattern):
        result = analyze_candle(candle)
        self.assertIn(expected_pattern, result.patterns)

    # --------------------------------------------------
    # DOJI FAMILY
    # --------------------------------------------------

    def test_doji(self):
        self.check_pattern(
            {"open": 100, "high": 102, "low": 98, "close": 100.1},
            "DOJI",
        )

    def test_long_legged_doji(self):
        self.check_pattern(
            {"open": 100, "high": 104, "low": 96, "close": 100.1},
            "LONG_LEGGED_DOJI",
        )

    def test_dragonfly_doji(self):
        self.check_pattern(
            {"open": 100, "high": 100.1, "low": 96, "close": 100.05},
            "DRAGONFLY_DOJI",
        )

    def test_gravestone_doji(self):
        self.check_pattern(
            {"open": 100, "high": 104, "low": 99.9, "close": 99.95},
            "GRAVESTONE_DOJI",
        )

    def test_four_price_doji(self):
        result = analyze_candle(
            {"open": 100, "high": 100, "low": 100, "close": 100}
        )

        self.assertEqual(result.patterns, ("FOUR_PRICE_DOJI",))
        self.assertEqual(result.geometry.total_range, Decimal("0"))

    # --------------------------------------------------
    # SPINNING TOP AND HIGH-WAVE
    # --------------------------------------------------

    def test_spinning_top(self):
        self.check_pattern(
            {"open": 100, "high": 103, "low": 97, "close": 101.5},
            "SPINNING_TOP",
        )

    def test_high_wave_candle(self):
        self.check_pattern(
            {"open": 100, "high": 104, "low": 96, "close": 100.5},
            "HIGH_WAVE_CANDLE",
        )

    # --------------------------------------------------
    # HAMMER SHAPES
    # --------------------------------------------------

    def test_hammer_shape(self):
        self.check_pattern(
            {"open": 102, "high": 103.2, "low": 99, "close": 103},
            "HAMMER_SHAPE",
        )

    def test_inverted_hammer_shape(self):
        self.check_pattern(
            {"open": 102, "high": 106, "low": 101.8, "close": 103},
            "INVERTED_HAMMER_SHAPE",
        )

    # --------------------------------------------------
    # MARUBOZU
    # --------------------------------------------------

    def test_bullish_marubozu(self):
        self.check_pattern(
            {"open": 100, "high": 109.2, "low": 99.8, "close": 109},
            "BULLISH_MARUBOZU",
        )

    def test_bearish_marubozu(self):
        self.check_pattern(
            {"open": 109, "high": 109.2, "low": 99.8, "close": 100},
            "BEARISH_MARUBOZU",
        )

    # --------------------------------------------------
    # LONG-WICK CANDLES
    # --------------------------------------------------

    def test_long_lower_wick_candle(self):
        self.check_pattern(
            {"open": 103, "high": 105, "low": 99, "close": 104},
            "LONG_LOWER_WICK_CANDLE",
        )

    def test_long_upper_wick_candle(self):
        self.check_pattern(
            {"open": 100, "high": 105, "low": 99, "close": 101},
            "LONG_UPPER_WICK_CANDLE",
        )

    # --------------------------------------------------
    # GEOMETRY
    # --------------------------------------------------

    def test_bullish_direction(self):
        geometry = calculate_candle_geometry(
            {"open": 100, "high": 105, "low": 99, "close": 104}
        )

        self.assertEqual(geometry.direction, "BULLISH")

    def test_bearish_direction(self):
        geometry = calculate_candle_geometry(
            {"open": 104, "high": 105, "low": 99, "close": 100}
        )

        self.assertEqual(geometry.direction, "BEARISH")

    def test_neutral_direction(self):
        geometry = calculate_candle_geometry(
            {"open": 100, "high": 105, "low": 95, "close": 100}
        )

        self.assertEqual(geometry.direction, "NEUTRAL")

    def test_decimal_geometry(self):
        geometry = calculate_candle_geometry(
            {
                "open": "100.25",
                "high": "105.50",
                "low": "99.75",
                "close": "104.25",
            }
        )

        self.assertIsInstance(geometry.open, Decimal)
        self.assertEqual(geometry.open, Decimal("100.25"))

    # --------------------------------------------------
    # INVALID OHLC
    # --------------------------------------------------

    def test_missing_open(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"high": 105, "low": 95, "close": 100}
            )

    def test_high_below_low(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": 100, "high": 95, "low": 98, "close": 99}
            )

    def test_high_below_close(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": 100, "high": 102, "low": 95, "close": 105}
            )

    def test_low_above_open(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": 95, "high": 105, "low": 100, "close": 102}
            )

    def test_zero_price(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": 0, "high": 105, "low": 95, "close": 100}
            )

    def test_non_finite_price(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": "NaN", "high": 105, "low": 95, "close": 100}
            )

    # --------------------------------------------------
    # CONFIGURATION AND RESULT
    # --------------------------------------------------

    def test_custom_configuration(self):
        config = replace(
            DEFAULT_PATTERN_CONFIG,
            doji_max_body_ratio=Decimal("0.20"),
        )

        result = analyze_candle(
            {"open": 100, "high": 105, "low": 95, "close": 101.5},
            config,
        )

        self.assertIn("DOJI", result.patterns)

    def test_calculation_version(self):
        result = analyze_candle(
            {"open": 100, "high": 105, "low": 95, "close": 104}
        )

        self.assertEqual(
            result.calculation_version,
            CALCULATION_VERSION,
        )

    def test_high_wave_is_not_also_spinning_top(self):
        result = analyze_candle(
            {"open": 100, "high": 104, "low": 96, "close": 100.5}
        )

        self.assertIn("HIGH_WAVE_CANDLE", result.patterns)
        self.assertEqual(
            result.patterns.count("HIGH_WAVE_CANDLE"),
            1,
        )
        self.assertNotIn("SPINNING_TOP", result.patterns)

    def test_invalid_record_type(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(None)

    def test_invalid_config_type(self):
        with self.assertRaises(CandlestickPatternError):
            analyze_candle(
                {"open": 100, "high": 105, "low": 95, "close": 104},
                config="invalid",
            )

    def test_bullish_engulfing(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 99, "high": 107, "low": 98, "close": 106},
        )
        self.assertIn("BULLISH_ENGULFING", result.patterns)

    def test_bearish_engulfing(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 106, "high": 107, "low": 98, "close": 99},
        )
        self.assertIn("BEARISH_ENGULFING", result.patterns)

    def test_bullish_harami(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 103, "high": 105, "low": 102, "close": 104},
        )
        self.assertIn("BULLISH_HARAMI", result.patterns)

    def test_bearish_harami(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 111, "low": 99, "close": 110},
            {"open": 107, "high": 108, "low": 105, "close": 106},
        )
        self.assertIn("BEARISH_HARAMI", result.patterns)
    
    def test_harami_cross(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 111, "low": 99, "close": 100},
            {"open": 104, "high": 105, "low": 103, "close": 104},
        )
        self.assertIn("BULLISH_HARAMI_CROSS", result.patterns)

    def test_bearish_harami_cross(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 111, "low": 99, "close": 110},
            {"open": 106, "high": 107, "low": 105, "close": 106},
        )
        self.assertIn("BEARISH_HARAMI_CROSS", result.patterns)

    # --------------------------------------------------
    # PIERCING LINE
    # --------------------------------------------------

    def test_piercing_line(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 111, "low": 98, "close": 100},
            {"open": 97, "high": 107, "low": 96, "close": 106},
        )

        self.assertIn("PIERCING_LINE", result.patterns)

    def test_piercing_line_rejected_without_enough_penetration(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 111, "low": 98, "close": 100},
            {"open": 97, "high": 105, "low": 96, "close": 104},
        )

        self.assertNotIn("PIERCING_LINE", result.patterns)

    # --------------------------------------------------
    # DARK CLOUD COVER
    # --------------------------------------------------

    def test_dark_cloud_cover(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 112, "low": 99, "close": 110},
            {"open": 113, "high": 114, "low": 103, "close": 104},
        )

        self.assertIn("DARK_CLOUD_COVER", result.patterns)

    def test_dark_cloud_cover_rejected_without_enough_penetration(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 112, "low": 99, "close": 110},
            {"open": 113, "high": 114, "low": 105, "close": 106},
        )

        self.assertNotIn("DARK_CLOUD_COVER", result.patterns)

    # --------------------------------------------------
    # TWEEZER BOTTOM
    # --------------------------------------------------

    def test_tweezer_bottom(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 101, "high": 106, "low": 99.1, "close": 105},
        )

        self.assertIn("TWEEZER_BOTTOM", result.patterns)

    def test_tweezer_bottom_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 101, "high": 106, "low": 99.5, "close": 105},
        )

        self.assertNotIn("TWEEZER_BOTTOM", result.patterns)

    # --------------------------------------------------
    # TWEEZER TOP
    # --------------------------------------------------

    def test_tweezer_top(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 104, "high": 106.1, "low": 99, "close": 100},
        )

        self.assertIn("TWEEZER_TOP", result.patterns)

    def test_tweezer_top_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 104, "high": 106.5, "low": 99, "close": 100},
        )

        self.assertNotIn("TWEEZER_TOP", result.patterns)
 
    def test_tweezer_bottom_accepts_exact_tolerance_boundary(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 101, "high": 106, "low": 99.35, "close": 105},
        )

        self.assertIn("TWEEZER_BOTTOM", result.patterns)

    def test_tweezer_top_accepts_exact_tolerance_boundary(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 104, "high": 106.35, "low": 99, "close": 100},
        )

        self.assertIn("TWEEZER_TOP", result.patterns)


    # --------------------------------------------------
    # BULLISH / BEARISH KICKER
    # --------------------------------------------------

    def test_bullish_kicker(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 106, "high": 110, "low": 105.5, "close": 109},
        )

        self.assertIn("BULLISH_KICKER", result.patterns)

    def test_bearish_kicker(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 99, "high": 99.5, "low": 95, "close": 96},
        )

        self.assertIn("BEARISH_KICKER", result.patterns)

    def test_bullish_kicker_rejected_without_sufficient_gap(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 105.5, "high": 110, "low": 105.2, "close": 109},
        )

        self.assertNotIn("BULLISH_KICKER", result.patterns)

    def test_bearish_kicker_rejected_without_sufficient_gap(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 99.5, "high": 99.8, "low": 95, "close": 96},
        )

        self.assertNotIn("BEARISH_KICKER", result.patterns)

    
    def test_bullish_kicker_accepts_exact_gap_threshold(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 105.7, "high": 110, "low": 105.5, "close": 109},
        )

        self.assertIn("BULLISH_KICKER", result.patterns)

    def test_bearish_kicker_accepts_exact_gap_threshold(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 99.3, "high": 99.5, "low": 95, "close": 96},
        )

        self.assertIn("BEARISH_KICKER", result.patterns)

    
    # --------------------------------------------------
    
    # BULLISH / BEARISH MEETING LINES
    # --------------------------------------------------

    def test_bullish_meeting_lines(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 99, "high": 108, "low": 97, "close": 100.2},
        )

        self.assertIn("BULLISH_MEETING_LINES", result.patterns)

    def test_bearish_meeting_lines(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 111, "high": 113, "low": 99, "close": 109.8},
        )

        self.assertIn("BEARISH_MEETING_LINES", result.patterns)

    def test_bullish_meeting_lines_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 99, "high": 108, "low": 97, "close": 101},
        )

        self.assertNotIn("BULLISH_MEETING_LINES", result.patterns)

    def test_bearish_meeting_lines_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 111, "high": 113, "low": 99, "close": 109},
        )

        self.assertNotIn("BEARISH_MEETING_LINES", result.patterns)

        # --------------------------------------------------
    
    # BULLISH / BEARISH SEPARATING LINES
    # --------------------------------------------------

    def test_bullish_separating_lines(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 105.1, "high": 112, "low": 104, "close": 111},
        )

        self.assertIn("BULLISH_SEPARATING_LINES", result.patterns)

    def test_bearish_separating_lines(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 100.1, "high": 101, "low": 93, "close": 94},
        )

        self.assertIn("BEARISH_SEPARATING_LINES", result.patterns)

    def test_bullish_separating_lines_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 105.5, "high": 112, "low": 104, "close": 111},
        )

        self.assertNotIn("BULLISH_SEPARATING_LINES", result.patterns)

    def test_bearish_separating_lines_rejected_outside_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 100.5, "high": 101, "low": 93, "close": 94},
        )

        self.assertNotIn("BEARISH_SEPARATING_LINES", result.patterns)


    
    def test_bullish_meeting_lines_accepts_exact_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 99, "high": 108, "low": 97, "close": 100.7},
        )

        self.assertIn("BULLISH_MEETING_LINES", result.patterns)

    def test_bearish_meeting_lines_accepts_exact_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 112, "low": 98, "close": 110},
            {"open": 111, "high": 113, "low": 99, "close": 109.3},
        )

        self.assertIn("BEARISH_MEETING_LINES", result.patterns)

    def test_bullish_separating_lines_accepts_exact_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 105, "high": 106, "low": 99, "close": 100},
            {"open": 105.35, "high": 112, "low": 104, "close": 111},
        )

        self.assertIn("BULLISH_SEPARATING_LINES", result.patterns)

    def test_bearish_separating_lines_accepts_exact_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 106, "low": 99, "close": 105},
            {"open": 100.35, "high": 101, "low": 93, "close": 94},
        )

        self.assertIn("BEARISH_SEPARATING_LINES", result.patterns)


    # --------------------------------------------------
    # ON-NECK / IN-NECK / THRUSTING
    # --------------------------------------------------
    
    def test_on_neck(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 100, "low": 96, "close": 98.1},
        )

        self.assertIn("ON_NECK", result.patterns)

    def test_in_neck(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 102, "low": 96, "close": 100.2},
        )

        self.assertIn("IN_NECK", result.patterns)

    def test_thrusting(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 104, "low": 96, "close": 103},
        )

        self.assertIn("THRUSTING", result.patterns)

    def test_on_neck_rejected_when_close_is_below_previous_low(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 98.5, "low": 96, "close": 97.9},
        )

        self.assertNotIn("ON_NECK", result.patterns)

    def test_in_neck_rejected_when_close_is_below_previous_close(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 100, "low": 96, "close": 99.9},
        )

        self.assertNotIn("IN_NECK", result.patterns)

    def test_thrusting_rejected_when_close_is_within_in_neck_tolerance(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 101, "low": 96, "close": 100.5},
        )

        self.assertIn("IN_NECK", result.patterns)
        self.assertNotIn("THRUSTING", result.patterns)

    def test_on_neck_rejected_when_open_does_not_gap_below_low(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 98, "high": 101, "low": 97, "close": 98.1},
        )

        self.assertNotIn("ON_NECK", result.patterns)

    def test_in_neck_rejected_when_previous_body_is_too_small(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 105},
            {"open": 97, "high": 107, "low": 96, "close": 105.1},
        )

        self.assertNotIn("IN_NECK", result.patterns)

    def test_thrusting_rejected_when_close_exceeds_midpoint(self):
        result = analyze_two_candle_patterns(
            {"open": 110, "high": 112, "low": 98, "close": 100},
            {"open": 97, "high": 107, "low": 96, "close": 106},
        )

        self.assertNotIn("THRUSTING", result.patterns)

    def test_equal_body_boundaries_not_classified_as_engulfing_or_harami(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 101, "low": 89, "close": 90},
            {"open": 90, "high": 101, "low": 89, "close": 100},
        )

        self.assertNotIn("BULLISH_ENGULFING", result.patterns)
        self.assertNotIn("BULLISH_HARAMI", result.patterns)


    def test_strict_bullish_engulfing_is_recognized(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 101, "low": 89, "close": 90},
            {"open": 89, "high": 102, "low": 88, "close": 101},
        )

        self.assertIn("BULLISH_ENGULFING", result.patterns)

    def test_strict_bearish_engulfing_is_recognized(self):
        result = analyze_two_candle_patterns(
            {"open": 90, "high": 101, "low": 89, "close": 100},
            {"open": 101, "high": 102, "low": 88, "close": 89},
        )

        self.assertIn("BEARISH_ENGULFING", result.patterns)

    def test_equal_body_boundaries_not_classified_as_harami(self):
        result = analyze_two_candle_patterns(
            {"open": 100, "high": 101, "low": 89, "close": 90},
            {"open": 90, "high": 101, "low": 89, "close": 100},
        )

        self.assertNotIn("BULLISH_HARAMI", result.patterns)

    
    def test_doji_accepts_exact_body_ratio_boundary(self):
        result = analyze_candle(
            {"open": 100, "high": 110, "low": 90, "close": 102}
        )

        self.assertIn("DOJI", result.patterns)


    def test_doji_rejected_above_body_ratio_boundary(self):
        result = analyze_candle(
            {"open": 100, "high": 110, "low": 90, "close": 102.1}
        )
        self.assertNotIn("DOJI", result.patterns)

    def test_inverted_hammer_accepts_exact_upper_wick_body_ratio(self):
        result = analyze_candle(
            {"open": 102, "high": 105, "low": 101.99, "close": 103}
        )

        self.assertIn("INVERTED_HAMMER_SHAPE", result.patterns)


    def test_inverted_hammer_rejected_below_upper_wick_body_ratio(self):
        result = analyze_candle(
            {"open": 102, "high": 104.99, "low": 101.99, "close": 103}
        )

        self.assertNotIn("INVERTED_HAMMER_SHAPE", result.patterns)


if __name__ == "__main__":
    unittest.main()
