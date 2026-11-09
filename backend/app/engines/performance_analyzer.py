from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.engines.backtest_engine import BacktestResult, ZERO


class PerformanceAnalyzerError(ValueError):
    """Raised when backtest results cannot be analyzed."""


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Performance and risk measurements for a backtest."""

    strategy_name: str
    instrument_code: str
    timeframe: str
    import_batch_id: int

    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: Decimal

    gross_profit_points: Decimal
    gross_loss_points: Decimal
    profit_factor: Decimal | None

    net_closed_points: Decimal
    open_unrealized_points: Decimal
    ending_equity_points: Decimal

    average_winner_points: Decimal | None
    average_loser_points: Decimal | None
    expectancy_points: Decimal

    max_drawdown_points: Decimal
    drawdown_peak_date: date | None
    drawdown_trough_date: date | None
    recovery_date: date | None
    recovery_sessions: int | None
    drawdown_recovered: bool

    equity_observations: int


def _decimal(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PerformanceAnalyzerError(
            f"{field_name} must be a valid decimal number."
        ) from exc

    if not result.is_finite():
        raise PerformanceAnalyzerError(
            f"{field_name} must be finite."
        )

    return result


def _drawdown_metrics(result: BacktestResult):
    """
    Calculate peak-to-trough drawdown from daily mark-to-market equity.

    Starting equity is zero index points. If the worst drawdown begins
    from this initial baseline, its peak date is None because the
    baseline precedes the first recorded candle.

    Recovery is the first later session whose equity reaches or
    exceeds the peak associated with the maximum drawdown.
    """

    curve = result.equity_curve

    if not curve:
        return {
            "max_drawdown_points": ZERO,
            "drawdown_peak_date": None,
            "drawdown_trough_date": None,
            "recovery_date": None,
            "recovery_sessions": 0,
            "drawdown_recovered": True,
        }

    previous_date: date | None = None

    peak_equity = ZERO
    peak_date: date | None = None

    maximum_drawdown = ZERO
    maximum_peak_value = ZERO
    maximum_peak_date: date | None = None
    maximum_trough_index: int | None = None
    maximum_trough_date: date | None = None

    for index, snapshot in enumerate(curve):
        current_date = snapshot.candle_date

        if not isinstance(current_date, date):
            raise PerformanceAnalyzerError(
                "Equity snapshot candle_date must be a date."
            )

        if previous_date is not None and current_date <= previous_date:
            raise PerformanceAnalyzerError(
                "Equity curve dates must be strictly increasing."
            )

        previous_date = current_date

        realized = _decimal(
            snapshot.realized_points,
            "realized_points",
        )
        unrealized = _decimal(
            snapshot.unrealized_points,
            "unrealized_points",
        )
        equity = _decimal(
            snapshot.equity_points,
            "equity_points",
        )

        if realized + unrealized != equity:
            raise PerformanceAnalyzerError(
                f"Inconsistent equity snapshot on {current_date}."
            )

        if equity > peak_equity:
            peak_equity = equity
            peak_date = current_date

        drawdown = peak_equity - equity

        if drawdown > maximum_drawdown:
            maximum_drawdown = drawdown
            maximum_peak_value = peak_equity
            maximum_peak_date = peak_date
            maximum_trough_index = index
            maximum_trough_date = current_date

    if maximum_drawdown == ZERO:
        return {
            "max_drawdown_points": ZERO,
            "drawdown_peak_date": None,
            "drawdown_trough_date": None,
            "recovery_date": None,
            "recovery_sessions": 0,
            "drawdown_recovered": True,
        }

    recovery_date = None
    recovery_sessions = None

    assert maximum_trough_index is not None

    for index in range(
        maximum_trough_index + 1,
        len(curve),
    ):
        snapshot = curve[index]

        if snapshot.equity_points >= maximum_peak_value:
            recovery_date = snapshot.candle_date
            recovery_sessions = index - maximum_trough_index
            break

    return {
        "max_drawdown_points": maximum_drawdown,
        "drawdown_peak_date": maximum_peak_date,
        "drawdown_trough_date": maximum_trough_date,
        "recovery_date": recovery_date,
        "recovery_sessions": recovery_sessions,
        "drawdown_recovered": recovery_date is not None,
    }


class PerformanceAnalyzer:
    """
    Analyze closed-trade performance and daily mark-to-market equity.

    All monetary-style results remain in index points multiplied by
    simulated quantity. This analyzer does not convert index points
    into rupees or assume options lot sizes.

    Profit factor is based on positive and negative net trade points,
    after the simulated slippage already included by the execution
    engine.

    When no losing trades exist, profit_factor is None because its
    denominator is zero.
    """

    @staticmethod
    def analyze(result: BacktestResult) -> PerformanceReport:

        if not isinstance(result, BacktestResult):
            raise TypeError(
                "result must be a BacktestResult."
            )

        trade_results = [
            _decimal(trade.net_points, "trade.net_points")
            for trade in result.trades
        ]

        winning_results = [
            points for points in trade_results if points > ZERO
        ]

        losing_results = [
            points for points in trade_results if points < ZERO
        ]

        breakeven_count = sum(
            points == ZERO for points in trade_results
        )

        total_trades = len(trade_results)
        winning_count = len(winning_results)
        losing_count = len(losing_results)

        gross_profit = sum(winning_results, ZERO)
        gross_loss = abs(sum(losing_results, ZERO))

        net_closed = sum(trade_results, ZERO)

        if gross_loss > ZERO:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = None

        win_rate = (
            Decimal(winning_count)
            / Decimal(total_trades)
            * Decimal("100")
            if total_trades
            else ZERO
        )

        average_winner = (
            gross_profit / Decimal(winning_count)
            if winning_count
            else None
        )

        average_loser = (
            sum(losing_results, ZERO) / Decimal(losing_count)
            if losing_count
            else None
        )

        expectancy = (
            net_closed / Decimal(total_trades)
            if total_trades
            else ZERO
        )

        open_unrealized = ZERO

        if result.open_position is not None:
            open_unrealized = _decimal(
                result.open_position.unrealized_points,
                "open_position.unrealized_points",
            )

        if result.equity_curve:
            ending_equity = _decimal(
                result.equity_curve[-1].equity_points,
                "ending_equity",
            )
        else:
            ending_equity = net_closed + open_unrealized

        drawdown = _drawdown_metrics(result)

        return PerformanceReport(
            strategy_name=result.strategy_name,
            instrument_code=result.instrument_code,
            timeframe=result.timeframe,
            import_batch_id=result.import_batch_id,

            total_trades=total_trades,
            winning_trades=winning_count,
            losing_trades=losing_count,
            breakeven_trades=breakeven_count,
            win_rate_percent=win_rate,

            gross_profit_points=gross_profit,
            gross_loss_points=gross_loss,
            profit_factor=profit_factor,

            net_closed_points=net_closed,
            open_unrealized_points=open_unrealized,
            ending_equity_points=ending_equity,

            average_winner_points=average_winner,
            average_loser_points=average_loser,
            expectancy_points=expectancy,

            **drawdown,
            equity_observations=len(result.equity_curve),
        )


__all__ = [
    "PerformanceAnalyzer",
    "PerformanceAnalyzerError",
    "PerformanceReport",
]
