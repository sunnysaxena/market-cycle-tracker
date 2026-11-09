
from dataclasses import FrozenInstanceError
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.services.api_errors import (
    InstrumentNotFoundError,
    UnsupportedInstrumentCategoryError,
)
from app.services.candlestick_database_service import (
    CandlestickDatabaseCandle,
    CandlestickDatabaseResult,
    _load_eligible_candles,
    _resolve_active_price_index,
    get_candlestick_analysis,
)


class TestCandlestickDatabaseService(TestCase):

    def setUp(self):
        self.session = MagicMock()

        self.index = SimpleNamespace(
            code="NIFTY50",
            category="market_index",
        )

        self.batch = SimpleNamespace(id=5)

        self.daily_rows = [
            {
                "period_start": date(2025, 1, 1),
                "period_end": date(2025, 1, 1),
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 103,
            },
            {
                "period_start": date(2025, 1, 2),
                "period_end": date(2025, 1, 2),
                "open": 103,
                "high": 108,
                "low": 101,
                "close": 107,
            },
        ]

    def _configure_rows(self, rows=None):
        result = MagicMock()
        result.mappings.return_value.all.return_value = (
            self.daily_rows if rows is None else rows
        )
        self.session.execute.return_value = result

    # -----------------------------------------------------
    # INDEX VALIDATION
    # -----------------------------------------------------

    def test_active_index_is_normalized(self):
        self.session.scalar.return_value = self.index

        result = _resolve_active_price_index(
            self.session,
            " nifty50 ",
        )

        self.assertEqual(result, "NIFTY50")

    def test_unsupported_instrument_is_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_active_price_index(
                self.session,
                "INDIA_VIX",
            )

        self.session.scalar.assert_not_called()

    def test_empty_instrument_is_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_active_price_index(
                self.session,
                " ",
            )

        self.session.scalar.assert_not_called()

    def test_non_string_instrument_is_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_active_price_index(
                self.session,
                None,
            )

        self.session.scalar.assert_not_called()

    def test_missing_active_index_is_rejected(self):
        self.session.scalar.return_value = None

        with self.assertRaises(InstrumentNotFoundError):
            _resolve_active_price_index(
                self.session,
                "NIFTY50",
            )

    def test_non_market_index_is_rejected(self):
        self.session.scalar.return_value = SimpleNamespace(
            code="NIFTY50",
            category="other",
        )

        with self.assertRaises(
            UnsupportedInstrumentCategoryError
        ):
            _resolve_active_price_index(
                self.session,
                "NIFTY50",
            )

    # -----------------------------------------------------
    # CANDLE LOADING
    # -----------------------------------------------------

    def test_daily_loader_returns_dated_ohlc_records(self):
        self._configure_rows()

        (
            candles,
            source,
            first_date,
            last_date,
        ) = _load_eligible_candles(
            self.session,
            import_batch_id=5,
            instrument_code="NIFTY50",
            timeframe="1D",
        )

        self.assertEqual(source, "daily_ohlcv")
        self.assertEqual(len(candles), 2)

        self.assertEqual(
            candles[0],
            {
                "period_start": date(2025, 1, 1),
                "period_end": date(2025, 1, 1),
                "open": 100,
                "high": 105,
                "low": 98,
                "close": 103,
            },
        )

        self.assertEqual(first_date, date(2025, 1, 1))
        self.assertEqual(last_date, date(2025, 1, 2))

    def test_daily_loader_filters_accepted_records(self):
        self._configure_rows()

        _load_eligible_candles(
            self.session,
            import_batch_id=5,
            instrument_code="NIFTY50",
            timeframe="1D",
        )

        statement = str(
            self.session.execute.call_args.args[0]
        )

        self.assertIn(
            "quality_status = 'accepted'",
            statement,
        )

    def test_weekly_loader_uses_aggregated_source(self):
        self._configure_rows()

        (
            candles,
            source,
            first_date,
            last_date,
        ) = _load_eligible_candles(
            self.session,
            import_batch_id=5,
            instrument_code="NIFTY50",
            timeframe="1W",
        )

        statement = str(
            self.session.execute.call_args.args[0]
        )

        self.assertEqual(source, "aggregated_ohlcv")
        self.assertEqual(len(candles), 2)

        self.assertIn(
            "period_status = 'completed'",
            statement,
        )
        self.assertIn(
            "boundary_alignment_status = 'aligned'",
            statement,
        )
        self.assertIn(
            "ORDER BY period_start ASC",
            statement,
        )

        self.assertEqual(first_date, date(2025, 1, 1))
        self.assertEqual(last_date, date(2025, 1, 2))

        self.assertEqual(
            candles[0]["period_start"],
            date(2025, 1, 1),
        )
        self.assertEqual(
            candles[0]["period_end"],
            date(2025, 1, 1),
        )

    def test_monthly_loader_uses_aggregated_source(self):
        self._configure_rows()

        result = _load_eligible_candles(
            self.session,
            import_batch_id=5,
            instrument_code="NIFTY50",
            timeframe="1M",
        )

        statement = str(
            self.session.execute.call_args.args[0]
        )

        self.assertEqual(result[1], "aggregated_ohlcv")
        self.assertIn("timeframe = :timeframe", statement)

        params = self.session.execute.call_args.args[1]
        self.assertEqual(params["timeframe"], "1M")

    def test_yearly_loader_uses_aggregated_source(self):
        self._configure_rows()

        result = _load_eligible_candles(
            self.session,
            import_batch_id=5,
            instrument_code="NIFTY50",
            timeframe="1Y",
        )

        params = self.session.execute.call_args.args[1]

        self.assertEqual(result[1], "aggregated_ohlcv")
        self.assertEqual(params["timeframe"], "1Y")

    def test_unsupported_loader_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            _load_eligible_candles(
                self.session,
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe="5M",
            )

        self.session.execute.assert_not_called()

    def test_empty_candle_result_is_rejected(self):
        self._configure_rows(rows=[])

        with self.assertRaises(ValueError):
            _load_eligible_candles(
                self.session,
                import_batch_id=5,
                instrument_code="NIFTY50",
                timeframe="1D",
            )

    # -----------------------------------------------------
    # UNIFIED DATABASE ANALYSIS
    # -----------------------------------------------------

    @patch(
        "app.services.candlestick_database_service.resolve_import_batch"
    )
    @patch(
        "app.services.candlestick_database_service.analyze_candlestick_patterns"
    )
    def test_daily_analysis_returns_metadata_and_dated_candles(
        self,
        mock_analyze,
        mock_resolve_batch,
    ):
        self.session.scalar.return_value = self.index
        self._configure_rows()

        mock_resolve_batch.return_value = self.batch
        mock_analysis = MagicMock()
        mock_analyze.return_value = mock_analysis

        result = get_candlestick_analysis(
            self.session,
            instrument_code=" nifty50 ",
            timeframe="1d",
            import_batch_id=5,
        )

        self.assertIsInstance(
            result,
            CandlestickDatabaseResult,
        )

        self.assertEqual(result.instrument_code, "NIFTY50")
        self.assertEqual(result.timeframe, "1D")
        self.assertEqual(result.import_batch_id, 5)
        self.assertEqual(result.source_table, "daily_ohlcv")
        self.assertEqual(result.candle_count, 2)

        self.assertEqual(
            result.first_period_start,
            date(2025, 1, 1),
        )
        self.assertEqual(
            result.last_period_end,
            date(2025, 1, 2),
        )

        self.assertEqual(len(result.candles), 2)

        first_candle = result.candles[0]

        self.assertIsInstance(
            first_candle,
            CandlestickDatabaseCandle,
        )

        self.assertEqual(
            first_candle.period_start,
            date(2025, 1, 1),
        )
        self.assertEqual(
            first_candle.period_end,
            date(2025, 1, 1),
        )
        self.assertEqual(first_candle.open, 100)
        self.assertEqual(first_candle.high, 105)
        self.assertEqual(first_candle.low, 98)
        self.assertEqual(first_candle.close, 103)

        self.assertIs(result.analysis, mock_analysis)

        mock_resolve_batch.assert_called_once_with(
            self.session,
            import_batch_id=5,
        )

        # The analysis engine must receive OHLC only.
        mock_analyze.assert_called_once_with(
            [
                {
                    "open": 100,
                    "high": 105,
                    "low": 98,
                    "close": 103,
                },
                {
                    "open": 103,
                    "high": 108,
                    "low": 101,
                    "close": 107,
                },
            ]
        )

        # One index lookup and one candle-loading query.
        self.assertEqual(self.session.execute.call_count, 1)

    def test_analysis_preserves_all_candle_dates_in_order(self):
        self.session.scalar.return_value = self.index
        self._configure_rows()

        with patch(
            "app.services.candlestick_database_service.resolve_import_batch",
            return_value=self.batch,
        ), patch(
            "app.services.candlestick_database_service.analyze_candlestick_patterns",
        ):
            result = get_candlestick_analysis(
                self.session,
                instrument_code="NIFTY50",
                timeframe="1D",
                import_batch_id=5,
            )

        self.assertEqual(
            [
                candle.period_start
                for candle in result.candles
            ],
            [
                date(2025, 1, 1),
                date(2025, 1, 2),
            ],
        )

    def test_invalid_timeframe_is_rejected_before_database_access(
        self,
    ):
        with self.assertRaises(ValueError):
            get_candlestick_analysis(
                self.session,
                instrument_code="NIFTY50",
                timeframe="5M",
            )

        self.session.scalar.assert_not_called()
        self.session.execute.assert_not_called()

    def test_empty_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            get_candlestick_analysis(
                self.session,
                instrument_code="NIFTY50",
                timeframe=" ",
            )

        self.session.scalar.assert_not_called()

    # -----------------------------------------------------
    # RESULT IMMUTABILITY
    # -----------------------------------------------------

    def test_result_is_immutable(self):
        result = CandlestickDatabaseResult(
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            source_table="daily_ohlcv",
            candle_count=1,
            first_period_start=date(2025, 1, 1),
            last_period_end=date(2025, 1, 1),
            candles=(),
            analysis=MagicMock(),
        )

        with self.assertRaises(FrozenInstanceError):
            result.candle_count = 10

    def test_database_candle_is_immutable(self):
        candle = CandlestickDatabaseCandle(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 1),
            open=100,
            high=105,
            low=98,
            close=103,
        )

        with self.assertRaises(FrozenInstanceError):
            candle.close = 110

    def test_result_candles_are_stored_as_tuple(self):
        result = CandlestickDatabaseResult(
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            source_table="daily_ohlcv",
            candle_count=1,
            first_period_start=date(2025, 1, 1),
            last_period_end=date(2025, 1, 1),
            candles=(),
            analysis=MagicMock(),
        )

        self.assertIsInstance(result.candles, tuple)


if __name__ == "__main__":
    import unittest
    unittest.main()
