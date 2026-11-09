import unittest
from datetime import date
from decimal import Decimal

from app.engines.backtest_strategy import (
    BacktestStrategy,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)


class ExampleStrategy(BacktestStrategy):

    @property
    def name(self):
        return "Example Test Strategy"

    def generate_signal(self, history, context):
        if not history:
            return None

        if history[-1].get("direction") == "BULLISH":
            return TradeSignal(
                action=SignalAction.ENTER,
                side=PositionSide.LONG,
                reason="Bullish test signal",
            )

        return None


class TestTradeSignal(unittest.TestCase):

    def test_valid_long_entry(self):
        signal = TradeSignal(
            action=SignalAction.ENTER,
            side=PositionSide.LONG,
            reason="Bullish trend",
        )

        self.assertEqual(signal.action, SignalAction.ENTER)
        self.assertEqual(signal.side, PositionSide.LONG)
        self.assertEqual(signal.reason, "Bullish trend")

    def test_valid_short_entry(self):
        signal = TradeSignal(
            action=SignalAction.ENTER,
            side=PositionSide.SHORT,
            reason="Bearish trend",
        )

        self.assertEqual(signal.side, PositionSide.SHORT)

    def test_accepts_string_enum_values(self):
        signal = TradeSignal(
            action="ENTER",
            side="LONG",
            reason="Test signal",
        )

        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.LONG)

    def test_normalizes_stop_loss_and_target_to_decimal(self):
        signal = TradeSignal(
            action="ENTER",
            side="LONG",
            reason="Risk-managed entry",
            stop_loss="22500.50",
            take_profit="23000",
        )

        self.assertEqual(
            signal.stop_loss,
            Decimal("22500.50"),
        )
        self.assertEqual(
            signal.take_profit,
            Decimal("23000"),
        )

    def test_accepts_valid_exit_signal(self):
        signal = TradeSignal(
            action="EXIT",
            side="LONG",
            reason="Exit condition reached",
        )

        self.assertIs(signal.action, SignalAction.EXIT)
        self.assertIs(signal.side, PositionSide.LONG)

    def test_rejects_invalid_action(self):
        with self.assertRaises(StrategyContractError):
            TradeSignal(
                action="BUY",
                side="LONG",
                reason="Invalid action",
            )

    def test_rejects_invalid_position_side(self):
        with self.assertRaises(StrategyContractError):
            TradeSignal(
                action="ENTER",
                side="NEUTRAL",
                reason="Invalid side",
            )

    def test_rejects_empty_reason(self):
        with self.assertRaises(StrategyContractError):
            TradeSignal(
                action="ENTER",
                side="LONG",
                reason="   ",
            )

    def test_rejects_invalid_stop_loss(self):
        for value in ("invalid", "0", "-100", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(StrategyContractError):
                    TradeSignal(
                        action="ENTER",
                        side="LONG",
                        reason="Invalid stop",
                        stop_loss=value,
                    )

    def test_rejects_invalid_take_profit(self):
        for value in ("invalid", "0", "-100", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(StrategyContractError):
                    TradeSignal(
                        action="ENTER",
                        side="LONG",
                        reason="Invalid target",
                        take_profit=value,
                    )

    def test_exit_cannot_define_new_risk_levels(self):
        with self.assertRaises(StrategyContractError):
            TradeSignal(
                action="EXIT",
                side="LONG",
                reason="Exit",
                stop_loss="100",
            )

    def test_signal_is_immutable(self):
        signal = TradeSignal(
            action="ENTER",
            side="LONG",
            reason="Test",
        )

        with self.assertRaises(AttributeError):
            signal.reason = "Changed"


class TestBacktestStrategy(unittest.TestCase):

    def test_abstract_strategy_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            BacktestStrategy()

    def test_concrete_strategy_name(self):
        strategy = ExampleStrategy()

        self.assertEqual(
            strategy.name,
            "Example Test Strategy",
        )

    def test_strategy_generates_signal_from_history(self):
        strategy = ExampleStrategy()

        history = (
            {"direction": "BEARISH"},
            {"direction": "BULLISH"},
        )

        context = StrategyContext(
            current_date=date(2026, 1, 2),
            current_close=Decimal("100"),
            position=None,
        )

        signal = strategy.generate_signal(history, context)

        self.assertIsNotNone(signal)
        self.assertIs(signal.action, SignalAction.ENTER)
        self.assertIs(signal.side, PositionSide.LONG)

    def test_strategy_can_return_no_signal(self):
        strategy = ExampleStrategy()

        context = StrategyContext(
            current_date=date(2026, 1, 2),
            current_close=Decimal("100"),
            position=None,
        )

        self.assertIsNone(
            strategy.generate_signal(
                ({"direction": "SIDEWAYS"},),
                context,
            )
        )


if __name__ == "__main__":
    unittest.main()
