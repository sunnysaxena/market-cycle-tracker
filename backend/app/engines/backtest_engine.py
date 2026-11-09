from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from app.engines.backtest_config import BacktestConfig
from app.engines.backtest_strategy import (
    BacktestStrategy,
    OpenPositionContext,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)


ZERO = Decimal("0")
ONE = Decimal("1")
BPS_DIVISOR = Decimal("10000")


class BacktestEngineError(ValueError):
    """Raised when historical data or execution is invalid."""


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    """A completed simulated directional index trade."""

    entry_date: date
    exit_date: date
    side: PositionSide

    entry_reference_price: Decimal
    entry_fill_price: Decimal
    exit_reference_price: Decimal
    exit_fill_price: Decimal

    quantity: Decimal

    gross_points: Decimal
    net_points: Decimal

    entry_reason: str
    exit_reason: str


@dataclass(frozen=True, slots=True)
class OpenPositionMark:
    """End-of-data valuation of a position not yet closed."""

    entry_date: date
    side: PositionSide
    entry_reference_price: Decimal
    entry_fill_price: Decimal
    mark_date: date
    mark_price: Decimal
    estimated_exit_fill_price: Decimal
    quantity: Decimal
    unrealized_points: Decimal
    entry_reason: str


@dataclass(frozen=True, slots=True)
class EquitySnapshot:
    """Daily realized and unrealized index-point equity."""

    candle_date: date
    realized_points: Decimal
    unrealized_points: Decimal
    equity_points: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Immutable summary of one historical backtest run."""

    strategy_name: str
    instrument_code: str
    timeframe: str
    import_batch_id: int

    total_candles: int
    evaluated_candles: int
    skipped_indicator_candles: int

    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquitySnapshot, ...]
    open_position: OpenPositionMark | None
    unexecuted_final_signal: TradeSignal | None

    @property
    def closed_trade_count(self) -> int:
        return len(self.trades)

    @property
    def total_gross_points(self) -> Decimal:
        return sum(
            (trade.gross_points for trade in self.trades),
            ZERO,
        )

    @property
    def total_net_points(self) -> Decimal:
        return sum(
            (trade.net_points for trade in self.trades),
            ZERO,
        )

    @property
    def winning_trades(self) -> int:
        return sum(
            trade.net_points > ZERO
            for trade in self.trades
        )

    @property
    def losing_trades(self) -> int:
        return sum(
            trade.net_points < ZERO
            for trade in self.trades
        )

    @property
    def win_rate_percent(self) -> Decimal:
        if not self.trades:
            return ZERO

        return (
            Decimal(self.winning_trades)
            / Decimal(len(self.trades))
            * Decimal("100")
        )


class _HistoryView(Sequence[Mapping[str, Any]]):
    """Fixed-length read-only view over eligible strategy history."""

    __slots__ = ("_records", "_length")

    def __init__(
        self,
        records: list[Mapping[str, Any]],
        length: int,
    ) -> None:
        if length < 0 or length > len(records):
            raise ValueError("Invalid history view length.")

        self._records = records
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __getitem__(
        self,
        index: int | slice,
    ) -> Mapping[str, Any] | tuple[Mapping[str, Any], ...]:
        if isinstance(index, slice):
            return tuple(
                self._records[i]
                for i in range(*index.indices(self._length))
            )

        if not isinstance(index, int):
            raise TypeError("History index must be an integer or slice.")

        if index < 0:
            index += self._length

        if index < 0 or index >= self._length:
            raise IndexError("History index out of range.")

        return self._records[index]


@dataclass(slots=True)
class _Position:
    side: PositionSide
    entry_date: date
    entry_reference_price: Decimal
    entry_fill_price: Decimal
    quantity: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    entry_reason: str


def _as_decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BacktestEngineError(
            f"{field_name} must be a valid decimal number."
        ) from exc

    if not result.is_finite():
        raise BacktestEngineError(
            f"{field_name} must be finite."
        )

    return result


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    raise BacktestEngineError(
        f"Invalid candle_date: {value!r}."
    )


def _entry_fill(
    reference_price: Decimal,
    side: PositionSide,
    slippage_bps: Decimal,
) -> Decimal:
    slippage = slippage_bps / BPS_DIVISOR

    if side is PositionSide.LONG:
        return reference_price * (ONE + slippage)

    return reference_price * (ONE - slippage)


def _exit_fill(
    reference_price: Decimal,
    side: PositionSide,
    slippage_bps: Decimal,
) -> Decimal:
    slippage = slippage_bps / BPS_DIVISOR

    if side is PositionSide.LONG:
        return reference_price * (ONE - slippage)

    return reference_price * (ONE + slippage)


def _direction_multiplier(side: PositionSide) -> Decimal:
    return ONE if side is PositionSide.LONG else Decimal("-1")


class BacktestEngine:
    """
    Strategy-independent historical execution simulator.

    Signals are generated after completed candles and scheduled
    for execution at the next candle's open.

    Protective stop-loss and take-profit checks use subsequent
    candle prices. If both are touched in one candle, stop-loss
    is assumed to execute first.

    Only one open position is supported in V1.

    P&L is expressed in underlying index points multiplied by
    the supplied synthetic quantity. It is not options-contract
    or broker-realistic rupee P&L.
    """

    def __init__(self, config: BacktestConfig):
        if not isinstance(config, BacktestConfig):
            raise TypeError("config must be a BacktestConfig.")

        self.config = config

    def run(
        self,
        records: Sequence[Mapping[str, Any]],
        strategy: BacktestStrategy,
        *,
        quantity: Decimal | int | float | str = Decimal("1"),
        warmup_bars: int = 0,
    ) -> BacktestResult:
        """
        Run a chronological simulation over historical candles.

        warmup_bars selects the last N candles before start_date.
        These candles seed strategy history only; they do not generate
        signals, execute trades, or contribute to result/equity counts.
        """

        if not isinstance(strategy, BacktestStrategy):
            raise TypeError(
                "strategy must implement BacktestStrategy."
            )

        if not isinstance(strategy.name, str) or not strategy.name.strip():
            raise BacktestEngineError(
                "Strategy name must be a non-empty string."
            )

        trade_quantity = _as_decimal(quantity, "quantity")

        if trade_quantity <= ZERO:
            raise BacktestEngineError(
                "quantity must be greater than zero."
            )

        # Validate warm-up configuration.
        if (
            not isinstance(warmup_bars, int)
            or isinstance(warmup_bars, bool)
            or warmup_bars < 0
        ):
            raise BacktestEngineError(
                "warmup_bars must be a non-negative integer."
            )

        if warmup_bars > 0 and self.config.start_date is None:
            raise BacktestEngineError(
                "warmup_bars requires start_date to be configured."
            )

        # Collect records through the configured end date.
        # Validate their chronological order before splitting them.
        candidates: list[tuple[date, Mapping[str, Any]]] = []
        previous_input_date: date | None = None

        for record in records:
            if not isinstance(record, Mapping):
                raise BacktestEngineError(
                    "Every historical candle must be a mapping."
                )

            candle_date = _as_date(record.get("candle_date"))

            if (
                previous_input_date is not None
                and candle_date <= previous_input_date
            ):
                raise BacktestEngineError(
                    "Historical candles must have strictly increasing "
                    "dates without duplicates."
                )

            previous_input_date = candle_date

            if (
                self.config.end_date is not None
                and candle_date > self.config.end_date
            ):
                continue

            candidates.append((candle_date, record))

        warmup_records: list[Mapping[str, Any]] = []

        if self.config.start_date is not None:
            earlier_records = [
                record
                for candle_date, record in candidates
                if candle_date < self.config.start_date
            ]

            active_records = [
                record
                for candle_date, record in candidates
                if candle_date >= self.config.start_date
            ]

            if warmup_bars > 0:
                warmup_records = earlier_records[-warmup_bars:]

            selected = warmup_records + active_records
        else:
            selected = [
                record for _, record in candidates
            ]

        warmup_count = len(warmup_records)

        # Validate and normalize candles without changing source records.
        normalized: list[dict[str, Any]] = []
        previous_date: date | None = None

        for record in selected:
            candle_date = _as_date(record.get("candle_date"))

            if previous_date is not None and candle_date <= previous_date:
                raise BacktestEngineError(
                    "Historical candles must have strictly increasing "
                    "dates without duplicates."
                )

            previous_date = candle_date

            if (
                "import_batch_id" in record
                and record["import_batch_id"]
                != self.config.import_batch_id
            ):
                raise BacktestEngineError(
                    "Historical record import_batch_id does not match "
                    "backtest configuration."
                )

            if (
                "instrument_code" in record
                and str(record["instrument_code"]).upper()
                != self.config.instrument_code
            ):
                raise BacktestEngineError(
                    "Historical record instrument_code does not match "
                    "backtest configuration."
                )

            bar = dict(record)
            bar["candle_date"] = candle_date

            for field in ("open", "high", "low", "close"):
                price = _as_decimal(record.get(field), field)

                if price <= ZERO:
                    raise BacktestEngineError(
                        f"{field} must be greater than zero."
                    )

                bar[field] = price

            if bar["high"] < max(bar["open"], bar["close"]):
                raise BacktestEngineError(
                    f"Invalid high price on {candle_date}."
                )

            if bar["low"] > min(bar["open"], bar["close"]):
                raise BacktestEngineError(
                    f"Invalid low price on {candle_date}."
                )

            if bar["high"] < bar["low"]:
                raise BacktestEngineError(
                    f"High cannot be below low on {candle_date}."
                )

            normalized.append(bar)

        # Strategy history contains only candles eligible under the
        # configured indicator-status policy. Execution and protective
        # price checks still process every market candle.
        strategy_history: list[Mapping[str, Any]] = []

        completed_trades: list[BacktestTrade] = []
        position: _Position | None = None
        pending_signal: TradeSignal | None = None

        evaluated_candles = 0
        skipped_indicator_candles = 0
        equity_curve: list[EquitySnapshot] = []

        slippage = self.config.slippage_bps

        def close_position(
            current_position: _Position,
            candle_date: date,
            reference_price: Decimal,
            reason: str,
        ) -> BacktestTrade:
            fill_price = _exit_fill(
                reference_price,
                current_position.side,
                slippage,
            )

            direction = _direction_multiplier(
                current_position.side
            )

            gross = (
                reference_price
                - current_position.entry_reference_price
            ) * current_position.quantity * direction

            net = (
                fill_price
                - current_position.entry_fill_price
            ) * current_position.quantity * direction

            return BacktestTrade(
                entry_date=current_position.entry_date,
                exit_date=candle_date,
                side=current_position.side,
                entry_reference_price=(
                    current_position.entry_reference_price
                ),
                entry_fill_price=current_position.entry_fill_price,
                exit_reference_price=reference_price,
                exit_fill_price=fill_price,
                quantity=current_position.quantity,
                gross_points=gross,
                net_points=net,
                entry_reason=current_position.entry_reason,
                exit_reason=reason,
            )

        def gap_exit(
            current_position: _Position,
            opening_price: Decimal,
        ) -> tuple[Decimal, str] | None:
            if current_position.side is PositionSide.LONG:
                if (
                    current_position.stop_loss is not None
                    and opening_price <= current_position.stop_loss
                ):
                    return opening_price, "STOP_LOSS_GAP"

                if (
                    current_position.take_profit is not None
                    and opening_price >= current_position.take_profit
                ):
                    return opening_price, "TAKE_PROFIT_GAP"

            else:
                if (
                    current_position.stop_loss is not None
                    and opening_price >= current_position.stop_loss
                ):
                    return opening_price, "STOP_LOSS_GAP"

                if (
                    current_position.take_profit is not None
                    and opening_price <= current_position.take_profit
                ):
                    return opening_price, "TAKE_PROFIT_GAP"

            return None

        def intrabar_exit(
            current_position: _Position,
            bar: Mapping[str, Any],
        ) -> tuple[Decimal, str] | None:
            high = bar["high"]
            low = bar["low"]

            if current_position.side is PositionSide.LONG:
                stop_hit = (
                    current_position.stop_loss is not None
                    and low <= current_position.stop_loss
                )
                target_hit = (
                    current_position.take_profit is not None
                    and high >= current_position.take_profit
                )
            else:
                stop_hit = (
                    current_position.stop_loss is not None
                    and high >= current_position.stop_loss
                )
                target_hit = (
                    current_position.take_profit is not None
                    and low <= current_position.take_profit
                )

            # Conservative assumption when intrabar sequence is unknown.
            if stop_hit:
                return current_position.stop_loss, "STOP_LOSS"

            if target_hit:
                return current_position.take_profit, "TAKE_PROFIT"

            return None

        def record_equity(bar: Mapping[str, Any]) -> None:
            realized = sum(
                (trade.net_points for trade in completed_trades),
                ZERO,
            )

            unrealized = ZERO

            if position is not None:
                estimated_exit_fill = _exit_fill(
                    bar["close"],
                    position.side,
                    slippage,
                )

                unrealized = (
                    estimated_exit_fill - position.entry_fill_price
                ) * position.quantity * _direction_multiplier(
                    position.side
                )

            equity_curve.append(
                EquitySnapshot(
                    candle_date=bar["candle_date"],
                    realized_points=realized,
                    unrealized_points=unrealized,
                    equity_points=realized + unrealized,
                )
            )

        for index, bar in enumerate(normalized):
            candle_date = bar["candle_date"]
            opening_price = bar["open"]

            # Warm-up candles seed historical strategy context only.
            # They never execute orders, evaluate signals, or record
            # equity snapshots.
            if (
                self.config.start_date is not None
                and candle_date < self.config.start_date
            ):
                if (
                    self.config.indicator_status_policy == "ALL"
                    or bar.get("indicator_calculation_status") == "ready"
                ):
                    strategy_history.append(
                        MappingProxyType(bar)
                    )

                continue

            # 1. Check opening gaps on positions carried into this candle.
            if position is not None:
                exit_event = gap_exit(position, opening_price)

                if exit_event is not None:
                    reference_price, reason = exit_event
                    completed_trades.append(
                        close_position(
                            position,
                            candle_date,
                            reference_price,
                            reason,
                        )
                    )
                    position = None

            # 2. Execute the signal created at the previous candle close.
            if pending_signal is not None:
                signal = pending_signal
                pending_signal = None

                if signal.action is SignalAction.ENTER:

                    # An opposing entry signal closes the existing
                    # position and reverses direction at this candle's
                    # open. Both exit and entry fills include slippage.
                    if (
                        position is not None
                        and signal.side is not position.side
                    ):
                        completed_trades.append(
                            close_position(
                                position,
                                candle_date,
                                opening_price,
                                f"REVERSAL: {signal.reason}",
                            )
                        )
                        position = None

                    # Open a new position when flat, including after
                    # closing an existing position for reversal.
                    if position is None:
                        reference_price = opening_price
                        fill_price = _entry_fill(
                            reference_price,
                            signal.side,
                            slippage,
                        )

                        stop_loss = signal.stop_loss
                        take_profit = signal.take_profit

                        if signal.side is PositionSide.LONG:
                            if (
                                stop_loss is not None
                                and stop_loss >= fill_price
                            ):
                                raise StrategyContractError(
                                    "LONG stop_loss must be below "
                                    "the actual entry fill."
                                )

                            if (
                                take_profit is not None
                                and take_profit <= fill_price
                            ):
                                raise StrategyContractError(
                                    "LONG take_profit must be above "
                                    "the actual entry fill."
                                )
                        else:
                            if (
                                stop_loss is not None
                                and stop_loss <= fill_price
                            ):
                                raise StrategyContractError(
                                    "SHORT stop_loss must be above "
                                    "the actual entry fill."
                                )

                            if (
                                take_profit is not None
                                and take_profit >= fill_price
                            ):
                                raise StrategyContractError(
                                    "SHORT take_profit must be below "
                                    "the actual entry fill."
                                )

                        position = _Position(
                            side=signal.side,
                            entry_date=candle_date,
                            entry_reference_price=reference_price,
                            entry_fill_price=fill_price,
                            quantity=trade_quantity,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            entry_reason=signal.reason,
                        )

                elif signal.action is SignalAction.EXIT:
                    if position is not None:
                        if signal.side is not position.side:
                            raise StrategyContractError(
                                "EXIT signal side does not match "
                                "the open position."
                            )

                        completed_trades.append(
                            close_position(
                                position,
                                candle_date,
                                opening_price,
                                signal.reason,
                            )
                        )
                        position = None

            # 3. Check intrabar protective levels.
            if position is not None:
                exit_event = intrabar_exit(position, bar)

                if exit_event is not None:
                    reference_price, reason = exit_event
                    completed_trades.append(
                        close_position(
                            position,
                            candle_date,
                            reference_price,
                            reason,
                        )
                    )
                    position = None

            # 4. Evaluate only after this candle is complete.
            if (
                self.config.indicator_status_policy == "READY_ONLY"
                and bar.get("indicator_calculation_status") != "ready"
            ):
                skipped_indicator_candles += 1
                record_equity(bar)
                continue

            # Only eligible candles are visible to the strategy.
            # Market execution and protective checks above still use
            # every candle, regardless of indicator status.
            strategy_history.append(MappingProxyType(bar))

            evaluated_candles += 1

            history = _HistoryView(
                strategy_history,
                len(strategy_history),
            )

            position_context = None

            if position is not None:
                position_context = OpenPositionContext(
                    side=position.side,
                    entry_date=position.entry_date,
                    entry_reference_price=position.entry_reference_price,
                    entry_fill_price=position.entry_fill_price,
                    quantity=position.quantity,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    entry_reason=position.entry_reason,
                )

            context = StrategyContext(
                current_date=candle_date,
                current_close=bar["close"],
                position=position_context,
            )

            signal = strategy.generate_signal(history, context)

            if signal is None:
                record_equity(bar)
                continue

            if not isinstance(signal, TradeSignal):
                raise StrategyContractError(
                    "generate_signal must return TradeSignal or None."
                )

            # Schedule actions for the NEXT candle only.
            if position is None:
                if signal.action is SignalAction.ENTER:
                    pending_signal = signal

            elif signal.action is SignalAction.EXIT:
                if signal.side is not position.side:
                    raise StrategyContractError(
                        "EXIT signal side does not match "
                        "the open position."
                    )

                pending_signal = signal

            elif (
                signal.action is SignalAction.ENTER
                and signal.side is not position.side
            ):
                # An opposing ENTER signal requests a reversal.
                # The execution engine will close the existing
                # position and open the new side at next bar open.
                pending_signal = signal

            # Same-direction ENTER signals are ignored while a
            # position is already open.

            record_equity(bar)

        # 5. Mark any remaining position without forcing a final exit.
        open_position_mark: OpenPositionMark | None = None

        if position is not None and normalized:
            last_bar = normalized[-1]
            mark_price = last_bar["close"]

            estimated_exit = _exit_fill(
                mark_price,
                position.side,
                slippage,
            )

            unrealized = (
                estimated_exit - position.entry_fill_price
            ) * position.quantity * _direction_multiplier(
                position.side
            )

            open_position_mark = OpenPositionMark(
                entry_date=position.entry_date,
                side=position.side,
                entry_reference_price=position.entry_reference_price,
                entry_fill_price=position.entry_fill_price,
                mark_date=last_bar["candle_date"],
                mark_price=mark_price,
                estimated_exit_fill_price=estimated_exit,
                quantity=position.quantity,
                unrealized_points=unrealized,
                entry_reason=position.entry_reason,
            )

        return BacktestResult(
            strategy_name=strategy.name.strip(),
            instrument_code=self.config.instrument_code,
            timeframe=self.config.timeframe,
            import_batch_id=self.config.import_batch_id,
            total_candles=len(normalized) - warmup_count,
            evaluated_candles=evaluated_candles,
            skipped_indicator_candles=skipped_indicator_candles,
            trades=tuple(completed_trades),
            equity_curve=tuple(equity_curve),
            open_position=open_position_mark,
            unexecuted_final_signal=pending_signal,
        )


__all__ = [
    "BacktestEngine",
    "BacktestEngineError",
    "BacktestTrade",
    "EquitySnapshot",
    "OpenPositionMark",
    "BacktestResult",
]
