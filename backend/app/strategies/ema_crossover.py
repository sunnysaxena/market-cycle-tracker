from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.engines.backtest_strategy import (
    BacktestStrategy,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)


class EmaCrossoverStrategy(BacktestStrategy):
    """
    Configurable EMA crossover strategy for index backtesting.

    Bullish crossover:
        Previous fast EMA <= previous slow EMA
        Current fast EMA > current slow EMA
        Flat -> LONG
        SHORT -> EXIT SHORT

    Bearish crossover:
        Previous fast EMA >= previous slow EMA
        Current fast EMA < current slow EMA
        Flat -> SHORT
        LONG -> EXIT LONG

    No crossover:
        No action.

    Indicator values are read from existing historical records.
    """

    def __init__(
        self,
        *,
        fast_period: int = 9,
        slow_period: int = 20,
        trade_mode: str = "BOTH",
    ) -> None:

        if (
            not isinstance(fast_period, int)
            or isinstance(fast_period, bool)
            or fast_period <= 0
        ):
            raise ValueError(
                "fast_period must be a positive integer."
            )

        if (
            not isinstance(slow_period, int)
            or isinstance(slow_period, bool)
            or slow_period <= 0
        ):
            raise ValueError(
                "slow_period must be a positive integer."
            )

        if fast_period >= slow_period:
            raise ValueError(
                "fast_period must be smaller than slow_period."
            )

        trade_mode = (
            trade_mode.strip().upper()
            if isinstance(trade_mode, str)
            else None
        )

        if trade_mode not in ("BOTH", "LONG_ONLY", "SHORT_ONLY"):
            raise ValueError(
                "trade_mode must be BOTH, LONG_ONLY or SHORT_ONLY."
            )

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.trade_mode = trade_mode

        self.fast_field = f"ema_{fast_period}"
        self.slow_field = f"ema_{slow_period}"

    @property
    def name(self) -> str:
        base_name = (
            f"EMA {self.fast_period}/{self.slow_period} "
            "Crossover"
        )

        if self.trade_mode == "BOTH":
            return base_name

        return f"{base_name} [{self.trade_mode}]"

    @staticmethod
    def _read_ema(
        record: Mapping[str, Any],
        field: str,
    ) -> Decimal | None:

        value = record.get(field)

        if value is None:
            return None

        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise StrategyContractError(
                f"Invalid indicator value for {field}: {value!r}."
            ) from exc

        if not result.is_finite():
            raise StrategyContractError(
                f"Indicator value for {field} must be finite."
            )

        return result

    def generate_signal(
        self,
        history: Sequence[Mapping[str, Any]],
        context: StrategyContext,
    ) -> TradeSignal | None:

        if not isinstance(context, StrategyContext):
            raise StrategyContractError(
                "context must be a StrategyContext."
            )

        if len(history) < 2:
            return None

        previous = history[-2]
        current = history[-1]

        if current.get("candle_date") != context.current_date:
            raise StrategyContractError(
                "Strategy context date must match the latest candle."
            )

        previous_fast = self._read_ema(
            previous,
            self.fast_field,
        )
        previous_slow = self._read_ema(
            previous,
            self.slow_field,
        )

        current_fast = self._read_ema(
            current,
            self.fast_field,
        )
        current_slow = self._read_ema(
            current,
            self.slow_field,
        )

        # Missing indicator values cannot generate a crossover.
        if None in (
            previous_fast,
            previous_slow,
            current_fast,
            current_slow,
        ):
            return None

        bullish_cross = (
            previous_fast <= previous_slow
            and current_fast > current_slow
        )

        bearish_cross = (
            previous_fast >= previous_slow
            and current_fast < current_slow
        )

        position = context.position

        if position is None:
            if (
                bullish_cross
                and self.trade_mode in ("BOTH", "LONG_ONLY")
            ):
                return TradeSignal(
                    action=SignalAction.ENTER,
                    side=PositionSide.LONG,
                    reason=(
                        f"Bullish EMA crossover: "
                        f"EMA {self.fast_period} moved above "
                        f"EMA {self.slow_period}."
                    ),
                )

            if (
                bearish_cross
                and self.trade_mode in ("BOTH", "SHORT_ONLY")
            ):
                return TradeSignal(
                    action=SignalAction.ENTER,
                    side=PositionSide.SHORT,
                    reason=(
                        f"Bearish EMA crossover: "
                        f"EMA {self.fast_period} moved below "
                        f"EMA {self.slow_period}."
                    ),
                )

            return None

        if (
            position.side is PositionSide.LONG
            and bearish_cross
        ):
            if self.trade_mode == "BOTH":
                return TradeSignal(
                    action=SignalAction.ENTER,
                    side=PositionSide.SHORT,
                    reason=(
                        f"Bearish EMA crossover reverses LONG to SHORT: "
                        f"EMA {self.fast_period} moved below "
                        f"EMA {self.slow_period}."
                    ),
                )

            return TradeSignal(
                action=SignalAction.EXIT,
                side=PositionSide.LONG,
                reason=(
                    f"Bearish EMA crossover closes LONG: "
                    f"SHORT entries disabled in {self.trade_mode} mode."
                ),
            )

        if (
            position.side is PositionSide.SHORT
            and bullish_cross
        ):
            if self.trade_mode == "BOTH":
                return TradeSignal(
                    action=SignalAction.ENTER,
                    side=PositionSide.LONG,
                    reason=(
                        f"Bullish EMA crossover reverses SHORT to LONG: "
                        f"EMA {self.fast_period} moved above "
                        f"EMA {self.slow_period}."
                    ),
                )

            return TradeSignal(
                action=SignalAction.EXIT,
                side=PositionSide.SHORT,
                reason=(
                    f"Bullish EMA crossover closes SHORT: "
                    f"LONG entries disabled in {self.trade_mode} mode."
                ),
            )

        return None


__all__ = ["EmaCrossoverStrategy"]
