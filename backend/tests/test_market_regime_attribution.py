import unittest
from datetime import date
from decimal import Decimal

from app.engines.backtest_engine import (
    BacktestResult,
    BacktestTrade,
    OpenPositionMark,
)
from app.engines.backtest_strategy import PositionSide
from app.engines.market_regime_attribution import (
    MARKET_REGIMES,
    MarketRegimeAttribution,
    MarketRegimeAttributionError,
)


def make_trade(entry_day: int, exit_day: int, net_points: str) -> BacktestTrade:
    net = Decimal(net_points)
    return BacktestTrade(
        entry_date=date(2026, 1, entry_day),
        exit_date=date(2026, 1, exit_day),
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


def make_result(*, trades=(), open_position=None, unexecuted=None):
    return BacktestResult(
        strategy_name="EMA 9/20",
        instrument_code="NIFTY50",
        timeframe="1D",
        import_batch_id=5,
        total_candles=10,
        evaluated_candles=10,
        skipped_indicator_candles=0,
        trades=tuple(trades),
        equity_curve=(),
        open_position=open_position,
        unexecuted_final_signal=unexecuted,
    )


def make_records(classifications):
    return [
        {
            "candle_date": date(2026, 1, day),
            "cycle_classification": classification,
        }
        for day, classification in enumerate(classifications, start=1)
    ]


class MarketRegimeAttributionTests(unittest.TestCase):
    def test_all_seven_regimes_are_reported_in_canonical_order(self):
        records = make_records([
            "MARKUP", "MARKDOWN", "ACCUMULATION", "DISTRIBUTION",
            "SIDEWAYS_CONSOLIDATION", "TRANSITION_UNCERTAIN",
            "INSUFFICIENT_DATA", "MARKUP",
        ])
        trades = [
            make_trade(2, 3, "10"),
            make_trade(3, 4, "-5"),
            make_trade(4, 5, "2"),
            make_trade(5, 6, "-2"),
            make_trade(6, 7, "0"),
            make_trade(7, 8, "3"),
            make_trade(8, 9, "4"),
        ]

        report = MarketRegimeAttribution.analyze(
            make_result(trades=trades), records
        )

        self.assertEqual(
            tuple(row.regime for row in report.regime_performance),
            MARKET_REGIMES,
        )
        self.assertEqual(report.attributed_trade_count, 7)
        self.assertEqual(report.unattributed_trade_count, 0)
        self.assertTrue(all(row.total_trades == 1 for row in report.regime_performance))

    def test_uses_signal_candle_not_entry_or_exit_candle_regime(self):
        records = make_records(["MARKUP", "MARKDOWN", "DISTRIBUTION"])
        trade = make_trade(2, 3, "10")

        report = MarketRegimeAttribution.analyze(
            make_result(trades=[trade]), records
        )

        attribution = report.trade_attributions[0]
        self.assertEqual(attribution.signal_date, date(2026, 1, 1))
        self.assertEqual(attribution.regime, "MARKUP")

    def test_aggregates_metrics_and_counts_breakeven(self):
        records = make_records([
            "MARKUP", "MARKUP", "MARKUP", "MARKUP", "MARKUP"
        ])
        trades = [
            make_trade(2, 3, "10"),
            make_trade(3, 4, "-4"),
            make_trade(4, 5, "0"),
        ]

        report = MarketRegimeAttribution.analyze(
            make_result(trades=trades), records
        )
        markup = report.regime_performance[1]

        self.assertEqual(markup.total_trades, 3)
        self.assertEqual(markup.winning_trades, 1)
        self.assertEqual(markup.losing_trades, 1)
        self.assertEqual(markup.breakeven_trades, 1)
        self.assertEqual(markup.win_rate_percent, Decimal("33.33333333333333333333333333"))
        self.assertEqual(markup.net_points, Decimal("6"))
        self.assertEqual(markup.profit_factor, Decimal("2.5"))

    def test_profit_factor_is_none_without_losing_trades(self):
        records = make_records(["MARKUP", "MARKUP"])
        report = MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(2, 3, "5")]), records
        )
        self.assertIsNone(report.regime_performance[1].profit_factor)

    def test_missing_signal_classification_is_unattributed(self):
        records = make_records([None, "MARKDOWN"])
        report = MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(2, 3, "5")]), records
        )
        self.assertEqual(report.unattributed_trade_count, 1)
        self.assertEqual(
            report.unattributed_trades[0].reason,
            "SIGNAL_CANDLE_CLASSIFICATION_MISSING",
        )

    def test_unknown_signal_classification_is_unattributed(self):
        records = make_records(["NEW_UNKNOWN_LABEL", "MARKDOWN"])
        report = MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(2, 3, "5")]), records
        )
        self.assertEqual(
            report.unattributed_trades[0].reason,
            "SIGNAL_CANDLE_CLASSIFICATION_UNKNOWN",
        )

    def test_missing_entry_or_preceding_signal_candle_is_unattributed(self):
        no_entry = MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(5, 6, "5")]),
            make_records(["MARKUP", "MARKUP"]),
        )
        self.assertEqual(no_entry.unattributed_trades[0].reason, "ENTRY_CANDLE_NOT_FOUND")

        no_predecessor = MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(1, 2, "5")]),
            make_records(["MARKUP", "MARKDOWN"]),
        )
        self.assertEqual(
            no_predecessor.unattributed_trades[0].reason,
            "PRECEDING_SIGNAL_CANDLE_NOT_AVAILABLE",
        )

    def test_open_position_and_unexecuted_signal_are_reported_not_grouped(self):
        # Open-position detail is intentionally not used in closed-trade metrics.
        open_position = OpenPositionMark(
            entry_date=date(2026, 1, 2),
            side=PositionSide.LONG,
            entry_reference_price=Decimal("100"),
            entry_fill_price=Decimal("100"),
            mark_date=date(2026, 1, 3),
            mark_price=Decimal("110"),
            estimated_exit_fill_price=Decimal("110"),
            quantity=Decimal("1"),
            unrealized_points=Decimal("10"),
            entry_reason="Open test position",
        )
        report = MarketRegimeAttribution.analyze(
            make_result(open_position=open_position),
            make_records(["MARKUP", "MARKDOWN"]),
        )
        self.assertTrue(report.open_position_present)
        self.assertFalse(report.unexecuted_final_signal_present)
        self.assertEqual(report.total_closed_trades, 0)

    def test_duplicate_or_unsorted_record_dates_raise(self):
        duplicate = [
            {"candle_date": date(2026, 1, 1), "cycle_classification": "MARKUP"},
            {"candle_date": date(2026, 1, 1), "cycle_classification": "MARKDOWN"},
        ]
        with self.assertRaises(MarketRegimeAttributionError):
            MarketRegimeAttribution.analyze(make_result(), duplicate)

    def test_analysis_does_not_mutate_input_records(self):
        records = make_records(["MARKUP", "MARKDOWN"])
        before = [dict(row) for row in records]
        MarketRegimeAttribution.analyze(
            make_result(trades=[make_trade(2, 3, "5")]), records
        )
        self.assertEqual(records, before)


if __name__ == "__main__":
    unittest.main()
