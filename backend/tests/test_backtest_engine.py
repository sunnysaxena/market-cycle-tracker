import unittest
from datetime import date
from decimal import Decimal

from app.engines.backtest_config import BacktestConfig
from app.engines.backtest_engine import (
    BacktestEngine,
    BacktestEngineError,
)
from app.engines.backtest_strategy import (
    BacktestStrategy,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)


class ScriptedStrategy(BacktestStrategy):
    def __init__(self, signals=None):
        self.signals = signals or {}
        self.seen_histories = []
        self.seen_contexts = []
        self.history_views = []

    @property
    def name(self):
        return "Scripted Test Strategy"

    def generate_signal(self, history, context):
        dates = tuple(row["candle_date"] for row in history)
        self.seen_histories.append(dates)
        self.seen_contexts.append(context)
        self.history_views.append(history)

        if not history:
            return None

        return self.signals.get(history[-1]["candle_date"])


def make_bar(
    day,
    *,
    open_price="100",
    high="105",
    low="95",
    close="102",
    status="ready",
):
    return {
        "import_batch_id": 5,
        "instrument_code": "NIFTY50",
        "candle_date": date(2026, 1, day),
        "open": Decimal(open_price),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "indicator_calculation_status": status,
    }


def entry_signal(
    side=PositionSide.LONG,
    *,
    stop_loss=None,
    take_profit=None,
):
    return TradeSignal(
        action=SignalAction.ENTER,
        side=side,
        reason="Test entry",
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def exit_signal(side=PositionSide.LONG):
    return TradeSignal(
        action=SignalAction.EXIT,
        side=side,
        reason="Test exit",
    )


class TestBacktestEngine(unittest.TestCase):

    def make_engine(self, **config_options):
        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            **config_options,
        )
        return BacktestEngine(config)

    def test_long_trade_executes_on_next_candle_open(self):
        bars = [
            make_bar(1, open_price="100", high="103",
                     low="99", close="101"),
            make_bar(2, open_price="110", high="113",
                     low="108", close="111"),
            make_bar(3, open_price="120", high="123",
                     low="118", close="121"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
            date(2026, 1, 2): exit_signal(),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 1)

        trade = result.trades[0]
        self.assertEqual(trade.entry_date, date(2026, 1, 2))
        self.assertEqual(trade.exit_date, date(2026, 1, 3))
        self.assertEqual(trade.entry_reference_price, Decimal("110"))
        self.assertEqual(trade.exit_reference_price, Decimal("120"))
        self.assertEqual(trade.gross_points, Decimal("10"))
        self.assertEqual(trade.net_points, Decimal("10"))

    def test_short_trade_calculates_directional_points(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="103",
                     low="98", close="99"),
            make_bar(3, open_price="90", high="92",
                     low="88", close="89"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(PositionSide.SHORT),
            date(2026, 1, 2): exit_signal(PositionSide.SHORT),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(trade.side, PositionSide.SHORT)
        self.assertEqual(trade.entry_reference_price, Decimal("100"))
        self.assertEqual(trade.exit_reference_price, Decimal("90"))
        self.assertEqual(trade.gross_points, Decimal("10"))
        self.assertEqual(trade.net_points, Decimal("10"))

    def test_slippage_reduces_long_trade_profit(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100"),
            make_bar(3, open_price="110", high="112",
                     low="108", close="111"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
            date(2026, 1, 2): exit_signal(),
        })

        result = self.make_engine(
            slippage_bps="100",
        ).run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(trade.entry_fill_price, Decimal("101"))
        self.assertEqual(trade.exit_fill_price, Decimal("108.9"))
        self.assertEqual(trade.gross_points, Decimal("10"))
        self.assertEqual(trade.net_points, Decimal("7.9"))

    def test_long_stop_loss_executes(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="102",
                     low="94", close="98"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(stop_loss="95"),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 1)

        trade = result.trades[0]
        self.assertEqual(trade.exit_reference_price, Decimal("95"))
        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        self.assertEqual(trade.net_points, Decimal("-5"))

    def test_take_profit_executes(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="106",
                     low="99", close="104"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(take_profit="105"),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]
        self.assertEqual(trade.exit_reference_price, Decimal("105"))
        self.assertEqual(trade.exit_reason, "TAKE_PROFIT")
        self.assertEqual(trade.net_points, Decimal("5"))

    def test_stop_loss_wins_when_both_levels_are_touched(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="106",
                     low="94", close="101"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(
                stop_loss="95",
                take_profit="105",
            ),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        self.assertEqual(trade.exit_reference_price, Decimal("95"))

    def test_gap_through_stop_loss_executes_at_open(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="102",
                     low="98", close="100"),
            make_bar(3, open_price="90", high="92",
                     low="88", close="91"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(stop_loss="95"),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(
            trade.exit_reference_price,
            Decimal("90"),
        )
        self.assertEqual(trade.exit_reason, "STOP_LOSS_GAP")

    def test_gap_through_target_executes_at_open(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="102",
                     low="98", close="100"),
            make_bar(3, open_price="110", high="112",
                     low="108", close="111"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(take_profit="105"),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(
            trade.exit_reference_price,
            Decimal("110"),
        )
        self.assertEqual(trade.exit_reason, "TAKE_PROFIT_GAP")

    def test_short_stop_loss_executes(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="106",
                     low="98", close="103"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(
                PositionSide.SHORT,
                stop_loss="105",
            ),
        })

        result = self.make_engine().run(bars, strategy)

        trade = result.trades[0]

        self.assertEqual(trade.side, PositionSide.SHORT)
        self.assertEqual(trade.exit_reference_price, Decimal("105"))
        self.assertEqual(trade.exit_reason, "STOP_LOSS")
        self.assertEqual(trade.net_points, Decimal("-5"))

    def test_open_position_is_marked_at_end_of_data(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="110", high="113",
                     low="108", close="112"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 0)
        self.assertIsNotNone(result.open_position)

        mark = result.open_position

        self.assertEqual(mark.entry_date, date(2026, 1, 2))
        self.assertEqual(mark.mark_price, Decimal("112"))
        self.assertEqual(mark.unrealized_points, Decimal("2"))

    def test_final_entry_signal_is_reported_as_unexecuted(self):
        bars = [make_bar(1)]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 0)
        self.assertIsNone(result.open_position)
        self.assertIsNotNone(result.unexecuted_final_signal)

    def test_history_is_chronological_and_has_no_future_candles(self):
        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
        ]

        strategy = ScriptedStrategy()

        self.make_engine().run(bars, strategy)

        self.assertEqual(
            strategy.seen_histories,
            [
                (date(2026, 1, 1),),
                (date(2026, 1, 1), date(2026, 1, 2)),
                (
                    date(2026, 1, 1),
                    date(2026, 1, 2),
                    date(2026, 1, 3),
                ),
            ],
        )

    def test_ready_only_policy_skips_non_ready_signals(self):
        bars = [
            make_bar(1, status="partial"),
            make_bar(2, status="ready"),
            make_bar(3, status="ready"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
            date(2026, 1, 2): entry_signal(),
        })

        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            indicator_status_policy="READY_ONLY",
        )

        result = BacktestEngine(config).run(bars, strategy)

        self.assertEqual(result.total_candles, 3)
        self.assertEqual(result.evaluated_candles, 2)
        self.assertEqual(result.skipped_indicator_candles, 1)
        self.assertEqual(
            strategy.seen_histories,
            [
                (date(2026, 1, 2),),
                (date(2026, 1, 2), date(2026, 1, 3)),
            ],
        )

    def test_strategy_receives_current_position_context(self):
        class ContextAwareStrategy(BacktestStrategy):
            def __init__(self):
                self.contexts = []

            @property
            def name(self):
                return "Context Aware Strategy"

            def generate_signal(self, history, context):
                self.contexts.append(context)

                if context.current_date == date(2026, 1, 1):
                    return entry_signal()

                if (
                    context.current_date == date(2026, 1, 2)
                    and context.has_open_position
                ):
                    return exit_signal(context.position.side)

                return None

        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
        ]

        strategy = ContextAwareStrategy()
        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 1)
        self.assertEqual(len(strategy.contexts), 3)

        first, second, third = strategy.contexts

        self.assertFalse(first.has_open_position)
        self.assertEqual(first.current_close, Decimal("102"))

        self.assertTrue(second.has_open_position)
        self.assertEqual(second.position.side, PositionSide.LONG)
        self.assertEqual(
            second.position.entry_date,
            date(2026, 1, 2),
        )
        self.assertEqual(
            second.position.entry_fill_price,
            Decimal("100"),
        )

        self.assertFalse(third.has_open_position)

    def test_saved_history_view_cannot_see_future_candles(self):
        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
        ]

        strategy = ScriptedStrategy()
        self.make_engine().run(bars, strategy)

        first_view = strategy.history_views[0]

        # The view remains fixed at the time it was provided.
        self.assertEqual(len(first_view), 1)
        self.assertEqual(
            first_view[-1]["candle_date"],
            date(2026, 1, 1),
        )

        # Strategy records are read-only.
        with self.assertRaises(TypeError):
            first_view[0]["close"] = Decimal("999")

        # Slicing also respects the fixed history boundary.
        self.assertEqual(len(first_view[:]), 1)

    def test_opposing_entry_reverses_position_at_next_open(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100", high="105",
                     low="95", close="102"),
            make_bar(3, open_price="110", high="115",
                     low="108", close="112"),
            make_bar(4, open_price="105", high="108",
                     low="103", close="106"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(PositionSide.LONG),
            date(2026, 1, 2): entry_signal(PositionSide.SHORT),
            date(2026, 1, 3): exit_signal(PositionSide.SHORT),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 2)

        long_trade, short_trade = result.trades

        self.assertEqual(long_trade.side, PositionSide.LONG)
        self.assertEqual(long_trade.entry_date, date(2026, 1, 2))
        self.assertEqual(long_trade.exit_date, date(2026, 1, 3))
        self.assertEqual(long_trade.entry_reference_price, Decimal("100"))
        self.assertEqual(long_trade.exit_reference_price, Decimal("110"))
        self.assertEqual(long_trade.gross_points, Decimal("10"))
        self.assertTrue(long_trade.exit_reason.startswith("REVERSAL:"))

        self.assertEqual(short_trade.side, PositionSide.SHORT)
        self.assertEqual(short_trade.entry_date, date(2026, 1, 3))
        self.assertEqual(short_trade.exit_date, date(2026, 1, 4))
        self.assertEqual(short_trade.entry_reference_price, Decimal("110"))
        self.assertEqual(short_trade.exit_reference_price, Decimal("105"))
        self.assertEqual(short_trade.gross_points, Decimal("5"))

        reversal_context = strategy.seen_contexts[2]
        self.assertTrue(reversal_context.has_open_position)
        self.assertEqual(
            reversal_context.position.side,
            PositionSide.SHORT,
        )

    def test_equity_curve_tracks_realized_and_unrealized_points(self):
        bars = [
            make_bar(1),
            make_bar(
                2,
                open_price="100",
                high="112",
                low="98",
                close="110",
            ),
            make_bar(
                3,
                open_price="120",
                high="123",
                low="118",
                close="121",
            ),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
            date(2026, 1, 2): exit_signal(),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(len(result.equity_curve), 3)

        first, second, third = result.equity_curve

        self.assertEqual(first.candle_date, date(2026, 1, 1))
        self.assertEqual(first.realized_points, Decimal("0"))
        self.assertEqual(first.unrealized_points, Decimal("0"))
        self.assertEqual(first.equity_points, Decimal("0"))

        self.assertEqual(second.candle_date, date(2026, 1, 2))
        self.assertEqual(second.realized_points, Decimal("0"))
        self.assertEqual(second.unrealized_points, Decimal("10"))
        self.assertEqual(second.equity_points, Decimal("10"))

        self.assertEqual(third.candle_date, date(2026, 1, 3))
        self.assertEqual(third.realized_points, Decimal("20"))
        self.assertEqual(third.unrealized_points, Decimal("0"))
        self.assertEqual(third.equity_points, Decimal("20"))

        self.assertEqual(result.total_net_points, Decimal("20"))

    def test_equity_curve_includes_non_ready_market_candles(self):
        bars = [
            make_bar(1, status="partial"),
            make_bar(2, status="ready"),
            make_bar(3, status="warming_up"),
        ]

        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            indicator_status_policy="READY_ONLY",
        )

        result = BacktestEngine(config).run(
            bars,
            ScriptedStrategy(),
        )

        self.assertEqual(result.total_candles, 3)
        self.assertEqual(result.evaluated_candles, 1)
        self.assertEqual(result.skipped_indicator_candles, 2)

        self.assertEqual(len(result.equity_curve), 3)

        self.assertEqual(
            tuple(
                snapshot.candle_date
                for snapshot in result.equity_curve
            ),
            (
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
            ),
        )

        self.assertTrue(
            all(
                snapshot.equity_points == Decimal("0")
                for snapshot in result.equity_curve
            )
        )

    def test_warmup_candles_seed_history_without_trading(self):
        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
            make_bar(
                4,
                open_price="110",
                high="115",
                low="108",
                close="112",
            ),
            make_bar(
                5,
                open_price="120",
                high="123",
                low="118",
                close="121",
            ),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(PositionSide.SHORT),
            date(2026, 1, 2): entry_signal(PositionSide.SHORT),
            date(2026, 1, 3): entry_signal(PositionSide.LONG),
            date(2026, 1, 4): exit_signal(PositionSide.LONG),
        })

        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            start_date=date(2026, 1, 3),
            end_date=date(2026, 1, 5),
        )

        result = BacktestEngine(config).run(
            bars,
            strategy,
            warmup_bars=2,
        )

        self.assertEqual(result.total_candles, 3)
        self.assertEqual(result.evaluated_candles, 3)
        self.assertEqual(len(result.equity_curve), 3)

        self.assertEqual(
            tuple(
                item.candle_date
                for item in result.equity_curve
            ),
            (
                date(2026, 1, 3),
                date(2026, 1, 4),
                date(2026, 1, 5),
            ),
        )

        # Warm-up signals were never evaluated.
        self.assertEqual(len(strategy.seen_histories), 3)

        first_history = strategy.seen_histories[0]
        self.assertEqual(
            first_history,
            (
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
            ),
        )

        # The first active signal executed at the next candle open.
        self.assertEqual(result.closed_trade_count, 1)
        trade = result.trades[0]
        self.assertEqual(trade.entry_date, date(2026, 1, 4))
        self.assertEqual(trade.exit_date, date(2026, 1, 5))
        self.assertEqual(trade.entry_reference_price, Decimal("110"))
        self.assertEqual(trade.exit_reference_price, Decimal("120"))

    def test_ready_only_filters_warmup_history(self):
        bars = [
            make_bar(1, status="partial"),
            make_bar(2, status="ready"),
            make_bar(3, status="ready"),
            make_bar(4, status="ready"),
        ]

        strategy = ScriptedStrategy()

        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            start_date=date(2026, 1, 3),
            end_date=date(2026, 1, 4),
            indicator_status_policy="READY_ONLY",
        )

        result = BacktestEngine(config).run(
            bars,
            strategy,
            warmup_bars=2,
        )

        self.assertEqual(result.total_candles, 2)
        self.assertEqual(result.evaluated_candles, 2)
        self.assertEqual(result.skipped_indicator_candles, 0)

        self.assertEqual(
            strategy.seen_histories[0],
            (
                date(2026, 1, 2),
                date(2026, 1, 3),
            ),
        )

        self.assertEqual(len(result.equity_curve), 2)

    def test_rejects_invalid_warmup_configuration(self):
        config = BacktestConfig(
            import_batch_id=5,
            instrument_code="NIFTY50",
            start_date=date(2026, 1, 2),
        )

        engine = BacktestEngine(config)

        bars = [
            make_bar(1),
            make_bar(2),
        ]

        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(BacktestEngineError):
                    engine.run(
                        bars,
                        ScriptedStrategy(),
                        warmup_bars=value,
                    )

    def test_warmup_requires_start_date(self):
        bars = [make_bar(1)]

        with self.assertRaisesRegex(
            BacktestEngineError,
            "requires start_date",
        ):
            self.make_engine().run(
                bars,
                ScriptedStrategy(),
                warmup_bars=1,
            )


    def test_date_range_filters_records(self):
        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
        ]

        result = self.make_engine(
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
        ).run(bars, ScriptedStrategy())

        self.assertEqual(result.total_candles, 2)
        self.assertEqual(result.evaluated_candles, 2)

    def test_rejects_non_chronological_records(self):
        bars = [
            make_bar(2),
            make_bar(1),
        ]

        with self.assertRaisesRegex(
            BacktestEngineError,
            "strictly increasing",
        ):
            self.make_engine().run(bars, ScriptedStrategy())

    def test_rejects_duplicate_dates(self):
        bars = [
            make_bar(1),
            make_bar(1),
        ]

        with self.assertRaisesRegex(
            BacktestEngineError,
            "strictly increasing",
        ):
            self.make_engine().run(bars, ScriptedStrategy())

    def test_rejects_invalid_ohlc(self):
        bars = [
            make_bar(
                1,
                open_price="100",
                high="99",
                low="95",
                close="98",
            )
        ]

        with self.assertRaisesRegex(
            BacktestEngineError,
            "Invalid high",
        ):
            self.make_engine().run(bars, ScriptedStrategy())

    def test_rejects_mismatched_instrument(self):
        bar = make_bar(1)
        bar["instrument_code"] = "SENSEX"

        with self.assertRaisesRegex(
            BacktestEngineError,
            "instrument_code",
        ):
            self.make_engine().run([bar], ScriptedStrategy())

    def test_rejects_non_positive_quantity(self):
        for quantity in ("0", "-1"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(BacktestEngineError):
                    self.make_engine().run(
                        [make_bar(1)],
                        ScriptedStrategy(),
                        quantity=quantity,
                    )

    def test_rejects_strategy_returning_invalid_object(self):
        class InvalidStrategy(BacktestStrategy):
            @property
            def name(self):
                return "Invalid Strategy"

            def generate_signal(self, history, context):
                return {"action": "ENTER"}

        with self.assertRaises(StrategyContractError):
            self.make_engine().run(
                [make_bar(1)],
                InvalidStrategy(),
            )

    def test_rejects_exit_for_wrong_position_side(self):
        bars = [
            make_bar(1),
            make_bar(2),
            make_bar(3),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(PositionSide.LONG),
            date(2026, 1, 2): exit_signal(PositionSide.SHORT),
        })

        with self.assertRaisesRegex(
            StrategyContractError,
            "does not match",
        ):
            self.make_engine().run(bars, strategy)

    def test_empty_dataset_returns_empty_result(self):
        result = self.make_engine().run(
            [],
            ScriptedStrategy(),
        )

        self.assertEqual(result.total_candles, 0)
        self.assertEqual(result.closed_trade_count, 0)
        self.assertEqual(result.total_net_points, Decimal("0"))
        self.assertIsNone(result.open_position)

    def test_result_calculates_win_rate_and_totals(self):
        bars = [
            make_bar(1),
            make_bar(2, open_price="100"),
            make_bar(3, open_price="110", high="112",
                     low="108", close="111"),
            make_bar(4, open_price="120", high="122",
                     low="118", close="121"),
            make_bar(5, open_price="115", high="117",
                     low="113", close="116"),
        ]

        strategy = ScriptedStrategy({
            date(2026, 1, 1): entry_signal(),
            date(2026, 1, 2): exit_signal(),
            date(2026, 1, 3): entry_signal(),
            date(2026, 1, 4): exit_signal(),
        })

        result = self.make_engine().run(bars, strategy)

        self.assertEqual(result.closed_trade_count, 2)
        self.assertEqual(result.winning_trades, 1)
        self.assertEqual(result.losing_trades, 1)
        self.assertEqual(result.win_rate_percent, Decimal("50"))
        self.assertEqual(result.total_gross_points, Decimal("5"))
        self.assertEqual(result.total_net_points, Decimal("5"))


if __name__ == "__main__":
    unittest.main()
