from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.engines.backtest_engine import BacktestResult, BacktestTrade, ZERO


MARKET_REGIMES: tuple[str, ...] = (
    "ACCUMULATION",
    "MARKUP",
    "DISTRIBUTION",
    "MARKDOWN",
    "SIDEWAYS_CONSOLIDATION",
    "TRANSITION_UNCERTAIN",
    "INSUFFICIENT_DATA",
)


class MarketRegimeAttributionError(ValueError):
    """Raised when backtest trades cannot be safely attributed."""


def _as_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise MarketRegimeAttributionError(
        f"{field_name} must be a date or datetime; received {value!r}."
    )


def _as_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MarketRegimeAttributionError(
            f"{field_name} must be a valid decimal number."
        ) from exc
    if not result.is_finite():
        raise MarketRegimeAttributionError(
            f"{field_name} must be finite."
        )
    return result


@dataclass(frozen=True, slots=True)
class TradeRegimeAttribution:
    """Regime assigned to a completed trade using its signal candle."""

    trade: BacktestTrade
    signal_date: date | None
    regime: str | None
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RegimePerformance:
    """Closed-trade performance for one market-cycle classification."""

    regime: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: Decimal
    gross_profit_points: Decimal
    gross_loss_points: Decimal
    profit_factor: Decimal | None
    net_points: Decimal
    average_net_points: Decimal
    average_winner_points: Decimal | None
    average_loser_points: Decimal | None
    expectancy_points: Decimal


@dataclass(frozen=True, slots=True)
class MarketRegimeAttributionReport:
    """Immutable regime attribution report for one backtest result."""

    strategy_name: str
    instrument_code: str
    timeframe: str
    import_batch_id: int
    total_closed_trades: int
    attributed_trade_count: int
    unattributed_trade_count: int
    open_position_present: bool
    unexecuted_final_signal_present: bool
    regime_performance: tuple[RegimePerformance, ...]
    trade_attributions: tuple[TradeRegimeAttribution, ...]

    @property
    def unattributed_trades(self) -> tuple[TradeRegimeAttribution, ...]:
        return tuple(
            item for item in self.trade_attributions
            if item.status != "ATTRIBUTED"
        )


class MarketRegimeAttribution:
    """Attribute completed backtest trades to their entry-decision regime.

    The backtest engine creates a signal after a candle closes and executes
    it at the next candle's open. Since BacktestTrade stores execution dates
    but not signal dates, this analyzer finds the historical candle directly
    preceding each trade's entry_date. If the execution candle or its
    predecessor cannot be established, the trade is left unattributed.

    ``records`` must be the same complete, chronologically ordered daily
    records supplied to BacktestEngine.run (including any warm-up candles).
    Each record must expose ``candle_date`` and ``cycle_classification``.
    This class is read-only and does not mutate the result or input records.
    """

    @staticmethod
    def analyze(
        result: BacktestResult,
        records: Sequence[Mapping[str, Any]],
    ) -> MarketRegimeAttributionReport:
        if not isinstance(result, BacktestResult):
            raise TypeError("result must be a BacktestResult.")
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise TypeError("records must be a sequence of historical mappings.")

        normalized_records: list[tuple[date, Mapping[str, Any]]] = []
        index_by_date: dict[date, int] = {}
        previous_date: date | None = None

        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise MarketRegimeAttributionError(
                    f"Historical record at index {index} must be a mapping."
                )
            candle_date = _as_date(
                record.get("candle_date"),
                f"records[{index}].candle_date",
            )
            if previous_date is not None and candle_date <= previous_date:
                raise MarketRegimeAttributionError(
                    "Historical candle dates must be strictly increasing "
                    "without duplicates."
                )
            previous_date = candle_date
            index_by_date[candle_date] = index
            normalized_records.append((candle_date, record))

        attributions: list[TradeRegimeAttribution] = []
        grouped: dict[str, list[BacktestTrade]] = {
            regime: [] for regime in MARKET_REGIMES
        }

        for trade_index, trade in enumerate(result.trades):
            if not isinstance(trade, BacktestTrade):
                raise MarketRegimeAttributionError(
                    f"result.trades[{trade_index}] is not a BacktestTrade."
                )

            entry_date = _as_date(
                trade.entry_date,
                f"result.trades[{trade_index}].entry_date",
            )
            entry_index = index_by_date.get(entry_date)

            if entry_index is None:
                attributions.append(TradeRegimeAttribution(
                    trade=trade,
                    signal_date=None,
                    regime=None,
                    status="UNATTRIBUTED",
                    reason="ENTRY_CANDLE_NOT_FOUND",
                ))
                continue

            if entry_index == 0:
                attributions.append(TradeRegimeAttribution(
                    trade=trade,
                    signal_date=None,
                    regime=None,
                    status="UNATTRIBUTED",
                    reason="PRECEDING_SIGNAL_CANDLE_NOT_AVAILABLE",
                ))
                continue

            signal_date, signal_record = normalized_records[entry_index - 1]
            raw_regime = signal_record.get("cycle_classification")

            if not isinstance(raw_regime, str) or not raw_regime.strip():
                attributions.append(TradeRegimeAttribution(
                    trade=trade,
                    signal_date=signal_date,
                    regime=None,
                    status="UNATTRIBUTED",
                    reason="SIGNAL_CANDLE_CLASSIFICATION_MISSING",
                ))
                continue

            regime = raw_regime.strip().upper()
            if regime not in MARKET_REGIMES:
                attributions.append(TradeRegimeAttribution(
                    trade=trade,
                    signal_date=signal_date,
                    regime=None,
                    status="UNATTRIBUTED",
                    reason="SIGNAL_CANDLE_CLASSIFICATION_UNKNOWN",
                ))
                continue

            grouped[regime].append(trade)
            attributions.append(TradeRegimeAttribution(
                trade=trade,
                signal_date=signal_date,
                regime=regime,
                status="ATTRIBUTED",
            ))

        performance = tuple(
            MarketRegimeAttribution._summarize(regime, trades)
            for regime, trades in grouped.items()
        )
        attributed_count = sum(len(trades) for trades in grouped.values())

        return MarketRegimeAttributionReport(
            strategy_name=result.strategy_name,
            instrument_code=result.instrument_code,
            timeframe=result.timeframe,
            import_batch_id=result.import_batch_id,
            total_closed_trades=len(result.trades),
            attributed_trade_count=attributed_count,
            unattributed_trade_count=len(result.trades) - attributed_count,
            open_position_present=result.open_position is not None,
            unexecuted_final_signal_present=(
                result.unexecuted_final_signal is not None
            ),
            regime_performance=performance,
            trade_attributions=tuple(attributions),
        )

    @staticmethod
    def _summarize(
        regime: str,
        trades: Sequence[BacktestTrade],
    ) -> RegimePerformance:
        values = [
            _as_decimal(trade.net_points, "trade.net_points")
            for trade in trades
        ]
        winners = [value for value in values if value > ZERO]
        losers = [value for value in values if value < ZERO]
        breakeven = sum(value == ZERO for value in values)

        gross_profit = sum(winners, ZERO)
        gross_loss = abs(sum(losers, ZERO))
        net_points = sum(values, ZERO)
        total = len(values)
        winning_count = len(winners)
        losing_count = len(losers)

        return RegimePerformance(
            regime=regime,
            total_trades=total,
            winning_trades=winning_count,
            losing_trades=losing_count,
            breakeven_trades=breakeven,
            win_rate_percent=(
                Decimal(winning_count) / Decimal(total) * Decimal("100")
                if total else ZERO
            ),
            gross_profit_points=gross_profit,
            gross_loss_points=gross_loss,
            profit_factor=(
                gross_profit / gross_loss if gross_loss > ZERO else None
            ),
            net_points=net_points,
            average_net_points=(net_points / Decimal(total) if total else ZERO),
            average_winner_points=(
                gross_profit / Decimal(winning_count)
                if winning_count else None
            ),
            average_loser_points=(
                sum(losers, ZERO) / Decimal(losing_count)
                if losing_count else None
            ),
            expectancy_points=(net_points / Decimal(total) if total else ZERO),
        )


__all__ = [
    "MARKET_REGIMES",
    "MarketRegimeAttribution",
    "MarketRegimeAttributionError",
    "MarketRegimeAttributionReport",
    "RegimePerformance",
    "TradeRegimeAttribution",
]
