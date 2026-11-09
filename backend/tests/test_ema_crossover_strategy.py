import unittest
from datetime import date
from decimal import Decimal

from app.engines.backtest_strategy import (
    OpenPositionContext,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
)
from app.strategies.ema_crossover import EmaCrossoverStrategy


def make_candle(
    day,
    *,
    ema9,
    ema20,
):
    return {
        "candle_date": date(2026, 1, day),
        "ema_9": ema9,
        "ema_20": ema20,
    }


def make_context(day, position=None):
    return StrategyContext(
        current_date=date(2026, 1, day),
        current_close=Decimal("100"),
        position=position,
    )


def make_position(side):
    return OpenPositionContext(
        side=side,
        entry_date=date(2026, 1, 1),
        entry_reference_price=Decimal("100"),
        entry_fill_price=Decimal("100"),
        quantity=Decimal("1"),
        stop_loss=None,
        take_profit=None,
        entry_reason="Test entry",
    )


class TestEmaCrossoverStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = EmaCrossoverStrategy()

    def test_strategy_name(self):
        self.assertEqual(
            self.strategy.name,
            "EMA 9/20 Crossover",
        )

    def test_custom_periods(self):
        strategy = EmaCrossoverStrategy(
            fast_period=20,
            slow_period=50,
        )

        self.assertEqual(
            strategy.name,
            "EMA 20/50 Crossover",
        )

    def test_bullish_crossover_enters_long(self):
        history = (
            make_candle(1, ema9="99", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(2),
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.LONG)
        self.assertIn("Bullish", signal.reason)

    def test_bearish_crossover_enters_short(self):
        history = (
            make_candle(1, ema9="101", ema20="100"),
            make_candle(2, ema9="99", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(2),
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.SHORT)
        self.assertIn("Bearish", signal.reason)

    def test_bearish_crossover_reverses_long_to_short(self):
        history = (
            make_candle(1, ema9="101", ema20="100"),
            make_candle(2, ema9="99", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(
                2,
                make_position(PositionSide.LONG),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.SHORT)
        self.assertIn("reverses LONG to SHORT", signal.reason)

    def test_bullish_crossover_reverses_short_to_long(self):
        history = (
            make_candle(1, ema9="99", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(
                2,
                make_position(PositionSide.SHORT),
            ),
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.LONG)
        self.assertIn("reverses SHORT to LONG", signal.reason)

    def test_no_crossover_returns_no_signal(self):
        history = (
            make_candle(1, ema9="102", ema20="100"),
            make_candle(2, ema9="103", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(2),
        )

        self.assertIsNone(signal)

    def test_insufficient_history_returns_no_signal(self):
        history = (
            make_candle(1, ema9="99", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(1),
        )

        self.assertIsNone(signal)

    def test_missing_ema_returns_no_signal(self):
        history = (
            make_candle(1, ema9=None, ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        signal = self.strategy.generate_signal(
            history,
            make_context(2),
        )

        self.assertIsNone(signal)

    def test_non_finite_ema_is_rejected(self):
        history = (
            make_candle(1, ema9="NaN", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        with self.assertRaises(StrategyContractError):
            self.strategy.generate_signal(
                history,
                make_context(2),
            )

    def test_invalid_periods_are_rejected(self):
        invalid_values = (0, -1, True)

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    EmaCrossoverStrategy(
                        fast_period=value,
                        slow_period=20,
                    )

    def test_fast_period_must_be_smaller(self):
        with self.assertRaises(ValueError):
            EmaCrossoverStrategy(
                fast_period=20,
                slow_period=9,
            )

    def test_long_only_ignores_bearish_entry_when_flat(self):
        strategy = EmaCrossoverStrategy(trade_mode="LONG_ONLY")

        history = (
            make_candle(1, ema9="101", ema20="100"),
            make_candle(2, ema9="99", ema20="100"),
        )

        self.assertIsNone(
            strategy.generate_signal(history, make_context(2))
        )

    def test_long_only_exits_without_opening_short(self):
        strategy = EmaCrossoverStrategy(trade_mode="LONG_ONLY")

        history = (
            make_candle(1, ema9="101", ema20="100"),
            make_candle(2, ema9="99", ema20="100"),
        )

        signal = strategy.generate_signal(
            history,
            make_context(2, make_position(PositionSide.LONG)),
        )

        self.assertIs(signal.action, SignalAction.EXIT)
        self.assertIs(signal.side, PositionSide.LONG)

    def test_short_only_ignores_bullish_entry_when_flat(self):
        strategy = EmaCrossoverStrategy(trade_mode="SHORT_ONLY")

        history = (
            make_candle(1, ema9="99", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        self.assertIsNone(
            strategy.generate_signal(history, make_context(2))
        )

    def test_short_only_exits_without_opening_long(self):
        strategy = EmaCrossoverStrategy(trade_mode="SHORT_ONLY")

        history = (
            make_candle(1, ema9="99", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        signal = strategy.generate_signal(
            history,
            make_context(2, make_position(PositionSide.SHORT)),
        )

        self.assertIs(signal.action, SignalAction.EXIT)
        self.assertIs(signal.side, PositionSide.SHORT)

    def test_trade_mode_is_validated_and_normalized(self):
        strategy = EmaCrossoverStrategy(trade_mode=" long_only ")

        self.assertEqual(strategy.trade_mode, "LONG_ONLY")
        self.assertIn("LONG_ONLY", strategy.name)

        with self.assertRaises(ValueError):
            EmaCrossoverStrategy(trade_mode="INVALID")

    def test_both_mode_remains_default(self):
        strategy = EmaCrossoverStrategy()

        self.assertEqual(strategy.trade_mode, "BOTH")
        self.assertEqual(strategy.name, "EMA 9/20 Crossover")


    def test_context_date_must_match_latest_candle(self):
        history = (
            make_candle(1, ema9="99", ema20="100"),
            make_candle(2, ema9="101", ema20="100"),
        )

        with self.assertRaises(StrategyContractError):
            self.strategy.generate_signal(
                history,
                make_context(3),
            )


if __name__ == "__main__":
    unittest.main()
