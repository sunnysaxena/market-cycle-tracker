import unittest
from datetime import date, datetime
from decimal import Decimal

from app.engines.backtest_config import (
    BacktestConfig,
    BacktestConfigurationError,
)


class TestBacktestConfig(unittest.TestCase):

    def make_config(self, **overrides):
        values = {
            "import_batch_id": 5,
            "instrument_code": "NIFTY50",
        }
        values.update(overrides)
        return BacktestConfig(**values)

    def test_valid_default_configuration(self):
        config = self.make_config()

        self.assertEqual(config.import_batch_id, 5)
        self.assertEqual(config.instrument_code, "NIFTY50")
        self.assertEqual(config.timeframe, "1D")
        self.assertEqual(config.indicator_status_policy, "ALL")
        self.assertEqual(config.execution_policy, "NEXT_BAR_OPEN")
        self.assertEqual(config.slippage_bps, Decimal("0"))
        self.assertIsNone(config.start_date)
        self.assertIsNone(config.end_date)

    def test_normalizes_instrument_code(self):
        config = self.make_config(
            instrument_code="  nifty50  "
        )

        self.assertEqual(config.instrument_code, "NIFTY50")

    def test_accepts_all_supported_price_indices(self):
        for instrument in (
            "NIFTY50",
            "BANKNIFTY",
            "SENSEX",
            "FINNIFTY",
            "MIDCPNIFTY",
        ):
            with self.subTest(instrument=instrument):
                config = self.make_config(
                    instrument_code=instrument
                )
                self.assertEqual(
                    config.instrument_code,
                    instrument,
                )

    def test_rejects_india_vix(self):
        with self.assertRaises(BacktestConfigurationError):
            self.make_config(instrument_code="INDIA_VIX")

    def test_rejects_non_positive_batch_id(self):
        for batch_id in (0, -1, True):
            with self.subTest(batch_id=batch_id):
                with self.assertRaises(
                    BacktestConfigurationError
                ):
                    self.make_config(import_batch_id=batch_id)

    def test_rejects_unsupported_timeframe(self):
        for timeframe in ("5M", "15M", "1W", "1M", "1Y"):
            with self.subTest(timeframe=timeframe):
                with self.assertRaises(
                    BacktestConfigurationError
                ):
                    self.make_config(timeframe=timeframe)

    def test_accepts_valid_date_range(self):
        config = self.make_config(
            start_date=date(2020, 1, 1),
            end_date=date(2026, 10, 30),
        )

        self.assertEqual(
            config.start_date,
            date(2020, 1, 1),
        )
        self.assertEqual(
            config.end_date,
            date(2026, 10, 30),
        )

    def test_rejects_reversed_date_range(self):
        with self.assertRaises(BacktestConfigurationError):
            self.make_config(
                start_date=date(2026, 10, 30),
                end_date=date(2020, 1, 1),
            )

    def test_normalizes_datetime_to_date(self):
        config = self.make_config(
            start_date=datetime(2020, 1, 1, 10, 30),
        )

        self.assertEqual(
            config.start_date,
            date(2020, 1, 1),
        )

    def test_rejects_invalid_date_type(self):
        with self.assertRaises(BacktestConfigurationError):
            self.make_config(start_date="2020-01-01")

    def test_accepts_valid_slippage(self):
        config = self.make_config(slippage_bps="12.5")

        self.assertEqual(
            config.slippage_bps,
            Decimal("12.5"),
        )

    def test_rejects_invalid_slippage(self):
        for value in ("invalid", "-1", "10001", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(
                    BacktestConfigurationError
                ):
                    self.make_config(slippage_bps=value)

    def test_rejects_invalid_indicator_policy(self):
        with self.assertRaises(BacktestConfigurationError):
            self.make_config(
                indicator_status_policy="UNKNOWN"
            )

    def test_accepts_ready_only_indicator_policy(self):
        config = self.make_config(
            indicator_status_policy="READY_ONLY"
        )

        self.assertEqual(
            config.indicator_status_policy,
            "READY_ONLY",
        )

    def test_rejects_invalid_execution_policy(self):
        with self.assertRaises(BacktestConfigurationError):
            self.make_config(
                execution_policy="SAME_CLOSE"
            )

    def test_configuration_is_immutable(self):
        config = self.make_config()

        with self.assertRaises(AttributeError):
            config.instrument_code = "SENSEX"


if __name__ == "__main__":
    unittest.main()
