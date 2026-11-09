
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.services.candlestick_analysis_service import (
    CandlestickAnalysisResult,
    IndexedSingleCandleResult,
    TwoCandlePatternMatch,
)
from app.engines.candlestick_multi_candle_engine import (
    MultiCandlePatternMatch,
)
from app.services.candlestick_database_service import (
    CandlestickDatabaseCandle,
    NoEligibleCandlesError,
)
from app.services.candlestick_query_service import (
    get_candlestick_patterns,
)


class TestCandlestickQueryService(TestCase):

    def setUp(self):
        self.db = MagicMock()

        self.batch = SimpleNamespace(
            id=5,
            status="completed",
            imported_rows=100,
            imported_at_utc=None,
        )

        self.candles = (
            CandlestickDatabaseCandle(
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 1),
                open=100,
                high=105,
                low=98,
                close=103,
            ),
            CandlestickDatabaseCandle(
                period_start=date(2025, 1, 2),
                period_end=date(2025, 1, 2),
                open=103,
                high=108,
                low=101,
                close=107,
            ),
            CandlestickDatabaseCandle(
                period_start=date(2025, 1, 3),
                period_end=date(2025, 1, 3),
                open=107,
                high=110,
                low=104,
                close=105,
            ),
        )

        self.analysis = CandlestickAnalysisResult(
            candle_count=3,
            single_candle_calculation_version="single_v1",
            two_candle_calculation_version="two_v1",
            multi_candle_calculation_version="multi_v1",
            single_candle_results=(
                IndexedSingleCandleResult(
                    candle_index=0,
                    result=SimpleNamespace(patterns=("DOJI",)),
                ),
                IndexedSingleCandleResult(
                    candle_index=1,
                    result=SimpleNamespace(patterns=("HAMMER",)),
                ),
                IndexedSingleCandleResult(
                    candle_index=2,
                    result=SimpleNamespace(patterns=()),
                ),
            ),
            two_candle_matches=(
                TwoCandlePatternMatch(
                    pattern="BULLISH_ENGULFING",
                    start_index=0,
                    end_index=1,
                ),
            ),
            multi_candle_matches=(
                MultiCandlePatternMatch(
                    pattern="MORNING_STAR",
                    candle_count=3,
                    start_index=0,
                    end_index=2,
                ),
            ),
        )

        self.database_result = SimpleNamespace(
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            source_table="daily_ohlcv",
            candle_count=3,
            first_period_start=date(2025, 1, 1),
            last_period_end=date(2025, 1, 3),
            candles=self.candles,
            analysis=self.analysis,
        )

    def _patch_services(self):
        batch_patch = patch(
            "app.services.candlestick_query_service.resolve_import_batch",
            return_value=self.batch,
        )

        database_patch = patch(
            "app.services.candlestick_query_service.get_candlestick_analysis",
            return_value=self.database_result,
        )

        return batch_patch, database_patch

    # --------------------------------------------------
    # BASIC RESPONSE
    # --------------------------------------------------

    def test_returns_candlestick_analysis_response(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code=" nifty50 ",
                timeframe="1d",
            )

        self.assertEqual(result.instrument_code, "NIFTY50")
        self.assertEqual(result.timeframe, "1D")
        self.assertEqual(result.source_table, "daily_ohlcv")
        self.assertEqual(result.batch.import_batch_id, 5)

        self.assertEqual(result.pagination.total_records, 3)
        self.assertEqual(result.pagination.returned_count, 3)

        self.assertEqual(len(result.candles), 3)
        self.assertEqual(result.availability.status, "available")

    def test_single_candle_patterns_are_attached_to_correct_candles(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
            )

        self.assertEqual(result.candles[0].patterns, ["DOJI"])
        self.assertEqual(result.candles[1].patterns, ["HAMMER"])
        self.assertEqual(result.candles[2].patterns, [])

    # --------------------------------------------------
    # DATE FILTERING
    # --------------------------------------------------

    def test_date_filtering_preserves_original_indices(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                start_date=date(2025, 1, 2),
                end_date=date(2025, 1, 3),
            )

        self.assertEqual(
            [candle.candle_index for candle in result.candles],
            [1, 2],
        )

        self.assertEqual(result.pagination.total_records, 2)

    def test_no_records_in_date_range(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                start_date=date(2026, 1, 1),
            )

        self.assertEqual(result.candles, [])
        self.assertEqual(result.pagination.total_records, 0)
        self.assertEqual(
            result.availability.status,
            "no_records_in_range",
        )
        self.assertFalse(result.availability.is_available)

    # --------------------------------------------------
    # PAGINATION AND PATTERN BOUNDARIES
    # --------------------------------------------------

    def test_pagination_preserves_original_candle_indices(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                limit=1,
                offset=1,
            )

        self.assertEqual(len(result.candles), 1)
        self.assertEqual(result.candles[0].candle_index, 1)
        self.assertEqual(result.pagination.total_records, 3)
        self.assertEqual(result.pagination.returned_count, 1)

    def test_patterns_spanning_previous_page_are_preserved(self):
        batch_patch, database_patch = self._patch_services()

        with batch_patch, database_patch:
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                limit=2,
                offset=1,
            )

        self.assertEqual(
            [candle.candle_index for candle in result.candles],
            [1, 2],
        )

        self.assertEqual(len(result.two_candle_patterns), 1)

        two_pattern = result.two_candle_patterns[0]

        self.assertEqual(two_pattern.pattern, "BULLISH_ENGULFING")
        self.assertEqual(two_pattern.start_index, 0)
        self.assertEqual(two_pattern.end_index, 1)

        self.assertEqual(len(result.multi_candle_patterns), 1)

        multi_pattern = result.multi_candle_patterns[0]

        self.assertEqual(multi_pattern.pattern, "MORNING_STAR")
        self.assertEqual(multi_pattern.start_index, 0)
        self.assertEqual(multi_pattern.end_index, 2)

    # --------------------------------------------------
    # EMPTY DATASET
    # --------------------------------------------------

    def test_empty_dataset_returns_no_data_response(self):
        batch_patch, _ = self._patch_services()

        with batch_patch, patch(
            "app.services.candlestick_query_service.get_candlestick_analysis",
            side_effect=NoEligibleCandlesError(
                "No eligible candles were found."
            ),
        ):
            result = get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
            )

        self.assertEqual(result.candles, [])
        self.assertEqual(result.two_candle_patterns, [])
        self.assertEqual(result.multi_candle_patterns, [])

        self.assertEqual(result.pagination.total_records, 0)
        self.assertEqual(result.availability.status, "no_data")
        self.assertFalse(result.availability.is_available)

        self.assertIsNone(result.first_period_start)
        self.assertIsNone(result.last_period_end)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaises(ValueError):
            get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                start_date=date(2025, 1, 3),
                end_date=date(2025, 1, 1),
            )

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                limit=2001,
            )

    def test_negative_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="1D",
                offset=-1,
            )

    def test_unsupported_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            get_candlestick_patterns(
                self.db,
                instrument_code="NIFTY50",
                timeframe="5M",
            )


if __name__ == "__main__":
    import unittest
    unittest.main()
