import unittest
from datetime import date
from decimal import Decimal

from app.engines.backtest_engine import (
    BacktestResult,
    BacktestTrade,
    EquitySnapshot,
    OpenPositionMark,
)
from app.engines.backtest_strategy import PositionSide
from app.engines.performance_analyzer import (
    PerformanceAnalyzer,
    PerformanceAnalyzerError,
)


def make_trade(net_points, index=1):
    net = Decimal(str(net_points))

    return BacktestTrade(
        entry_date=date(2026, 1, index),
        exit_date=date(2026, 1, index + 1),
        side=PositionSide.LONG,
        entry_reference_price=Decimal("100"),
        entry_fill_price=Decimal("100"),
        exit_reference_price=Decimal("100") + net,
        exit_fill_price=Decimal("100") + net,
        quantity=Decimal("1"),
        gross_points=net,
        net_points=net,
        entry_reason="Test entry",
        exit_reason="Test exit",
    )


def make_snapshot(day, realized, unrealized):
    realized = Decimal(str(realized))
    unrealized = Decimal(str(unrealized))

    return EquitySnapshot(
        candle_date=date(2026, 1, day),
        realized_points=realized,
        unrealized_points=unrealized,
        equity_points=realized + unrealized,
    )


def make_open_position(unrealized="25"):
    unrealized = Decimal(str(unrealized))

    return OpenPositionMark(
        entry_date=date(2026, 1, 10),
        side=PositionSide.LONG,
        entry_reference_price=Decimal("100"),
        entry_fill_price=Decimal("100"),
        mark_date=date(2026, 1, 20),
        mark_price=Decimal("125"),
        estimated_exit_fill_price=Decimal("125"),
        quantity=Decimal("1"),
        unrealized_points=unrealized,
        entry_reason="Test open position",
    )


def make_result(
    *,
    trades=(),
    equity_curve=(),
    open_position=None,
):
    return BacktestResult(
        strategy_name="Performance Test Strategy",
        instrument_code="NIFTY50",
        timeframe="1D",
        import_batch_id=5,
        total_candles=len(equity_curve),
        evaluated_candles=len(equity_curve),
        skipped_indicator_candles=0,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        open_position=open_position,
        unexecuted_final_signal=None,
    )


class TestPerformanceAnalyzer(unittest.TestCase):

    def analyze(self, result):
        return PerformanceAnalyzer.analyze(result)

    def test_trade_summary_and_expectancy(self):
        result = make_result(
            trades=[
                make_trade("100", 1),
                make_trade("-40", 3),
                make_trade("0", 5),
                make_trade("60", 7),
                make_trade("-20", 9),
            ]
        )

        report = self.analyze(result)

        self.assertEqual(report.total_trades, 5)
        self.assertEqual(report.winning_trades, 2)
        self.assertEqual(report.losing_trades, 2)
        self.assertEqual(report.breakeven_trades, 1)

        self.assertEqual(report.win_rate_percent, Decimal("40"))
        self.assertEqual(report.gross_profit_points, Decimal("160"))
        self.assertEqual(report.gross_loss_points, Decimal("60"))
        self.assertEqual(report.net_closed_points, Decimal("100"))

        self.assertEqual(report.average_winner_points, Decimal("80"))
        self.assertEqual(report.average_loser_points, Decimal("-30"))
        self.assertEqual(report.expectancy_points, Decimal("20"))

        self.assertEqual(
            report.profit_factor.quantize(Decimal("0.0001")),
            Decimal("2.6667"),
        )

    def test_profit_factor_is_none_when_there_are_no_losses(self):
        result = make_result(
            trades=[
                make_trade("50", 1),
                make_trade("25", 3),
            ]
        )

        report = self.analyze(result)

        self.assertEqual(report.gross_profit_points, Decimal("75"))
        self.assertEqual(report.gross_loss_points, Decimal("0"))
        self.assertIsNone(report.profit_factor)

    def test_profit_factor_is_zero_when_all_trades_are_losses(self):
        result = make_result(
            trades=[
                make_trade("-30", 1),
                make_trade("-20", 3),
            ]
        )

        report = self.analyze(result)

        self.assertEqual(report.gross_profit_points, Decimal("0"))
        self.assertEqual(report.gross_loss_points, Decimal("50"))
        self.assertEqual(report.profit_factor, Decimal("0"))

    def test_empty_trade_result(self):
        report = self.analyze(make_result())

        self.assertEqual(report.total_trades, 0)
        self.assertEqual(report.winning_trades, 0)
        self.assertEqual(report.losing_trades, 0)
        self.assertEqual(report.breakeven_trades, 0)
        self.assertEqual(report.win_rate_percent, Decimal("0"))
        self.assertEqual(report.expectancy_points, Decimal("0"))
        self.assertIsNone(report.average_winner_points)
        self.assertIsNone(report.average_loser_points)
        self.assertIsNone(report.profit_factor)

    def test_average_metrics_exclude_breakeven_trades(self):
        result = make_result(
            trades=[
                make_trade("100", 1),
                make_trade("0", 3),
                make_trade("-50", 5),
            ]
        )

        report = self.analyze(result)

        self.assertEqual(report.average_winner_points, Decimal("100"))
        self.assertEqual(report.average_loser_points, Decimal("-50"))
        self.assertEqual(report.expectancy_points, Decimal("50") / Decimal("3"))

    def test_maximum_drawdown_and_recovery(self):
        curve = [
            make_snapshot(1, "0", "0"),
            make_snapshot(2, "0", "100"),
            make_snapshot(3, "0", "60"),
            make_snapshot(4, "0", "90"),
            make_snapshot(5, "0", "100"),
        ]

        report = self.analyze(make_result(equity_curve=curve))

        self.assertEqual(report.max_drawdown_points, Decimal("40"))
        self.assertEqual(report.drawdown_peak_date, date(2026, 1, 2))
        self.assertEqual(report.drawdown_trough_date, date(2026, 1, 3))
        self.assertEqual(report.recovery_date, date(2026, 1, 5))
        self.assertEqual(report.recovery_sessions, 2)
        self.assertTrue(report.drawdown_recovered)

    def test_unrecovered_drawdown(self):
        curve = [
            make_snapshot(1, "0", "0"),
            make_snapshot(2, "0", "100"),
            make_snapshot(3, "0", "60"),
            make_snapshot(4, "0", "70"),
        ]

        report = self.analyze(make_result(equity_curve=curve))

        self.assertEqual(report.max_drawdown_points, Decimal("40"))
        self.assertIsNone(report.recovery_date)
        self.assertIsNone(report.recovery_sessions)
        self.assertFalse(report.drawdown_recovered)

    def test_initial_loss_uses_zero_baseline(self):
        curve = [
            make_snapshot(1, "0", "-10"),
            make_snapshot(2, "0", "-20"),
        ]

        report = self.analyze(make_result(equity_curve=curve))

        self.assertEqual(report.max_drawdown_points, Decimal("20"))
        self.assertIsNone(report.drawdown_peak_date)
        self.assertEqual(report.drawdown_trough_date, date(2026, 1, 2))
        self.assertFalse(report.drawdown_recovered)

    def test_no_drawdown(self):
        curve = [
            make_snapshot(1, "0", "0"),
            make_snapshot(2, "0", "50"),
            make_snapshot(3, "0", "75"),
        ]

        report = self.analyze(make_result(equity_curve=curve))

        self.assertEqual(report.max_drawdown_points, Decimal("0"))
        self.assertIsNone(report.drawdown_peak_date)
        self.assertIsNone(report.drawdown_trough_date)
        self.assertIsNone(report.recovery_date)
        self.assertEqual(report.recovery_sessions, 0)
        self.assertTrue(report.drawdown_recovered)

    def test_open_position_is_included_in_ending_equity(self):
        result = make_result(
            trades=[
                make_trade("100", 1),
            ],
            open_position=make_open_position("25"),
        )

        report = self.analyze(result)

        self.assertEqual(report.net_closed_points, Decimal("100"))
        self.assertEqual(report.open_unrealized_points, Decimal("25"))
        self.assertEqual(report.ending_equity_points, Decimal("125"))

    def test_equity_curve_takes_precedence_for_ending_equity(self):
        curve = [
            make_snapshot(1, "0", "0"),
            make_snapshot(2, "100", "30"),
        ]

        result = make_result(
            trades=[make_trade("100", 1)],
            equity_curve=curve,
            open_position=make_open_position("30"),
        )

        report = self.analyze(result)

        self.assertEqual(report.ending_equity_points, Decimal("130"))
        self.assertEqual(report.equity_observations, 2)

    def test_empty_equity_curve_has_zero_drawdown(self):
        report = self.analyze(make_result())

        self.assertEqual(report.max_drawdown_points, Decimal("0"))
        self.assertEqual(report.recovery_sessions, 0)
        self.assertTrue(report.drawdown_recovered)
        self.assertEqual(report.equity_observations, 0)

    def test_rejects_inconsistent_equity_snapshot(self):
        invalid_snapshot = EquitySnapshot(
            candle_date=date(2026, 1, 1),
            realized_points=Decimal("10"),
            unrealized_points=Decimal("5"),
            equity_points=Decimal("20"),
        )

        with self.assertRaises(PerformanceAnalyzerError):
            self.analyze(
                make_result(equity_curve=[invalid_snapshot])
            )

    def test_rejects_non_chronological_equity_curve(self):
        curve = [
            make_snapshot(2, "0", "100"),
            make_snapshot(1, "0", "90"),
        ]

        with self.assertRaises(PerformanceAnalyzerError):
            self.analyze(make_result(equity_curve=curve))

    def test_rejects_non_backtest_result(self):
        with self.assertRaises(TypeError):
            PerformanceAnalyzer.analyze(None)


if __name__ == "__main__":
    unittest.main()
